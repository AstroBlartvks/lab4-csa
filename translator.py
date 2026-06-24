"""Транслятор Forth -> бинарный машинный код стековой машины.

Этапы: tokenize -> _compile_tokens -> layout -> emit.
CLI: translator.py <source.fth> <target.bin> [--debug]
"""

from __future__ import annotations

import sys

from isa import Instruction, Opcode, to_bytes, to_hex

_MMIO_OUT = 0xFFFFFFF2
_MMIO_IN = 0xFFFFFFF0


def _is_str_prefix(source: str, i: int) -> bool:
    return source[i : i + 3] in ('." ', 'S" ')


def _skip_block_comment(source: str, i: int) -> int:
    end = source.find(")", i)
    return end + 1 if end != -1 else len(source)


def _skip_line_comment(source: str, i: int) -> int:
    end = source.find("\n", i)
    return end + 1 if end != -1 else len(source)


def _read_string_token(source: str, i: int) -> tuple[str, int]:
    rest_start = i + 3
    end = source.find('"', rest_start)
    end = end + 1 if end != -1 else len(source)
    return source[i:end], end


def tokenize(source: str) -> list[str]:
    """Разбить исходник Forth на список токенов.

    >>> tokenize("2 3 +")
    ['2', '3', '+']
    >>> tokenize("\\\\ comment\\n4 5")
    ['4', '5']
    >>> tokenize('." hello"')
    ['." hello"']
    >>> tokenize('S" hi" drop')
    ['S" hi"', 'drop']
    >>> tokenize("( this is a comment ) 1")
    ['1']
    """
    tokens: list[str] = []
    i = 0
    n = len(source)
    while i < n:
        ch = source[i]
        prev_ws = i == 0 or source[i - 1] in " \t\n\r"

        if ch in " \t\n\r":
            i += 1
        elif ch == "(" and prev_ws:
            i = _skip_block_comment(source, i + 1)
        elif ch == "\\" and prev_ws:
            i = _skip_line_comment(source, i + 1)
        elif _is_str_prefix(source, i):
            tok, i = _read_string_token(source, i)
            tokens.append(tok)
        else:
            j = i
            while j < n and source[j] not in " \t\n\r":
                j += 1
            tokens.append(source[i:j])
            i = j
    return tokens


def _lit(code: list[Instruction], val: int) -> None:
    code.append({"opcode": Opcode.LIT, "operand": val})


def _op(code: list[Instruction], op: Opcode, operand: int = 0) -> None:
    code.append({"opcode": op, "operand": operand})


_BYTES_PER_WORD = 4


def _wlen(code: list[Instruction]) -> int:
    """Размер списка инструкций в байтах (каждая инструкция = 4 байта, LIT = 8 байт)."""
    return sum(8 if i["opcode"] == Opcode.LIT else 4 for i in code)


def _build_print_cstr(offset: int) -> tuple[list[Instruction], int]:
    """Скомпилировать print_cstr ( addr -- ).

    offset - абсолютный байтовый адрес первой инструкции.
    Возвращает (код, адрес_функции).

    Алгоритм: dup @ dup 0= if drop drop ret then emit addr+1 jmp loop.
    """
    code: list[Instruction] = []
    loop = offset + _wlen(code)
    _op(code, Opcode.DUP)
    _op(code, Opcode.LOAD)
    _op(code, Opcode.DUP)
    jz_idx = len(code)
    _op(code, Opcode.JZ, 0)
    _lit(code, _MMIO_OUT)
    _op(code, Opcode.STORE)
    _lit(code, 4)
    _op(code, Opcode.ADD)
    _op(code, Opcode.JMP, loop)
    exit_pc = offset + _wlen(code)
    code[jz_idx]["operand"] = exit_pc
    _op(code, Opcode.DROP)
    _op(code, Opcode.DROP)
    _op(code, Opcode.RET)
    return code, offset


