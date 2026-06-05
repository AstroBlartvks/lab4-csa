"""Тесты DataPath: семантика return-стека на сценарии CALL → CALL → RET → RET.

Прогоняем примитивы push/pop в том же порядке, в каком их дёргают
микроинструкции CALL ([29]) и RET ([30]) из microcode.py:

    CALL: LatchTors(FromPc), RStackPush(), LatchPc(Jmp)
    RET:  LatchPc(FromTors), RStackPop()
"""

from cache import Cache, MainMemory
from machine import DataPath
from microcode import PcSel, TorsSel


def _fresh_dp() -> DataPath:
    return DataPath(Cache(MainMemory(size=256)))


def test_call_call_ret_ret_return_stack() -> None:
    """Двойной вложенный вызов и возврат восстанавливает TORS родителя.

    Адреса возврата: PC0 (после первого CALL), PC1 (после второго CALL).
    """
    pc0, pc1 = 100, 200
    target1, target2 = 1000, 2000

    dp = _fresh_dp()
    assert dp.rsp == 0
    assert dp.tors == 0

    # ── CALL #1: вызываем функцию f1, адрес возврата PC0 ──────────────────
    dp.pc = pc0
    dp.latch_tors(TorsSel.FromPc)   # TORS ← PC0
    dp.rstack_push()                # RS[0] ← PC0; RSP=1
    dp.pc = target1                 # LatchPc(Jmp)

    assert dp.tors == pc0
    assert dp._rs[0] == pc0
    assert dp.rsp == 1
    assert dp.pc == target1

    # ── CALL #2: внутри f1 вызываем f2, адрес возврата PC1 ────────────────
    dp.pc = pc1
    dp.latch_tors(TorsSel.FromPc)   # TORS ← PC1
    dp.rstack_push()                # RS[1] ← PC1; RSP=2
    dp.pc = target2

    assert dp.tors == pc1
    assert dp._rs[0] == pc0
    assert dp._rs[1] == pc1
    assert dp.rsp == 2
    assert dp.pc == target2

    # ── RET #1: возврат из f2 в f1 ────────────────────────────────────────
    dp.latch_pc(PcSel.FromTors)     # PC ← TORS = PC1
    dp.rstack_pop()                 # RSP=1; TORS ← RS[0] = PC0

    assert dp.pc == pc1             # вернулись в f1
    assert dp.rsp == 1
    assert dp.tors == pc0           # TORS восстановлен на кадр-родитель

    # ── RET #2: возврат из f1 к вызывающему ───────────────────────────────
    dp.latch_pc(PcSel.FromTors)     # PC ← TORS = PC0
    dp.rstack_pop()                 # RSP=0; TORS ← RS[255] = 0 (мусор)

    assert dp.pc == pc0             # вернулись к исходному коду
    assert dp.rsp == 0
    assert dp.tors == 0             # пустой return-стек


def test_push_pop_symmetry_with_data_stack() -> None:
    """rstack_pop восстанавливает TORS, dstack_pop — NOS; оба возвращают RSP/DSP.

    Контраст семантики: return-стек хранит сам TORS (push после LatchTors),
    data-стек хранит NOS. Проверяем, что после push/pop состояние совпадает.
    """
    dp = _fresh_dp()

    # Return-стек: 0xAA — текущий TORS, кладём ещё 0xBB и 0xCC
    dp.tors = 0xAA
    dp.rstack_push()                # RS[0] ← 0xAA; RSP=1
    dp.tors = 0xBB
    dp.rstack_push()                # RS[1] ← 0xBB; RSP=2
    dp.tors = 0xCC
    dp.rstack_push()                # RS[2] ← 0xCC; RSP=3

    dp.rstack_pop()                 # RSP=2; TORS ← RS[1] = 0xBB
    assert dp.rsp == 2
    assert dp.tors == 0xBB
    dp.rstack_pop()                 # RSP=1; TORS ← RS[0] = 0xAA
    assert dp.rsp == 1
    assert dp.tors == 0xAA
