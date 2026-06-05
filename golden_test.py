"""Golden тесты транслятора и машины Forth.

Конфигурационные файлы: golden/*.yml
"""

import collections
import logging

import pytest

from isa import to_hex
from machine import simulation
from translator import translate

# Формат журнала совпадает с machine.basicConfig (раздел __main__).
_LOG_FORMAT = "%(levelname)-7s %(module)s:%(funcName)-13s %(message)s"

# Логгеры, которые попадают в журнал процессора: такты машины и события кеша.
_PROC_LOGGERS = ("machine", "cache")

# Размер «окна» журнала: начало (старт) + конец (HALT). Середина — длинные
# повторяющиеся stall'ы и тело циклов — схлопывается в одну пометку.
_HEAD = 80
_TAIL = 40


class CompactLogHandler(logging.Handler):
    """Ring-buffer для журнала: держит первые _HEAD и последние _TAIL записей.

    Для тяжёлых программ (prob1 — миллионы тактов) хранить весь журнал в ОЗУ
    нельзя. Этот handler репрезентативно адаптирует журнал под алгоритм:
    видны старт и финал, а длинная середина схлопывается в одну строку
    «... <N log records skipped> ...» (требование задания, раздел Тестирование).
    """

    def __init__(self, head: int = _HEAD, tail: int = _TAIL) -> None:
        super().__init__()
        self.head: list[str] = []
        self.tail: collections.deque[str] = collections.deque(maxlen=tail)
        self.head_limit = head
        self.total = 0

    def emit(self, record: logging.LogRecord) -> None:
        self.total += 1
        msg = self.format(record)
        if len(self.head) < self.head_limit:
            self.head.append(msg)
        else:
            self.tail.append(msg)

    def get_text(self) -> str:
        if self.total <= self.head_limit:
            return "\n".join(self.head)
        skipped = self.total - self.head_limit - len(self.tail)
        if skipped <= 0:
            return "\n".join([*self.head, *self.tail])
        return "\n".join(self.head) + f"\n... <{skipped} log records skipped> ...\n" + "\n".join(self.tail)


@pytest.mark.golden_test("golden/*.yml")
def test_translator_and_machine(golden):  # type: ignore[no-untyped-def]
    """Golden-тест: транслятор + симуляция.

    Поля YAML:
      in_source   -- Forth-исходник
      in_stdin    -- строка ввода для симуляции
      out_code_hex -- текстовый дамп бинаря (опционально)
      out_stdout  -- ожидаемый вывод программы
      out_log     -- адаптированный журнал процессора (старт + финал)
    """
    source: str = golden["in_source"]
    stdin_str: str = golden["in_stdin"]
    limit: int = golden.get("in_limit", 1_000_000)

    handler = CompactLogHandler()
    handler.setFormatter(logging.Formatter(_LOG_FORMAT))
    loggers = [logging.getLogger(name) for name in _PROC_LOGGERS]
    saved = [(lg.level, lg.propagate) for lg in loggers]
    for lg in loggers:
        lg.addHandler(handler)
        lg.setLevel(logging.DEBUG)
        lg.propagate = False
    try:
        code = translate(source)
        input_tokens = [ord(c) for c in stdin_str]
        output, _ticks, _stats = simulation(code, input_tokens, limit=limit)
    finally:
        for lg, (level, propagate) in zip(loggers, saved, strict=True):
            lg.removeHandler(handler)
            lg.setLevel(level)
            lg.propagate = propagate

    stdout = "".join(chr(v) for v in output)

    assert to_hex(code) == golden.out["out_code_hex"]
    assert stdout == golden.out["out_stdout"]
    assert handler.get_text() == golden.out["out_log"]