def _build_print_num(offset: int) -> tuple[list[Instruction], int]:
    """Скомпилировать print_num ( n -- ).

    offset - абсолютный байтовый адрес первой инструкции.
    Выводит десятичное представление знакового числа.

    """
    code: list[Instruction] = []

    def w() -> int:
        return offset + _wlen(code)

    _op(code, Opcode.DUP)
    _lit(code, 0)
    _op(code, Opcode.EQ)
    jz_zero = len(code)
    _op(code, Opcode.JZ, 0)
    _op(code, Opcode.DROP)
    _lit(code, 48)
    _lit(code, _MMIO_OUT)
    _op(code, Opcode.STORE)
    _op(code, Opcode.RET)
    code[jz_zero]["operand"] = w()

    _op(code, Opcode.DUP)
    _lit(code, 0)
    _op(code, Opcode.LT)
    _op(code, Opcode.DUP)
    jz_neg = len(code)
    _op(code, Opcode.JZ, 0)
    _lit(code, 45)
    _lit(code, _MMIO_OUT)
    _op(code, Opcode.STORE)
    _op(code, Opcode.SWAP)
    _op(code, Opcode.INVERT)
    _lit(code, 1)
    _op(code, Opcode.ADD)
    _op(code, Opcode.SWAP)
    code[jz_neg]["operand"] = w()
    _op(code, Opcode.DROP)

    _lit(code, 0)
    _op(code, Opcode.SWAP)  # (n, counter) -> (counter, n): TOS=n, NOS=counter
    push_loop = w()
    # стек TOS=n, NOS=counter. Если n=0 -> выйти.
    _op(code, Opcode.DUP)
    jz_push = len(code)
    _op(code, Opcode.JZ, 0)  # JZ снимает дубль; если n=0 -> exit
    _op(code, Opcode.DUP)
    _lit(code, 10)
    _op(code, Opcode.MOD)
    _op(code, Opcode.TO_R)  # digit -> RS
    _lit(code, 10)
    _op(code, Opcode.DIV)  # n/10
    _op(code, Opcode.SWAP)
    _lit(code, 1)
    _op(code, Opcode.ADD)  # counter+1
    _op(code, Opcode.SWAP)
    _op(code, Opcode.JMP, push_loop)
    code[jz_push]["operand"] = w()
    _op(code, Opcode.DROP)  # drop n=0

    pop_loop = w()
    # стек: (counter). Если counter=0 -> завершить.
    _op(code, Opcode.DUP)
    jz_pop = len(code)
    _op(code, Opcode.JZ, 0)  # JZ снимает дубль; если 0 -> done
    _lit(code, 1)
    _op(code, Opcode.SUB)
    _op(code, Opcode.R_FROM)
    _lit(code, 48)
    _op(code, Opcode.ADD)
    _lit(code, _MMIO_OUT)
    _op(code, Opcode.STORE)
    _op(code, Opcode.JMP, pop_loop)
    code[jz_pop]["operand"] = w()
    _op(code, Opcode.DROP)
    _op(code, Opcode.RET)

    return code, offset


_BUILTINS: dict[str, Opcode] = {
    "+": Opcode.ADD,
    "-": Opcode.SUB,
    "*": Opcode.MUL,
    "/": Opcode.DIV,
    "mod": Opcode.MOD,
    "=": Opcode.EQ,
    "<": Opcode.LT,
    ">": Opcode.GT,
    "and": Opcode.AND,
    "or": Opcode.OR,
    "invert": Opcode.INVERT,
    "@": Opcode.LOAD,
    "!": Opcode.STORE,
    "dup": Opcode.DUP,
    "drop": Opcode.DROP,
    "swap": Opcode.SWAP,
    "over": Opcode.OVER,
    ">r": Opcode.TO_R,
    "r>": Opcode.R_FROM,
    "r@": Opcode.R_FETCH,
    "execute": Opcode.EXECUTE,
    "nop": Opcode.NOP,
}


class _TranslateError(Exception):
    """Ошибка трансляции Forth-программы."""


def _handle_string_token(
    tok: str,
    cur: list[Instruction],
    data_section: list[int],
    data_base: int,
    addr_print_cstr: int,
) -> None:
    is_dot = tok.startswith('." ')
    text = tok[3:-1]
    str_offset = len(data_section)
    for ch in text:
        data_section.append(ord(ch))
    data_section.append(0)
    _lit(cur, data_base + str_offset * _BYTES_PER_WORD)
    if is_dot:
        _op(cur, Opcode.CALL, addr_print_cstr)


