"""Сигналы, селекторы и микропрограмма стековой машины.

Содержит только декларации типов и данные. Никакой логики исполнения -
она живёт в machine.py.
"""

from dataclasses import dataclass
from enum import Enum

from isa import Opcode


class PcSel(Enum):
    """Источник для защёлки PC."""

    Next = "next"
    Jmp = "jmp"
    Jz = "jz"
    FromTors = "from_tors"
    FromTos = "from_tos"


class MarSel(Enum):
    """Источник для защёлки MAR."""

    FromPc = "from_pc"
    FromTos = "from_tos"


class MdrSel(Enum):
    """Источник для защёлки MDR."""

    FromMem = "from_mem"
    FromNos = "from_nos"
    FromTos = "from_tos"


class TosSel(Enum):
    """Источник для защёлки TOS."""

    FromAlu = "from_alu"
    FromMdr = "from_mdr"
    FromNos = "from_nos"
    FromTors = "from_tors"


class NosSel(Enum):
    """Источник для защёлки NOS (только прямой обмен, push/pop управляют NOS сами)."""

    FromTos = "from_tos"
    FromMdr = "from_mdr"


class TorsSel(Enum):
    """Источник для защёлки TORS."""

    FromPc = "from_pc"
    FromTos = "from_tos"


class MpcSel(Enum):
    """Источник для защёлки mPC."""

    Zero = "zero"
    Next = "next"
    Opcode = "opcode"


class AluOpSel(Enum):
    """Операция ALU."""

    Add = "add"
    Sub = "sub"
    Mul = "mul"
    Div = "div"
    Mod = "mod"
    Eq = "eq"
    Lt = "lt"
    Gt = "gt"
    And = "and"
    Or = "or"
    Invert = "invert"


class MemOp(Enum):
    """Тип обращения к памяти."""

    Read = "read"
    Write = "write"


@dataclass(frozen=True)
class LatchPc:
    """PC ← (sel)."""

    sel: PcSel


@dataclass(frozen=True)
class LatchIr:
    """IR ← MDR."""


@dataclass(frozen=True)
class LatchMar:
    """MAR ← (sel)."""

    sel: MarSel


@dataclass(frozen=True)
class LatchMdr:
    """MDR ← (sel)."""

    sel: MdrSel


@dataclass(frozen=True)
class LatchTos:
    """TOS ← (sel); флаги Z/N обновляются от нового TOS."""

    sel: TosSel


@dataclass(frozen=True)
class LatchNos:
    """NOS ← (sel). Использовать только без push/pop."""

    sel: NosSel


@dataclass(frozen=True)
class LatchTors:
    """TORS ← (sel)."""

    sel: TorsSel


@dataclass(frozen=True)
class DStackPush:
    """DS_SRAM[DSP] ← NOS; DSP++; NOS ← TOS."""


@dataclass(frozen=True)
class DStackPop:
    """DSP--; NOS ← DS_SRAM[DSP]."""


@dataclass(frozen=True)
class RStackPush:
    """RS_SRAM[RSP] ← TORS; RSP++."""


@dataclass(frozen=True)
class RStackPop:
    """RSP--; TORS ← RS_SRAM[RSP-1] (восстановление TORS кадра-родителя).

    Снимаемое значение уже использовано вызывающим (RET берёт PC из TORS,
    R> копирует TORS в TOS) до pop. См. DataPath.rstack_pop."""


@dataclass(frozen=True)
class AluOp:
    """Запустить ALU над (NOS op TOS). Результат на шине ALU.OUT."""

    op: AluOpSel


@dataclass(frozen=True)
class MemRequest:
    """Запросить кеш: read или write по адресу MAR."""

    op: MemOp


@dataclass(frozen=True)
class LatchMpc:
    """mPC ← (sel)."""

    sel: MpcSel


@dataclass(frozen=True)
class Halt:
    """Поднять флаг остановки модели."""


# Union-тип всех сигналов для аннотаций
Signal = (
    LatchPc
    | LatchIr
    | LatchMar
    | LatchMdr
    | LatchTos
    | LatchNos
    | LatchTors
    | DStackPush
    | DStackPop
    | RStackPush
    | RStackPop
    | AluOp
    | MemRequest
    | LatchMpc
    | Halt
)

