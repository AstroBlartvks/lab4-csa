"""Модель процессора: DataPath, ControlUnit, simulation.

Архитектура: стековая машина, Neumann, микрокодированный CU, кеш.
Вариант: forth | stack | neum | mc | tick | binary | stream | mem | cstr | prob1 | cache
"""

from __future__ import annotations

import logging
import struct
import sys
from collections.abc import Callable

from cache import Cache, CacheStats, MainMemory
from isa import Instruction, Opcode, from_bytes, to_bytes
from microcode import (
    MPC_OF_OPCODE,
    MPROGRAM,
    AluOp,
    AluOpSel,
    DStackPop,
    DStackPush,
    Halt,
    LatchIr,
    LatchMar,
    LatchMdr,
    LatchMpc,
    LatchNos,
    LatchPc,
    LatchTors,
    LatchTos,
    MarSel,
    MdrSel,
    MemOp,
    MemRequest,
    MpcSel,
    NosSel,
    PcSel,
    RStackPop,
    RStackPush,
    Signal,
    TorsSel,
    TosSel,
)

log = logging.getLogger(__name__)

MMIO_IN_PORT = 0xFFFFFFF0
MMIO_IN_STATUS = 0xFFFFFFF1
MMIO_OUT_PORT = 0xFFFFFFF2

_MEM_SIZE = 65536
_DS_SIZE = 256
_RS_SIZE = 256

# Таблица арифметических/побитовых ALU-операций (без сравнений)
_ALU_OPS: dict[AluOpSel, Callable[[int, int], int]] = {
    AluOpSel.Add: lambda a, b: a + b,
    AluOpSel.Sub: lambda a, b: a - b,
    AluOpSel.Mul: lambda a, b: a * b,
    AluOpSel.Div: lambda a, b: int(a / b),  # округление к нулю
    AluOpSel.Mod: lambda a, b: a - int(a / b) * b,  # знак от делимого
    AluOpSel.And: lambda a, b: a & b,
    AluOpSel.Or: lambda a, b: a | b,
    AluOpSel.Invert: lambda a, b: ~b,  # унарная, a не используется
}


class MMIOController:
    """Контроллер ввода/вывода в стиле memory-mapped (stream).

    Адреса:
      0xFFFFFFF0  IN_PORT   - чтение следующего токена из input-буфера
      0xFFFFFFF1  IN_STATUS - 1 если есть данные, 0 если EOF
      0xFFFFFFF2  OUT_PORT  - запись токена в output-буфер
    """

    def __init__(self, input_tokens: list[int]) -> None:
        self._input = list(input_tokens)
        self.output: list[int] = []

    def read(self, addr: int) -> int:
        """Прочитать из порта. Вызов IN_PORT при пустом буфере → EOFError."""
        if addr == MMIO_IN_PORT:
            if not self._input:
                raise EOFError
            return self._input.pop(0)
        if addr == MMIO_IN_STATUS:
            return 1 if self._input else 0
        return 0

    def write(self, addr: int, val: int) -> None:
        """Записать в порт."""
        if addr == MMIO_OUT_PORT:
            self.output.append(val)
            log.debug("output: %d (0x%02X)", val, val & 0xFF)

    def is_eof(self) -> bool:
        """True если входной буфер исчерпан."""
        return not self._input


