"""Модель основной памяти и кеша.

MainMemory - идеальная память без задержек.
Cache - direct-mapped, write-back, write-allocate, 4 строки x 4 слова.
Геометрия адреса: tag 28 бит, index 2 бит, offset 2 бит.
Тайминги: hit=1, miss=1+9, dirty eviction=1+9+9.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from machine import MMIOController

log = logging.getLogger(__name__)

_OFFSET_BITS = 2
_INDEX_BITS = 2
_OFFSET_MASK = (1 << _OFFSET_BITS) - 1
_INDEX_MASK = (1 << _INDEX_BITS) - 1

MMIO_BASE = 0xFFFFFFF0


class _Op(Enum):
    Read = auto()
    Write = auto()


@dataclass
class CacheStats:
    """Статистика кеша для демонстрации эффекта кеша."""

    hits: int = 0
    misses: int = 0
    writebacks: int = 0


@dataclass
class _Line:
    valid: bool = False
    dirty: bool = False
    tag: int = -1
    data: list[int] = field(default_factory=lambda: [0] * 4)


class MainMemory:
    """Идеальная память без задержек.

    Адресация байтовая: снаружи все адреса в байтах и выровнены на 4.
    Внутри хранится list[int] из 32-битных слов (индекс = addr >> 2).
    Размер ``size`` задаётся в словах. Все задержки - ответственность Cache.
    """

    def __init__(self, size: int = 65536) -> None:
        self._data = [0] * size

    def read(self, addr: int) -> int:
        """Прочитать слово по байтовому адресу (выровнен на 4)."""
        assert addr & 3 == 0, f"unaligned read at 0x{addr:08X}"
        return self._data[addr >> 2]

    def write(self, addr: int, val: int) -> None:
        """Записать слово по байтовому адресу (выровнен на 4)."""
        assert addr & 3 == 0, f"unaligned write at 0x{addr:08X}"
        self._data[addr >> 2] = val

    def load_image(self, words: list[int], at: int = 0) -> None:
        """Загрузить список слов начиная с байтового адреса at (выровнен на 4)."""
        assert at & 3 == 0, f"unaligned load at 0x{at:08X}"
        base = at >> 2
        for i, w in enumerate(words):
            self._data[base + i] = w


class Cache:
    """Direct-mapped write-back write-allocate кеш.

    Геометрия фиксирована константами модуля: _INDEX_BITS строк по
    _OFFSET_BITS слов (4 строки x 4 слова). Это согласовано с _split.

    Тайминги (в тактах):
      hit:            1
      miss:           1 + miss_penalty
      dirty eviction: 1 + miss_penalty + miss_penalty
    """

    def __init__(
        self,
        ram: MainMemory,
        miss_penalty: int = 9,
        mmio: MMIOController | None = None,
    ) -> None:
        self._ram = ram
        self._wpl = 1 << _OFFSET_BITS
        self._penalty = miss_penalty
        self._mmio = mmio
        self._cache: list[_Line] = [_Line(data=[0] * self._wpl) for _ in range(1 << _INDEX_BITS)]
        self.stats = CacheStats()

        # Состояние текущего запроса
        self._busy = False
        self._stall: int = 0
        self._op: _Op = _Op.Read
        self._addr: int = 0
        self._write_val: int = 0
        self._result: int = 0

    def request(self, addr: int, op: str, data: int = 0) -> None:
        """Запустить операцию чтения или записи.

        op: "read" или "write".
        Нельзя вызывать пока is_busy() == True.
        """
        assert not self._busy, "Cache.request() вызван пока кеш занят"
        self._op = _Op.Read if op == "read" else _Op.Write
        self._addr = addr
        self._write_val = data
        self._busy = True

        if addr >= MMIO_BASE:
            # MMIO bypass - 1 такт, без stall
            self._stall = 0
            return

        tag, index, offset = _split(addr)
        line = self._cache[index]
        hit = line.valid and line.tag == tag

        if hit:
            self.stats.hits += 1
            log.debug("cache %-5s addr=0x%08X → HIT  line=%d", op.upper(), addr, index)
            self._execute_hit(line, offset)
            self._busy = False
        else:
            self.stats.misses += 1
            stall = self._penalty
            if line.valid and line.dirty:
                stall += self._penalty
                self.stats.writebacks += 1
                wb_base = _line_byte_base(line.tag, index)
                log.debug(
                    "cache %-5s addr=0x%08X → MISS line=%d evict=DIRTY wb=0x%08X (stall %d)",
                    op.upper(),
                    addr,
                    index,
                    wb_base,
                    stall,
                )
            else:
                log.debug(
                    "cache %-5s addr=0x%08X → MISS line=%d (stall %d)",
                    op.upper(),
                    addr,
                    index,
                    stall,
                )
            self._stall = stall

    def tick(self) -> None:
        """Продвинуть кеш на один такт.

        Когда stall исчерпан - выполняет операцию и снимает busy.
        """
        if not self._busy:
            return
        if self._stall > 0:
            self._stall -= 1
            return
        # Stall исчерпан - выполняем операцию
        self._execute()
        self._busy = False

    def is_busy(self) -> bool:
        """True если кеш ещё обрабатывает запрос."""
        return self._busy

    def response(self) -> int:
        """Результат последнего read-запроса. Вызывать после is_busy() == False."""
        assert not self._busy, "response() вызван пока кеш занят"
        return self._result

    def _execute(self) -> None:
        addr = self._addr

        if addr >= MMIO_BASE:
            self._mmio_request(addr, self._op, self._write_val)
            return

        tag, index, offset = _split(addr)
        line = self._cache[index]

        # Writeback грязной вытесняемой строки
        if line.valid and line.tag != tag and line.dirty:
            old_base = _line_byte_base(line.tag, index)
            for i in range(self._wpl):
                self._ram.write(old_base + i * 4, line.data[i])
            line.dirty = False

        # Загрузка строки (miss)
        if not line.valid or line.tag != tag:
            line_base = _line_byte_base(tag, index)
            line.data = [self._ram.read(line_base + i * 4) for i in range(self._wpl)]
            line.tag = tag
            line.valid = True
            line.dirty = False

        # Выполняем операцию
        if self._op == _Op.Read:
            self._result = line.data[offset]
        else:
            line.data[offset] = self._write_val
            line.dirty = True

    def _execute_hit(self, line: _Line, offset: int) -> None:
        """Выполнить операцию по строке, которая уже в кеше (hit)."""
        if self._op == _Op.Read:
            self._result = line.data[offset]
        else:
            line.data[offset] = self._write_val
            line.dirty = True

    def _mmio_request(self, addr: int, op: _Op, data: int) -> None:
        if self._mmio is not None:
            if op == _Op.Read:
                self._result = self._mmio.read(addr)
            else:
                self._mmio.write(addr, data)
        else:
            # Заглушка: используется в тестах cache без machine
            if op == _Op.Read:
                self._result = self._ram.read(addr)
            else:
                self._ram.write(addr, data)


def _split(byte_addr: int) -> tuple[int, int, int]:
    """Разбить БАЙТОВЫЙ адрес (выровнен на 4) на (tag, index, offset).

    Сначала переходим к адресу слова (byte_addr >> 2), затем как раньше:
    offset - слово внутри строки, index - номер строки, tag - остальное.

    >>> _split(0x00000000)
    (0, 0, 0)
    >>> _split(0x00000004)
    (0, 0, 1)
    >>> _split(0x00000010)
    (0, 1, 0)
    >>> _split(0x00000040)
    (1, 0, 0)
    >>> _split(0x0000005C)
    (1, 1, 3)
    """
    word_addr = byte_addr >> 2
    offset = word_addr & _OFFSET_MASK
    index = (word_addr >> _OFFSET_BITS) & _INDEX_MASK
    tag = word_addr >> (_OFFSET_BITS + _INDEX_BITS)
    return tag, index, offset


def _line_byte_base(tag: int, index: int) -> int:
    """Байтовый адрес первого слова строки (tag, index)."""
    word_base = (tag << (_OFFSET_BITS + _INDEX_BITS)) | (index << _OFFSET_BITS)
    return word_base << 2
