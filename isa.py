"""Представление машинного кода: опкоды, кодирование/декодирование бинаря.

Формат инструкции (32 бита):
  31..24 - opcode
  23..0  - operand (24 бита)

Спецслучай LIT: opcode-слово + следующее 32-битное слово со значением.
"""

import struct
from enum import IntEnum
from typing import TypedDict


class Opcode(IntEnum):
    """Опкоды стековой машины.

    >>> Opcode.HALT
    <Opcode.HALT: 1>
    >>> hex(Opcode.ADD)
    '0x20'
    """

    NOP = 0x00
    HALT = 0x01

    # Стек данных
    LIT = 0x10
    DUP = 0x11
    DROP = 0x12
    SWAP = 0x13
    OVER = 0x14

    # АЛУ - арифметика
    ADD = 0x20
    SUB = 0x21
    MUL = 0x22
    DIV = 0x23
    MOD = 0x24

    # АЛУ - сравнения
    EQ = 0x25
    LT = 0x26
    GT = 0x2A

    # АЛУ - логика
    AND = 0x27
    OR = 0x28
    INVERT = 0x29

    # Память
    LOAD = 0x30
    STORE = 0x31

    # Поток управления
    JMP = 0x40
    JZ = 0x41
    CALL = 0x42
    RET = 0x43
    EXECUTE = 0x44

    # Стек возвратов
    TO_R = 0x50
    R_FROM = 0x51
    R_FETCH = 0x52


class Instruction(TypedDict, total=False):
    """Одна инструкция в списке машинного кода.

    ``opcode`` и ``operand`` обязательны; ``term`` - опционально (строка исходника для дебага).
    """

    opcode: Opcode
    operand: int
    term: str


MNEMONICS: dict[Opcode, str] = {
    Opcode.NOP: "NOP",
    Opcode.HALT: "HALT",
    Opcode.LIT: "LIT",
    Opcode.DUP: "DUP",
    Opcode.DROP: "DROP",
    Opcode.SWAP: "SWAP",
    Opcode.OVER: "OVER",
    Opcode.ADD: "ADD",
    Opcode.SUB: "SUB",
    Opcode.MUL: "MUL",
    Opcode.DIV: "DIV",
    Opcode.MOD: "MOD",
    Opcode.EQ: "EQ",
    Opcode.LT: "LT",
    Opcode.GT: "GT",
    Opcode.AND: "AND",
    Opcode.OR: "OR",
    Opcode.INVERT: "INVERT",
    Opcode.LOAD: "LOAD",
    Opcode.STORE: "STORE",
    Opcode.JMP: "JMP",
    Opcode.JZ: "JZ",
    Opcode.CALL: "CALL",
    Opcode.RET: "RET",
    Opcode.EXECUTE: "EXECUTE",
    Opcode.TO_R: ">R",
    Opcode.R_FROM: "R>",
    Opcode.R_FETCH: "R@",
}

MNEMONIC_TO_OPCODE: dict[str, Opcode] = {mnem: op for op, mnem in MNEMONICS.items()}

# Опкоды с операндом (24-битное поле используется для адреса)
_HAS_OPERAND: frozenset[Opcode] = frozenset({Opcode.JMP, Opcode.JZ, Opcode.CALL})


def encode_instruction(opcode: Opcode, operand: int = 0) -> int:
    """Закодировать одну инструкцию в 32-битное слово.

    >>> hex(encode_instruction(Opcode.HALT))
    '0x1000000'
    >>> hex(encode_instruction(Opcode.JMP, 5))
    '0x40000005'
    >>> hex(encode_instruction(Opcode.DUP))
    '0x11000000'
    """
    return ((opcode & 0xFF) << 24) | (operand & 0x00FFFFFF)


def _decode_word(word: int) -> tuple[Opcode, int]:
    """Декодировать 32-битное слово в (opcode, operand)."""
    opcode_raw = (word >> 24) & 0xFF
    operand = word & 0x00FFFFFF
    return Opcode(opcode_raw), operand