class DataPath:
    """Тракт данных стековой машины.

    Методы соответствуют сигналам из MICROCODE.md раздел 2.
    Каждый метод исполняется за один такт.

    >>> from cache import Cache, MainMemory
    >>> ram = MainMemory(); cache = Cache(ram)
    >>> dp = DataPath(cache)
    >>> dp.flag_z
    True
    >>> dp.mdr = 42; dp.latch_tos(TosSel.FromMdr)
    >>> dp.tos
    42
    >>> dp.flag_z
    False
    """

    def __init__(self, cache: Cache) -> None:
        self._cache = cache
        # Регистры
        self.pc: int = 0
        self.ir: int = 0
        self.tos: int = 0
        self.nos: int = 0
        self.dsp: int = 0
        self.tors: int = 0
        self.rsp: int = 0
        self.mar: int = 0
        self.mdr: int = 0
        self._alu_result: int = 0
        # SRAM стеков
        self._ds: list[int] = [0] * _DS_SIZE
        self._rs: list[int] = [0] * _RS_SIZE

    # Флаги - combinational от TOS
    @property
    def flag_z(self) -> bool:
        """Zero: TOS == 0."""
        return self.tos == 0

    @property
    def flag_n(self) -> bool:
        """Negative: TOS < 0."""
        return self.tos < 0

    @property
    def ir_operand(self) -> int:
        """24-битный операнд из IR."""
        return self.ir & 0x00FFFFFF

    def latch_pc(self, sel: PcSel) -> None:
        """PC ← (sel). Адресация байтовая: следующее слово = PC+4."""
        if sel == PcSel.Next:
            self.pc += 4
        elif sel == PcSel.Jmp:
            self.pc = self.ir_operand
        elif sel == PcSel.Jz:
            if self.flag_z:
                self.pc = self.ir_operand
            # иначе PC уже инкрементирован в FETCH, оставляем как есть
        elif sel == PcSel.FromTors:
            self.pc = self.tors
        elif sel == PcSel.FromTos:
            self.pc = self.tos

    def latch_ir(self) -> None:
        """IR ← MDR."""
        self.ir = self.mdr

    def latch_mar(self, sel: MarSel) -> None:
        """MAR ← (sel)."""
        if sel == MarSel.FromPc:
            self.mar = self.pc
        elif sel == MarSel.FromTos:
            self.mar = self.tos

    def latch_mdr(self, sel: MdrSel) -> None:
        """MDR ← (sel)."""
        if sel == MdrSel.FromMem:
            raw = self._cache.response()
            # Знаковое расширение: 32-битное unsigned → signed Python int
            self.mdr = (raw + 0x80000000) % 0x100000000 - 0x80000000
        elif sel == MdrSel.FromNos:
            self.mdr = self.nos
        elif sel == MdrSel.FromTos:
            self.mdr = self.tos

    def latch_tos(self, sel: TosSel) -> None:
        """TOS ← (sel)."""
        if sel == TosSel.FromAlu:
            # ALU результат уже лежит в _alu_result, выставленном alu_op()
            self.tos = self._alu_result
        elif sel == TosSel.FromMdr:
            self.tos = self.mdr
        elif sel == TosSel.FromNos:
            self.tos = self.nos
        elif sel == TosSel.FromTors:
            self.tos = self.tors

    def latch_nos(self, sel: NosSel) -> None:
        """NOS ← (sel). Только для SWAP (без push/pop)."""
        if sel == NosSel.FromTos:
            self.nos = self.tos
        elif sel == NosSel.FromMdr:
            self.nos = self.mdr

    def latch_tors(self, sel: TorsSel) -> None:
        """TORS ← (sel)."""
        if sel == TorsSel.FromPc:
            self.tors = self.pc
        elif sel == TorsSel.FromTos:
            self.tors = self.tos

    def dstack_push(self) -> None:
        """DS_SRAM[DSP] ← NOS; DSP++; NOS ← TOS."""
        self._ds[self.dsp] = self.nos
        self.dsp = (self.dsp + 1) & 0xFF
        self.nos = self.tos

    def dstack_pop(self) -> None:
        """DSP--; NOS ← DS_SRAM[DSP]."""
        self.dsp = (self.dsp - 1) & 0xFF
        self.nos = self._ds[self.dsp]

    def rstack_push(self) -> None:
        """RS_SRAM[RSP] ← TORS; RSP++."""
        self._rs[self.rsp] = self.tors
        self.rsp = (self.rsp + 1) & 0xFF

    def rstack_pop(self) -> None:
        """RSP ← RSP-1; TORS ← RS_SRAM[RSP-1] (после декремента).

        RSP указывает на первый свободный слот. Снимаемое значение
        (старая вершина) уже извлечено вызывающим до pop: RET читает PC
        из TORS, а R> копирует TORS в TOS. Поэтому pop лишь ВОССТАНАВЛИВАЕТ
        TORS родительского кадра.

        push кладёт в SRAM то значение TORS, что было активно при входе в
        кадр (CALL делает TORS←PC ДО push, см. microcode CALL/TO_R). Значит
        TORS родителя лежит в RS[RSP_new-1], и читается именно оттуда.
        Симметрии с dstack_pop (читает RS[RSP_new]) здесь нет намеренно:
        у data-стека push сохраняет NOS, у return-стека - сам TORS.
        """
        self.rsp = (self.rsp - 1) & 0xFF
        self.tors = self._rs[(self.rsp - 1) & 0xFF]

    def alu_op(self, op: AluOpSel) -> None:
        """Вычислить ALU(NOS op TOS), результат в _alu_result."""
        self._alu_result = self._alu(op, self.nos, self.tos)

    def mem_request(self, op: MemOp) -> None:
        """Отправить запрос в кеш по адресу MAR (нормализован к unsigned)."""
        addr = self.mar & 0xFFFFFFFF
        if op == MemOp.Read:
            self._cache.request(addr, "read")
        else:
            self._cache.request(addr, "write", data=self.mdr)

    def _alu(self, op: AluOpSel, a: int, b: int) -> int:
        """Вычислить ALU-операцию. Результат - знаковое 32-битное."""
        # Сравнения возвращают Forth-флаг (-1/0) без нормализации
        if op == AluOpSel.Eq:
            return -1 if a == b else 0
        if op == AluOpSel.Lt:
            return -1 if a < b else 0
        if op == AluOpSel.Gt:
            return -1 if a > b else 0
        raw = _ALU_OPS[op](a, b)
        return (raw + 0x80000000) % 0x100000000 - 0x80000000