MPROGRAM: list[list[Signal]] = [
    # [0] FETCH_1
    [LatchMar(MarSel.FromPc), MemRequest(MemOp.Read), LatchPc(PcSel.Next), LatchMpc(MpcSel.Next)],
    # [1] FETCH_2
    [LatchMdr(MdrSel.FromMem), LatchIr(), LatchMpc(MpcSel.Opcode)],
    # [2] NOP
    [LatchMpc(MpcSel.Zero)],
    # [3] HALT
    [Halt()],
    # [4] LIT_1
    [LatchMar(MarSel.FromPc), MemRequest(MemOp.Read), LatchPc(PcSel.Next), LatchMpc(MpcSel.Next)],
    # [5] LIT_2
    [DStackPush(), LatchMdr(MdrSel.FromMem), LatchTos(TosSel.FromMdr), LatchMpc(MpcSel.Zero)],
    # [6] DUP
    [DStackPush(), LatchMpc(MpcSel.Zero)],
    # [7] DROP
    [LatchTos(TosSel.FromNos), DStackPop(), LatchMpc(MpcSel.Zero)],
    # [8] SWAP_1
    [LatchMdr(MdrSel.FromTos), LatchMpc(MpcSel.Next)],
    # [9] SWAP_2
    [LatchTos(TosSel.FromNos), LatchNos(NosSel.FromMdr), LatchMpc(MpcSel.Zero)],
    # [10] OVER_1
    [LatchMdr(MdrSel.FromNos), LatchMpc(MpcSel.Next)],
    # [11] OVER_2
    [DStackPush(), LatchTos(TosSel.FromMdr), LatchMpc(MpcSel.Zero)],
    # [12] ADD
    [AluOp(AluOpSel.Add), LatchTos(TosSel.FromAlu), DStackPop(), LatchMpc(MpcSel.Zero)],
    # [13] SUB
    [AluOp(AluOpSel.Sub), LatchTos(TosSel.FromAlu), DStackPop(), LatchMpc(MpcSel.Zero)],
    # [14] MUL
    [AluOp(AluOpSel.Mul), LatchTos(TosSel.FromAlu), DStackPop(), LatchMpc(MpcSel.Zero)],
    # [15] DIV
    [AluOp(AluOpSel.Div), LatchTos(TosSel.FromAlu), DStackPop(), LatchMpc(MpcSel.Zero)],
    # [16] MOD
    [AluOp(AluOpSel.Mod), LatchTos(TosSel.FromAlu), DStackPop(), LatchMpc(MpcSel.Zero)],
    # [17] EQ
    [AluOp(AluOpSel.Eq), LatchTos(TosSel.FromAlu), DStackPop(), LatchMpc(MpcSel.Zero)],
    # [18] LT
    [AluOp(AluOpSel.Lt), LatchTos(TosSel.FromAlu), DStackPop(), LatchMpc(MpcSel.Zero)],
    # [19] GT
    [AluOp(AluOpSel.Gt), LatchTos(TosSel.FromAlu), DStackPop(), LatchMpc(MpcSel.Zero)],
    # [20] AND
    [AluOp(AluOpSel.And), LatchTos(TosSel.FromAlu), DStackPop(), LatchMpc(MpcSel.Zero)],
    # [21] OR
    [AluOp(AluOpSel.Or), LatchTos(TosSel.FromAlu), DStackPop(), LatchMpc(MpcSel.Zero)],
    # [22] INVERT
    [AluOp(AluOpSel.Invert), LatchTos(TosSel.FromAlu), LatchMpc(MpcSel.Zero)],
    # [23] LOAD_1
    [LatchMar(MarSel.FromTos), MemRequest(MemOp.Read), LatchMpc(MpcSel.Next)],
    # [24] LOAD_2
    [LatchMdr(MdrSel.FromMem), LatchTos(TosSel.FromMdr), LatchMpc(MpcSel.Zero)],
    # [25] STORE_1
    [
        LatchMar(MarSel.FromTos),
        LatchMdr(MdrSel.FromNos),
        MemRequest(MemOp.Write),
        LatchTos(TosSel.FromNos),
        DStackPop(),
        LatchMpc(MpcSel.Next),
    ],
    # [26] STORE_2
    [LatchTos(TosSel.FromNos), DStackPop(), LatchMpc(MpcSel.Zero)],
    # [27] JMP
    [LatchPc(PcSel.Jmp), LatchMpc(MpcSel.Zero)],
    # [28] JZ
    [LatchPc(PcSel.Jz), LatchTos(TosSel.FromNos), DStackPop(), LatchMpc(MpcSel.Zero)],
    # [29] CALL
    [LatchTors(TorsSel.FromPc), RStackPush(), LatchPc(PcSel.Jmp), LatchMpc(MpcSel.Zero)],
    # [30] RET
    [LatchPc(PcSel.FromTors), RStackPop(), LatchMpc(MpcSel.Zero)],
    # [31] EXECUTE
    [
        LatchTors(TorsSel.FromPc),
        RStackPush(),
        LatchPc(PcSel.FromTos),
        LatchTos(TosSel.FromNos),
        DStackPop(),
        LatchMpc(MpcSel.Zero),
    ],
    # [32] TO_R
    [LatchTors(TorsSel.FromTos), RStackPush(), LatchTos(TosSel.FromNos), DStackPop(), LatchMpc(MpcSel.Zero)],
    # [33] R_FROM
    [DStackPush(), LatchTos(TosSel.FromTors), RStackPop(), LatchMpc(MpcSel.Zero)],
    # [34] R_FETCH
    [DStackPush(), LatchTos(TosSel.FromTors), LatchMpc(MpcSel.Zero)],
]