def _handle_special(  # noqa: C901
    tok: str,
    tokens: list[str],
    idx: int,
    cur: list[Instruction],
    word_code: list[Instruction],
    word_dict: dict[str, int],
    const_dict: dict[str, int],
    ctrl: list[int],
    data_section: list[int],
    data_base: int,
    addr_print_cstr: int,
    addr_print_num: int,
    word_code_base: int,
    in_def: bool,
) -> tuple[int, bool, list[Instruction]]:
    """Обработать управляющие токены. Возвращает (новый_idx, новый_in_def, новый_cur)."""
    if tok == ":":
        name = tokens[idx]
        idx += 1
        word_dict[name] = word_code_base + _wlen(word_code)
        return idx, True, word_code

    if tok == ";":
        _op(cur, Opcode.RET)
        return idx, False, []  # cur будет заменён в caller на main_code

    if tok == "if":
        ctrl.append(len(cur))  # индекс if для обратной заплатки
        _op(cur, Opcode.JZ, 0)
        return idx, in_def, cur

    if tok == "else":
        jz_ii = ctrl.pop()
        ctrl.append(len(cur))  # индекс jmp для обратной заплатки
        _op(cur, Opcode.JMP, 0)
        cur[jz_ii]["operand"] = _wlen(cur)
        return idx, in_def, cur

    if tok == "then":
        ii = ctrl.pop()
        cur[ii]["operand"] = _wlen(cur)
        return idx, in_def, cur

    if tok == "begin":
        ctrl.append(_wlen(cur))  # таргет для джампа
        return idx, in_def, cur

    if tok == "until":
        _op(cur, Opcode.JZ, ctrl.pop())
        return idx, in_def, cur

    if tok == "again":
        _op(cur, Opcode.JMP, ctrl.pop())
        return idx, in_def, cur

    if tok == "while":
        ctrl.append(len(cur))  # заплатка для джз
        _op(cur, Opcode.JZ, 0)
        return idx, in_def, cur

    if tok == "repeat":
        jz_ii = ctrl.pop()  # индекс джз для обратной заплатки
        begin_w = ctrl.pop()  # начало таргета
        _op(cur, Opcode.JMP, begin_w)
        cur[jz_ii]["operand"] = _wlen(cur)  # джз таргет
        return idx, in_def, cur

    if tok == "variable":
        name = tokens[idx]
        idx += 1
        var_offset = len(data_section)
        data_section.append(0)
        proc_addr = word_code_base + _wlen(word_code)
        word_dict[name] = proc_addr
        _lit(word_code, data_base + var_offset * _BYTES_PER_WORD)
        _op(word_code, Opcode.RET)
        return idx, in_def, cur

    if tok == "allot":
        if not cur or cur[-1].get("opcode") != Opcode.LIT:
            raise _TranslateError(tok)
        n = cur[-1].get("operand", 0)
        cur.pop()
        for _ in range(n):
            data_section.append(0)
        return idx, in_def, cur

    if tok == "constant":
        name = tokens[idx]
        idx += 1
        if not cur or cur[-1].get("opcode") != Opcode.LIT:
            raise _TranslateError(name)
        val = cur[-1].get("operand", 0)
        cur.pop()
        const_dict[name] = val
        return idx, in_def, cur

    if tok == "'":
        name = tokens[idx]
        idx += 1
        if name not in word_dict:
            raise _TranslateError(name)
        _lit(cur, word_dict[name])
        return idx, in_def, cur

    if tok.upper() == "[CHAR]":
        ch = tokens[idx]
        idx += 1
        _lit(cur, ord(ch[0]))
        return idx, in_def, cur

    raise _TranslateError(tok)


_SHORTHAND: dict[str, tuple[int, Opcode]] = {
    "1+": (1, Opcode.ADD),
    "1-": (1, Opcode.SUB),
    "2*": (2, Opcode.MUL),
}