class ControlUnit:
    """Микрокодированный блок управления.

    Один такт = одна микроинструкция из MPROGRAM[mpc].
    Stall кеша: если cache.is_busy() - такт не продвигает mpc.
    """

    def __init__(self, dp: DataPath, cache: Cache) -> None:
        self._dp = dp
        self._cache = cache
        self.mpc: int = 0
        self._halt = False

    def tick(self) -> bool:
        """Исполнить один такт. Вернуть False если HALT."""
        if self._cache.is_busy():
            self._cache.tick()
            return True
        return self._execute_uinstr()

    def _execute_uinstr(self) -> bool:
        """Исполнить одну микроинструкцию. Вернуть False если HALT."""
        mpc_signal: LatchMpc | None = None
        halt_seen = False

        for sig in MPROGRAM[self.mpc]:
            if isinstance(sig, LatchMpc):
                mpc_signal = sig
            elif isinstance(sig, Halt):
                halt_seen = True
            else:
                self._apply(sig)

        if halt_seen:
            return False
        if mpc_signal is not None:
            self._apply_mpc(mpc_signal)
        return True

    def _apply(self, sig: Signal) -> None:
        """Диспетчеризация сигнала на DataPath."""
        dp = self._dp
        if isinstance(sig, LatchPc):
            dp.latch_pc(sig.sel)
        elif isinstance(sig, LatchIr):
            dp.latch_ir()
        elif isinstance(sig, LatchMar):
            dp.latch_mar(sig.sel)
        elif isinstance(sig, LatchMdr):
            dp.latch_mdr(sig.sel)
        elif isinstance(sig, LatchTos):
            dp.latch_tos(sig.sel)
        else:
            self._apply_stack_mem(sig)

    def _apply_stack_mem(self, sig: Signal) -> None:
        """LatchNos/Tors, стековые операции, AluOp, MemRequest."""
        dp = self._dp
        if isinstance(sig, LatchNos):
            dp.latch_nos(sig.sel)
        elif isinstance(sig, LatchTors):
            dp.latch_tors(sig.sel)
        elif isinstance(sig, AluOp):
            dp.alu_op(sig.op)
        elif isinstance(sig, MemRequest):
            dp.mem_request(sig.op)
        else:
            self._apply_stacks(sig)

    def _apply_stacks(self, sig: Signal) -> None:
        """DStack/RStack push/pop."""
        dp = self._dp
        if isinstance(sig, DStackPush):
            dp.dstack_push()
        elif isinstance(sig, DStackPop):
            dp.dstack_pop()
        elif isinstance(sig, RStackPush):
            dp.rstack_push()
        elif isinstance(sig, RStackPop):
            dp.rstack_pop()

    def _apply_mpc(self, sig: LatchMpc) -> None:
        if sig.sel == MpcSel.Zero:
            self.mpc = 0
        elif sig.sel == MpcSel.Next:
            self.mpc += 1
        elif sig.sel == MpcSel.Opcode:
            opcode = Opcode(self._dp.ir >> 24)
            self.mpc = MPC_OF_OPCODE[opcode]