MPC_OF_OPCODE: dict[Opcode, int] = {
    Opcode.NOP: 2,
    Opcode.HALT: 3,
    Opcode.LIT: 4,
    Opcode.DUP: 6,
    Opcode.DROP: 7,
    Opcode.SWAP: 8,
    Opcode.OVER: 10,
    Opcode.ADD: 12,
    Opcode.SUB: 13,
    Opcode.MUL: 14,
    Opcode.DIV: 15,
    Opcode.MOD: 16,
    Opcode.EQ: 17,
    Opcode.LT: 18,
    Opcode.GT: 19,
    Opcode.AND: 20,
    Opcode.OR: 21,
    Opcode.INVERT: 22,
    Opcode.LOAD: 23,
    Opcode.STORE: 25,
    Opcode.JMP: 27,
    Opcode.JZ: 28,
    Opcode.CALL: 29,
    Opcode.RET: 30,
    Opcode.EXECUTE: 31,
    Opcode.TO_R: 32,
    Opcode.R_FROM: 33,
    Opcode.R_FETCH: 34,
}


def _self_check() -> None:
    """Проверки консистентности микропрограммы.

    >>> from isa import Opcode
    >>> # Каждый опкод из ISA покрыт в MPC_OF_OPCODE.
    >>> all(op in MPC_OF_OPCODE for op in Opcode)
    True
    >>> # Все адреса - валидные индексы MPROGRAM.
    >>> all(0 <= addr < len(MPROGRAM) for addr in MPC_OF_OPCODE.values())
    True
    >>> # Каждая микроинструкция оканчивается LatchMpc или Halt.
    >>> def _has_terminal(uinstr):
    ...     return any(isinstance(s, (LatchMpc, Halt)) for s in uinstr)
    >>> all(_has_terminal(u) for u in MPROGRAM)
    True
    >>> # Ровно 35 микроинструкций (SWAP и OVER занимают по 2).
    >>> len(MPROGRAM)
    35
    >>> # FETCH_1 по адресу 0 начинается с LatchMar(FromPc).
    >>> MPROGRAM[0][0] == LatchMar(MarSel.FromPc)
    True
    >>> # FETCH_2 по адресу 1: первый сигнал - LatchMdr(FromMem).
    >>> MPROGRAM[1][0] == LatchMdr(MdrSel.FromMem)
    True
    >>> # HALT по адресу 3 состоит ровно из одного сигнала Halt.
    >>> MPROGRAM[3] == [Halt()]
    True
    """