def _emit_io_word(tok: str, cur: list[Instruction], addr_print_num: int) -> bool:
    """I/O и прочие мета-слова. Возвращает True если обработано."""
    if tok == "emit":
        _lit(cur, _MMIO_OUT)
        _op(cur, Opcode.STORE)
    elif tok == "key":
        _lit(cur, _MMIO_IN)
        _op(cur, Opcode.LOAD)
    elif tok == "cr":
        _lit(cur, 10)
        _lit(cur, _MMIO_OUT)
        _op(cur, Opcode.STORE)
    elif tok == ".":
        _op(cur, Opcode.CALL, addr_print_num)
    elif tok == "halt":
        _op(cur, Opcode.HALT)
    elif tok == "exit":
        _op(cur, Opcode.RET)
    else:
        return False
    return True


_COMPOUND: dict[str, list[tuple[bool, Opcode | int]]] = {
    "0=": [(True, 0), (False, Opcode.EQ)],
    "<>": [(False, Opcode.EQ), (False, Opcode.INVERT)],
    "negate": [(False, Opcode.INVERT), (True, 1), (False, Opcode.ADD)],
    "nip": [(False, Opcode.SWAP), (False, Opcode.DROP)],
    "rot": [(False, Opcode.TO_R), (False, Opcode.SWAP), (False, Opcode.R_FROM), (False, Opcode.SWAP)],
    ">=": [(False, Opcode.LT), (False, Opcode.INVERT)],
    "<=": [(False, Opcode.GT), (False, Opcode.INVERT)],
    "2dup": [(False, Opcode.OVER), (False, Opcode.OVER)],
    "2drop": [(False, Opcode.DROP), (False, Opcode.DROP)],
    "cells": [(True, 4), (False, Opcode.MUL)],
    "chars": [(True, 4), (False, Opcode.MUL)],
    "cell+": [(True, 4), (False, Opcode.ADD)],
    "char+": [(True, 4), (False, Opcode.ADD)],
}


def _emit_builtin_word(tok: str, cur: list[Instruction], addr_print_num: int) -> bool:
    """Встроенные слова. Возвращает True если обработано."""
    if tok.lower() in _BUILTINS:
        _op(cur, _BUILTINS[tok.lower()])
        return True
    if tok in _SHORTHAND:
        val, opc = _SHORTHAND[tok]
        _lit(cur, val)
        _op(cur, opc)
        return True
    if tok in _COMPOUND:
        for is_lit, val in _COMPOUND[tok]:
            if is_lit:
                _lit(cur, val)
            else:
                _op(cur, val)  # type: ignore[arg-type]
        return True
    return _emit_io_word(tok, cur, addr_print_num)


_CONTROL_TOKS = frozenset(
    [
        ":",
        ";",
        "if",
        "else",
        "then",
        "begin",
        "until",
        "again",
        "while",
        "repeat",
        "variable",
        "allot",
        "constant",
        "'",
        "[char]",
        "[CHAR]",
    ]
)


def _compile_tokens(  # noqa: C901
    tokens: list[str],
    addr_print_cstr: int,
    addr_print_num: int,
    word_code_base: int,
    data_base: int,
) -> tuple[list[Instruction], list[Instruction], list[int]]:
    """Однопроходный компилятор Forth.

    Возвращает (word_code, main_code, data_section).
    Адреса JMP/JZ/CALL внутри main_code хранятся как индексы в main_code;
    layout() скорректирует их, добавив main_base.
    """
    word_code: list[Instruction] = []
    main_code: list[Instruction] = []
    data_section: list[int] = []
    word_dict: dict[str, int] = {}
    const_dict: dict[str, int] = {}
    ctrl: list[int] = []
    in_def = False
    cur: list[Instruction] = main_code

    i = 0
    while i < len(tokens):
        tok = tokens[i]
        i += 1

        if tok.startswith('." ') or tok.startswith('S" '):
            _handle_string_token(tok, cur, data_section, data_base, addr_print_cstr)
            continue

        if tok.lower() in _CONTROL_TOKS or tok in ("'", "[CHAR]", "[char]"):
            new_idx, new_in_def, new_cur = _handle_special(
                tok,
                tokens,
                i,
                cur,
                word_code,
                word_dict,
                const_dict,
                ctrl,
                data_section,
                data_base,
                addr_print_cstr,
                addr_print_num,
                word_code_base,
                in_def,
            )
            i = new_idx
            if tok == ";" and not new_in_def:
                in_def = False
                cur = main_code
            elif tok == ":" and new_in_def:
                in_def = True
                cur = word_code
            else:
                in_def = new_in_def
                if new_cur is not word_code and new_cur is not main_code:
                    cur = main_code
                else:
                    cur = new_cur
            continue

        if _emit_builtin_word(tok, cur, addr_print_num):
            continue

        if tok in word_dict:
            _op(cur, Opcode.CALL, word_dict[tok])
            continue

        if tok in const_dict:
            _lit(cur, const_dict[tok])
            continue

        try:
            _lit(cur, int(tok, 0))
            continue
        except ValueError:
            pass

        raise _TranslateError(tok)

    return word_code, main_code, data_section