def simulation(
    code: list[Instruction],
    input_tokens: list[int],
    limit: int = 1_000_000,
) -> tuple[list[int], int, CacheStats]:
    """Запустить симуляцию. Вернуть (output, ticks, cache_stats).

    >>> code: list[Instruction] = [{"opcode": Opcode.LIT, "operand": 42}, {"opcode": Opcode.HALT, "operand": 0}]
    >>> output, ticks, stats = simulation(code, [])
    >>> output
    []
    >>> ticks > 0
    True
    >>> stats.hits >= 0
    True
    """
    ram = MainMemory(_MEM_SIZE)
    mmio = MMIOController(input_tokens)
    cache = Cache(ram, mmio=mmio)
    dp = DataPath(cache)
    cu = ControlUnit(dp, cache)

    binary = to_bytes(code)
    n = len(binary) // 4
    words = list(struct.unpack(f">{n}I", binary))
    ram.load_image(words)

    ticks = 0
    running = True
    try:
        while running and ticks < limit:
            if log.isEnabledFor(logging.DEBUG):
                mnem = _mnemonic_of_ir(ram.read(dp.pc)) if cu.mpc == 0 else ""
                log.debug(
                    "TICK:%4d PC:%4d mPC:%2d TOS:%10d NOS:%10d  %s",
                    ticks,
                    dp.pc,
                    cu.mpc,
                    dp.tos,
                    dp.nos,
                    mnem,
                )
            running = cu.tick()
            ticks += 1
    except EOFError:
        log.warning("Input buffer exhausted (EOF)")

    if ticks >= limit:
        log.warning("Simulation limit reached (%d ticks)", limit)

    log.info("output: %r", mmio.output)
    log.info("ticks: %d", ticks)
    log.info(
        "cache: hits=%d misses=%d writebacks=%d",
        cache.stats.hits,
        cache.stats.misses,
        cache.stats.writebacks,
    )
    return mmio.output, ticks, cache.stats


def _mnemonic_of_ir(ir: int) -> str:
    from isa import MNEMONICS

    try:
        return MNEMONICS[Opcode(ir >> 24)]
    except (ValueError, KeyError):
        return f"???(0x{ir:08X})"


def main() -> None:
    """Запуск симуляции из командной строки.

    Использование: machine.py <code.bin> <input.txt> [--log]
    """
    args = sys.argv[1:]
    enable_log = "--log" in args
    args = [a for a in args if a != "--log"]

    if len(args) < 2:
        print("Usage: machine.py <code.bin> <input.txt> [--log]", file=sys.stderr)
        sys.exit(1)

    if enable_log:
        logging.basicConfig(level=logging.DEBUG, format="%(levelname)-7s %(module)s:%(funcName)-13s %(message)s")

    with open(args[0], "rb") as f:
        code = from_bytes(f.read())

    with open(args[1], encoding="utf-8") as f:
        text = f.read()
    input_tokens = [ord(c) for c in text]

    output, ticks, stats = simulation(code, input_tokens)
    print("".join(chr(v) for v in output))
    print(f"ticks: {ticks}")
    print(f"cache: hits={stats.hits} misses={stats.misses} writebacks={stats.writebacks}")


if __name__ == "__main__":
    main()