def to_bytes(code: list[Instruction]) -> bytes:
    """Сериализовать список инструкций в бинарный файл.

    LIT занимает два слова: opcode-слово + слово с 32-битным значением.

    >>> import struct
    >>> instrs: list[Instruction] = [{"opcode": Opcode.LIT, "operand": 42}, {"opcode": Opcode.HALT, "operand": 0}]
    >>> b = to_bytes(instrs)
    >>> len(b)
    12
    >>> struct.unpack('>III', b) == (0x10000000, 42, 0x01000000)
    True
    """
    words: list[int] = []
    for instr in code:
        opcode: Opcode = instr["opcode"]
        operand: int = instr.get("operand", 0)
        if opcode == Opcode.LIT:
            # opcode-слово не несёт операнда; значение - в следующем слове
            words.append(encode_instruction(opcode, 0))
            words.append(operand & 0xFFFFFFFF)
        else:
            words.append(encode_instruction(opcode, operand))
    return struct.pack(f">{len(words)}I", *words)


def from_bytes(binary: bytes) -> list[Instruction]:
    """Десериализовать бинарный файл в список инструкций.

    >>> instrs: list[Instruction] = [{"opcode": Opcode.LIT, "operand": 42}, {"opcode": Opcode.DUP, "operand": 0}]
    >>> recovered = from_bytes(to_bytes(instrs))
    >>> recovered[0]["opcode"] == Opcode.LIT and recovered[0]["operand"] == 42
    True
    >>> recovered[1]["opcode"] == Opcode.DUP
    True
    >>> len(recovered)
    2
    """
    n = len(binary) // 4
    words = list(struct.unpack(f">{n}I", binary))
    result: list[Instruction] = []
    i = 0
    while i < len(words):
        opcode, operand = _decode_word(words[i])
        if opcode == Opcode.LIT:
            i += 1
            value = words[i] if i < len(words) else 0
            # знаковое 32-битное
            if value >= 0x80000000:
                value -= 0x100000000
            result.append({"opcode": opcode, "operand": value})
        else:
            result.append({"opcode": opcode, "operand": operand})
        i += 1
    return result


def to_hex(code: list[Instruction]) -> str:
    """Текстовый дамп кода в формате «<addr> - <HEXCODE> - <mnemonic>».

    Адресация байтовая: каждое 32-битное слово занимает 4 байта, поэтому
    адреса идут 0, 4, 8, ... (LIT охватывает два слова = 8 байт).

    >>> lines = to_hex([{"opcode": Opcode.JMP, "operand": 20}, {"opcode": Opcode.LIT, "operand": 42}, {"opcode": Opcode.HALT, "operand": 0}])
    >>> lines.split("\\n")[0]
    '0  - 40000014 - JMP 20'
    >>> lines.split("\\n")[1]
    '4  - 10000000 - LIT'
    >>> lines.split("\\n")[2]
    '8  - 0000002A - <value 42>'
    >>> lines.split("\\n")[3]
    '12  - 01000000 - HALT'
    """
    binary = to_bytes(code)
    n = len(binary) // 4
    words = list(struct.unpack(f">{n}I", binary))

    lines: list[str] = []
    addr = 0
    i = 0
    while i < len(words):
        word = words[i]
        opcode_raw = (word >> 24) & 0xFF
        operand = word & 0x00FFFFFF
        try:
            opcode = Opcode(opcode_raw)
            mnemonic = MNEMONICS[opcode]
            if opcode in _HAS_OPERAND:
                mnemonic = f"{mnemonic} {operand}"
        except ValueError:
            mnemonic = f"<unknown 0x{opcode_raw:02X}>"
        lines.append(f"{addr}  - {word:08X} - {mnemonic}")
        addr += 4
        if opcode_raw == Opcode.LIT:
            i += 1
            if i < len(words):
                val_word = words[i]
                lines.append(
                    f"{addr}  - {val_word:08X} - <value {val_word if val_word < 0x80000000 else val_word - 0x100000000}>"
                )
                addr += 4
        i += 1
    return "\n".join(lines)