def _patch_cf(code: list[Instruction], base: int) -> None:
    """Исправить JMP/JZ с относительных индексов на абсолютные адреса."""
    cf = {Opcode.JMP, Opcode.JZ}
    for instr in code:
        if instr.get("opcode") in cf:
            instr["operand"] = base + instr.get("operand", 0)


def _layout(
    runtime: list[Instruction],
    word_code: list[Instruction],
    main_code: list[Instruction],
    data_section: list[int],
) -> list[Instruction]:
    word_base = _BYTES_PER_WORD + _wlen(runtime)
    main_base = word_base + _wlen(word_code)
    _patch_cf(word_code, word_base)
    _patch_cf(main_code, main_base)
    jmp: list[Instruction] = [{"opcode": Opcode.JMP, "operand": main_base}]
    if not main_code or main_code[-1].get("opcode") != Opcode.HALT:
        main_code.append({"opcode": Opcode.HALT, "operand": 0})
    data: list[Instruction] = [{"opcode": Opcode.NOP, "operand": w} for w in data_section]
    return jmp + runtime + word_code + main_code + data


def translate(source: str) -> list[Instruction]:
    """Транслировать Forth-исходник в список инструкций.

    >>> instrs = translate("2 3 +")
    >>> from isa import Opcode
    >>> Opcode.ADD in [i["opcode"] for i in instrs]
    True

    >>> instrs2 = translate(": sq dup * ; 5 sq")
    >>> from isa import Opcode
    >>> Opcode.MUL in [i["opcode"] for i in instrs2]
    True
    """
    tokens = tokenize(source)

    rt_cstr, addr_cstr = _build_print_cstr(_BYTES_PER_WORD)
    rt_num, addr_num = _build_print_num(_BYTES_PER_WORD + _wlen(rt_cstr))
    runtime = rt_cstr + rt_num
    rt_wlen = _wlen(runtime)
    word_code_base = _BYTES_PER_WORD + rt_wlen  # после ведущего JMP

    wc1, mc1, _ = _compile_tokens(tokens, addr_cstr, addr_num, word_code_base, 0)
    mc1_halt_extra = 0 if mc1 and mc1[-1].get("opcode") == Opcode.HALT else _BYTES_PER_WORD
    data_base = _BYTES_PER_WORD + rt_wlen + _wlen(wc1) + _wlen(mc1) + mc1_halt_extra

    wc, mc, ds = _compile_tokens(tokens, addr_cstr, addr_num, word_code_base, data_base)
    return _layout(runtime, wc, mc, ds)


def main() -> None:
    """Запуск транслятора из командной строки.

    Использование: translator.py <source.fth> <target.bin> [--debug]
    """
    args = sys.argv[1:]
    debug = "--debug" in args
    args = [a for a in args if a != "--debug"]

    if len(args) < 2:
        print("Usage: translator.py <source.fth> <target.bin> [--debug]", file=sys.stderr)
        sys.exit(1)

    src_path, bin_path = args[0], args[1]

    with open(src_path, encoding="utf-8") as f:
        source = f.read()

    code = translate(source)
    binary = to_bytes(code)

    with open(bin_path, "wb") as f:
        f.write(binary)

    if debug:
        hex_path = bin_path + ".hex"
        with open(hex_path, "w", encoding="utf-8") as f:
            f.write(to_hex(code))
        print(f"Wrote {hex_path}")

    loc = len([ln for ln in source.splitlines() if ln.strip()])
    print(f"source LoC: {loc} code instr: {len(code)}")


if __name__ == "__main__":
    main()
