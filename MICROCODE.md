# MICROCODE.md — контракт сигналов и полная микропрограмма

Этот документ — **исчерпывающая спецификация** микрокодированного уровня. Здесь
зафиксированы:

1. **Полный набор сигналов** ControlUnit и DataPath с селекторами.
2. **Контракт mux'ов**: куда подаются какие источники.
3. **Полная микропрограмма** для всех 28 опкодов из `isa.py`.
4. **Карта `opcode → mPC`** — стартовый адрес микропрограммы для каждого опкода.

Цель — чтобы `microcode.py`, `machine.py` (DataPath, CU) и набор unit-тестов
писались по этому документу без архитектурных додумываний на ходу.

ARCHITECTURE.md остаётся главным про общую структуру, но **в части микрокода
этот файл его уточняет и переопределяет**.

---

## 0. Базовые принципы

1. **Один такт = одна микроинструкция.** Микроинструкция — это **множество
   сигналов**, поданных одновременно. Все защёлки срабатывают по фронту такта,
   читая **старые** значения регистров.

2. **Сигнал — это управляющая линия от CU к DataPath.** Не «один транзистор»,
   а «один контрольный бит», который активирует согласованный пучок защёлок
   (как `LatchAcc` у ryukzak в OCaml-референсе: одна линия — но за ней и
   `OutputEnable` памяти, и защёлка ACC).

3. **Параллельность защёлок без конфликтов.** Если на одном такте есть
   `DStackPush` и `LatchTos(FromNos)`:
   - `DStackPush` читает старые TOS и NOS, пишет SRAM ← старый NOS, NOS ← старый TOS.
   - `LatchTos` параллельно читает старый NOS и защёлкивает его в TOS.
   - Конфликта нет, потому что все источники — это **старые** значения регистров.

4. **Stall кеша — невидим для микропрограммы.** Микропрограмма пишется
   «оптимистично», как будто кеш всегда отвечает за 1 такт. Реальный stall
   обрабатывается в `ControlUnit.tick()`: если кеш `is_busy()`, mPC **не
   продвигается**, значит та же микроинструкция исполняется в следующем такте.
   На практике stall случается **перед** микроинструкцией, которая использует
   `MDR` от предыдущего `MemRequest(Read)`.

5. **Кодовый стиль.** Сигналы и селекторы — Python dataclass-ы. Микропрограмма —
   `list[list[Signal]]`.

---

## 1. Полный реестр регистров (повтор для удобства)

| Регистр  | Ширина  | Назначение                                            |
|----------|---------|-------------------------------------------------------|
| `PC`     | 32      | Program counter                                       |
| `IR`     | 32      | Instruction register                                  |
| `TOS`    | 32      | Top of data stack                                     |
| `NOS`    | 32      | Next on data stack                                    |
| `DSP`    | 8       | Указатель в DS SRAM (next-free слот)                  |
| `TORS`   | 32      | Top of return stack                                   |
| `RSP`    | 8       | Указатель в RS SRAM (next-free слот)                  |
| `MAR`    | 32      | Memory address register                               |
| `MDR`    | 32      | Memory data register                                  |
| `mPC`    | 16      | Microprogram counter                                  |
| `Z`, `N` | 1       | Флаги ALU (zero, negative)                            |

**`IR.opcode`** = `(IR >> 24) & 0xFF`, **`IR.operand`** = `IR & 0xFFFFFF`.

---

## 2. Полный реестр сигналов

### 2.1. Сигналы DataPath (управляющие линии в data path)

| Сигнал                  | Селектор / аргумент           | Действие                                                          |
|-------------------------|-------------------------------|-------------------------------------------------------------------|
| `LatchPc(sel)`          | `PcSel`                       | PC ← (см. таблицу PcSel)                                          |
| `LatchIr`               | —                             | IR ← MDR                                                          |
| `LatchMar(sel)`         | `MarSel`                      | MAR ← (см. MarSel)                                                |
| `LatchMdr(sel)`         | `MdrSel`                      | MDR ← (см. MdrSel)                                                |
| `LatchTos(sel)`         | `TosSel`                      | TOS ← (см. TosSel), флаги Z/N обновляются от нового TOS           |
| `LatchTors(sel)`        | `TorsSel`                     | TORS ← (см. TorsSel)                                              |
| `DStackPush`            | —                             | DS_SRAM[DSP] ← NOS; DSP ← DSP+1; NOS ← TOS (старый)               |
| `DStackPop`             | —                             | DSP ← DSP-1; NOS ← DS_SRAM[DSP]                                   |
| `RStackPush`            | —                             | RS_SRAM[RSP] ← TORS; RSP ← RSP+1                                  |
| `RStackPop`             | —                             | RSP ← RSP-1; TORS ← RS_SRAM[RSP-1]                                |
| `AluOp(op)`             | `AluOpSel`                    | Запустить ALU над (NOS, TOS). Результат на шине ALU.OUT.          |
| `MemRequest(op)`        | `MemOp`                       | Отправить запрос в кеш: read или write по адресу MAR              |

### 2.2. Сигналы ControlUnit

| Сигнал                  | Селектор             | Действие                                                          |
|-------------------------|----------------------|-------------------------------------------------------------------|
| `LatchMpc(sel)`         | `MpcSel`             | mPC ← Zero (=0) / Next (mPC+1) / Opcode (MPC_OF_OPCODE[IR.opcode])|
| `Halt`                  | —                    | Поднять флаг остановки модели                                     |

### 2.3. Селекторы

#### `PcSel`
| Значение        | PC ←                                                              |
|-----------------|-------------------------------------------------------------------|
| `Next`          | PC + 1                                                            |
| `Jmp`           | IR.operand (адрес перехода из текущей инструкции)                 |
| `Jz`            | если флаг Z=1 — IR.operand, иначе PC + 1                          |
| `FromTors`      | TORS (для `RET`)                                                  |
| `FromTos`       | TOS (для `EXECUTE`)                                               |

#### `MarSel`
| Значение  | MAR ←                                                                   |
|-----------|-------------------------------------------------------------------------|
| `FromPc`  | PC                                                                      |
| `FromTos` | TOS                                                                     |

#### `MdrSel`
| Значение   | MDR ←                                                                  |
|------------|------------------------------------------------------------------------|
| `FromMem`  | Шина данных от кеша (после `MemRequest(Read)`)                         |
| `FromNos`  | NOS (для `STORE`)                                                      |

#### `TosSel`
| Значение         | TOS ←                                                            |
|------------------|------------------------------------------------------------------|
| `FromAlu`        | Выход ALU                                                        |
| `FromMdr`        | MDR (для `LIT`, `LOAD`)                                          |
| `FromNos`        | NOS (для `DROP`, `SWAP`-стороны)                                 |
| `FromTors`       | TORS (для `R>`, `R@`)                                            |

#### `TorsSel`
| Значение   | TORS ←                                                                 |
|------------|------------------------------------------------------------------------|
| `FromPc`   | PC (для `CALL` — адрес возврата)                                       |
| `FromTos`  | TOS (для `>R`)                                                         |

#### `MpcSel`
| Значение  | mPC ←                                                                   |
|-----------|-------------------------------------------------------------------------|
| `Zero`    | 0 (стартовый адрес FETCH)                                               |
| `Next`    | mPC + 1                                                                 |
| `Opcode`  | MPC_OF_OPCODE[IR.opcode] (декодирование)                                |

#### `AluOpSel`
| Значение  | Результат                                                               |
|-----------|-------------------------------------------------------------------------|
| `Add`     | NOS + TOS                                                               |
| `Sub`     | NOS - TOS                                                               |
| `Mul`     | NOS * TOS                                                               |
| `Div`     | NOS / TOS (целочисленное)                                               |
| `Mod`     | NOS mod TOS                                                             |
| `Eq`      | -1 если NOS == TOS, иначе 0                                             |
| `Lt`      | -1 если NOS < TOS, иначе 0                                              |
| `Gt`      | -1 если NOS > TOS, иначе 0                                              |
| `And`     | NOS & TOS (побитово)                                                    |
| `Or`      | NOS \| TOS (побитово)                                                   |
| `Invert`  | ~TOS (унарная, NOS не используется)                                     |

#### `MemOp`
| Значение  | Действие                                                                |
|-----------|-------------------------------------------------------------------------|
| `Read`    | Кеш: положить mem[MAR] в MDR (асинхронно, занимает 1 или 10 тактов)     |
| `Write`   | Кеш: записать MDR в mem[MAR] (1 или 10/19 тактов)                       |

---

## 3. Правила параллелизма (важно при чтении микропрограммы)

**Правило старых значений.** Все источники справа от `←` берутся **до** срабатывания
защёлок этого такта. Например, на одном такте:
- `DStackPush` (хочет старый NOS для SRAM, старый TOS для NOS)
- `LatchTos(FromAlu)` (хочет выход ALU, который зависит от старых TOS и NOS)

Оба сигнала используют **старые** TOS/NOS как входы. Новые значения защёлкиваются
только в конце такта.

**Запрещённые комбинации:**

| Комбинация                                 | Почему нельзя                                  |
|--------------------------------------------|------------------------------------------------|
| `DStackPush` + `DStackPop`                 | конфликт по NOS и SRAM-порту                   |
| `RStackPush` + `RStackPop`                 | то же для RS                                   |
| Две разные защёлки одного регистра         | конфликт по входу D-триггера                   |
| `LatchNos(...)` + `DStackPush`             | оба пишут NOS (Push сам пишет: NOS ← TOS)      |
| `LatchNos(...)` + `DStackPop`              | оба пишут NOS (Pop сам пишет: NOS ← SRAM)      |
| `LatchTors(...)` + `RStackPop`             | оба пишут TORS                                 |
| `MemRequest(Read)` + `MemRequest(Write)`   | один порт памяти                               |

**Разрешённые сочетания** (примеры):
- `DStackPush + LatchTos(X)` — push поднимает стек, X указывает новое значение TOS.
- `DStackPop + LatchTos(X)` — pop опускает стек, X переопределяет TOS (по умолчанию TOS не меняется при DStackPop, что почти всегда неправильно — почти всегда нужен LatchTos(FromNos) или ALU).
- `RStackPush + LatchTors(X)` — push сохраняет TORS в SRAM, X кладёт новое значение в TORS.
- `RStackPop + LatchTos(...)` — pop возвращает TORS со SRAM, отдельно обновляем TOS.

**`LatchNos`/`LatchTors` без push/pop** — да, такое возможно (например, для прямых
перестановок типа SWAP), но в большинстве случаев `NOS` управляется автоматически
push/pop.

---

## 4. Полная микропрограмма

Адреса микроинструкций — десятичные. Структура:
- **0–1**: FETCH (общая для всех инструкций).
- **2+**: тела микропрограмм по опкодам, каждая заканчивается `LatchMpc(Zero)` —
  возврат к FETCH (или `Halt` для HALT).

### 4.1. FETCH

```
[0] FETCH_1:  [LatchMar(FromPc), MemRequest(Read), LatchPc(Next), LatchMpc(Next)]
              # MAR ← PC; запросили чтение слова инструкции; PC ← PC+1 (готовимся к следующей)
              # — увеличение PC параллельно запросу безопасно: новый MAR уже защёлкнут
              # из старого PC, а новый PC войдёт в действие только со следующего такта.

[1] FETCH_2:  [LatchMdr(FromMem), LatchIr, LatchMpc(Opcode)]
              # MDR ← кеш (stall здесь, пока кеш не готов);
              # IR ← MDR; mPC ← MPC_OF_OPCODE[IR.opcode] — декод.
```

**Stall-нюанс.** На такте FETCH_2 первым сигналом стоит `LatchMdr(FromMem)`.
Если кеш ещё не отдал данные (busy), `ControlUnit.tick()` блокирует выполнение
всей микроинструкции — этот же такт повторится, пока кеш не выставит `done`.
Это происходит автоматически через ветку `is_busy()` в `CU.tick()`, в микрокоде
ничего дополнительно писать не нужно.

### 4.2. Микропрограммы по опкодам

Для удобства проверки слева — комментарий с эффектом на стеке (Forth-нотация).

#### Нулевая группа

```
[2] NOP:      [LatchMpc(Zero)]

[3] HALT:     [Halt]
```

#### LIT — `( -- n )`, читает следующее слово как 32-битное значение

```
[4] LIT_1:    [LatchMar(FromPc), MemRequest(Read), LatchPc(Next), LatchMpc(Next)]
              # запросили чтение следующего слова, PC ← PC+1
[5] LIT_2:    [DStackPush, LatchMdr(FromMem), LatchTos(FromMdr), LatchMpc(Zero)]
              # push: SRAM ← старый NOS, NOS ← старый TOS;
              # MDR ← кеш (stall здесь, пока кеш не готов);
              # TOS ← MDR (значение литерала).
```

#### DUP — `( a -- a a )`

```
[6] DUP:      [DStackPush, LatchMpc(Zero)]
              # push: SRAM ← NOS, NOS ← TOS. TOS не меняется (LatchTos не указан).
              # После: TOS=a, NOS=a. Глубже — старый NOS.
```

#### DROP — `( a -- )`

```
[7] DROP:     [LatchTos(FromNos), DStackPop, LatchMpc(Zero)]
              # TOS ← старый NOS; параллельно NOS ← SRAM[--DSP].
```

#### SWAP — `( a b -- b a )`

```
[8] SWAP:     [LatchTos(FromNos), LatchNos(FromTos), LatchMpc(Zero)]
              # TOS ← старый NOS, NOS ← старый TOS — параллельный обмен.
              # SRAM и DSP не трогаем.
```

Здесь `LatchNos(FromTos)` — отдельный селектор `NosSel.FromTos`. Дополняем
таблицу `NosSel`:

| Значение          | NOS ←                                                            |
|-------------------|------------------------------------------------------------------|
| `FromTos`         | TOS (для `SWAP`)                                                 |

#### OVER — `( a b -- a b a )`

```
[9] OVER:     [DStackPush, LatchTos(FromNos), LatchMpc(Zero)]
              # push: SRAM ← старый NOS (=a), NOS ← старый TOS (=b);
              # параллельно TOS ← старый NOS (=a).
              # После: SRAM[..., a], NOS=b, TOS=a — что и есть «a b a».
```

#### Бинарная АЛУ — `( a b -- r )`

Шаблон одинаковый для ADD/SUB/MUL/DIV/MOD/EQ/LT/GT/AND/OR.

```
[10] ADD:     [AluOp(Add),    LatchTos(FromAlu), DStackPop, LatchMpc(Zero)]
[11] SUB:     [AluOp(Sub),    LatchTos(FromAlu), DStackPop, LatchMpc(Zero)]
[12] MUL:     [AluOp(Mul),    LatchTos(FromAlu), DStackPop, LatchMpc(Zero)]
[13] DIV:     [AluOp(Div),    LatchTos(FromAlu), DStackPop, LatchMpc(Zero)]
[14] MOD:     [AluOp(Mod),    LatchTos(FromAlu), DStackPop, LatchMpc(Zero)]
[15] EQ:      [AluOp(Eq),     LatchTos(FromAlu), DStackPop, LatchMpc(Zero)]
[16] LT:      [AluOp(Lt),     LatchTos(FromAlu), DStackPop, LatchMpc(Zero)]
[17] GT:      [AluOp(Gt),     LatchTos(FromAlu), DStackPop, LatchMpc(Zero)]
[18] AND:     [AluOp(And),    LatchTos(FromAlu), DStackPop, LatchMpc(Zero)]
[19] OR:      [AluOp(Or),     LatchTos(FromAlu), DStackPop, LatchMpc(Zero)]
```

#### Унарная АЛУ — `( a -- r )`

```
[20] INVERT:  [AluOp(Invert), LatchTos(FromAlu), LatchMpc(Zero)]
              # стек не двигаем — только TOS заменяется на ~TOS.
```

#### LOAD — `( addr -- val )`, `@`

```
[21] LOAD_1:  [LatchMar(FromTos), MemRequest(Read), LatchMpc(Next)]
              # MAR ← addr (с TOS), запрос на чтение.
[22] LOAD_2:  [LatchMdr(FromMem), LatchTos(FromMdr), LatchMpc(Zero)]
              # MDR ← кеш (stall здесь, пока кеш не готов);
              # TOS ← MDR.
```

#### STORE — `( val addr -- )`, `!`

`addr` на TOS, `val` на NOS.

```
[23] STORE_1: [LatchMar(FromTos), LatchMdr(FromNos), MemRequest(Write),
               LatchTos(FromNos), DStackPop, LatchMpc(Next)]
              # MAR ← addr; MDR ← val; запрос на запись;
              # параллельно: TOS ← старый NOS = val (через мгновение пропадёт);
              # DStackPop: NOS ← SRAM[--DSP] (новое значение под бывшим val).
              # На этом такте на стеке: TOS=val (временно), NOS=что было под val.

[24] STORE_2: [LatchTos(FromNos), DStackPop, LatchMpc(Zero)]
              # ещё один pop, чтобы убрать «временный» TOS=val.
              # Stall здесь — если write не успел (write-back при miss).
```

**Альтернатива (более логичная по смыслу) — сначала pop'нуть оба, потом записать.**
Но тогда нужен ещё один регистр под адрес. Текущий вариант проще и не вводит новых
регистров. Цена — две микроинструкции вместо «одной красивой».

#### JMP — `( -- )`, безусловный переход на `IR.operand`

```
[25] JMP:     [LatchPc(Jmp), LatchMpc(Zero)]
              # PC ← IR.operand (затирает PC+1 из FETCH).
```

#### JZ — `( flag -- )`, переход если flag == 0

```
[26] JZ:      [LatchPc(Jz), LatchTos(FromNos), DStackPop, LatchMpc(Zero)]
              # PC ← Jz (использует флаг Z, который установлен от старого TOS);
              # параллельно снимаем flag со стека.
```

Тонкость: `LatchPc(Jz)` смотрит на флаг `Z`, который должен отражать **текущее
значение TOS**. По правилу из таблицы (см. 2.1), `LatchTos` обновляет флаги от
**нового** TOS. Но здесь нам нужен флаг от **старого** TOS (того самого flag-а).

**Решение:** флаги в DataPath обновляются **в начале такта**, до защёлок (как часть
combinational-логики). На входе такта Z отражает значение TOS-как-есть. ALU/Latch
обновляют флаги только если им явно сказано (отдельный момент — большинство
ALU-операций обновляют флаги, потому что пишут через ALU). Для `JZ` достаточно
условия: «Z от TOS на входе такта» — это естественно, потому что Z — это
combinational функция от значения регистра TOS, а не отдельный регистр.

**В реализации:** `flag_z(self) -> bool: return self.tos == 0`. Никакого
отдельного защёлкивания флага.

#### CALL — `( -- )`, переход с сохранением адреса возврата

```
[27] CALL:    [LatchTors(FromPc), RStackPush, LatchPc(Jmp), LatchMpc(Zero)]
              # TORS ← PC (= уже инкрементированный PC = адрес инструкции после CALL);
              # RStackPush: RS_SRAM ← старый TORS, RSP++;
              # PC ← IR.operand;
              # Параллельно — без конфликта (FromPc и Jmp оба читают PC до защёлки,
              # но LatchPc(Jmp) перезаписывает, а LatchTors(FromPc) уже зафиксировал
              # старое значение).
```

#### RET — `( -- )`

```
[28] RET:     [LatchPc(FromTors), RStackPop, LatchMpc(Zero)]
              # PC ← TORS (старый); параллельно TORS ← RS_SRAM[--RSP].
```

#### EXECUTE — `( xt -- )`, вызов по адресу с вершины стека

```
[29] EXECUTE: [LatchTors(FromPc), RStackPush,
               LatchPc(FromTos), LatchTos(FromNos), DStackPop, LatchMpc(Zero)]
              # Как CALL, но новый PC берётся из TOS, а не из IR.operand.
              # Параллельно снимаем xt со стека (стандартный pop).
```

#### `>R` — `( a -- )(R: -- a)`

```
[30] TO_R:    [LatchTors(FromTos), RStackPush, LatchTos(FromNos), DStackPop, LatchMpc(Zero)]
              # TORS ← старый TOS; RStackPush сохраняет старый TORS в RS_SRAM;
              # параллельно стандартный pop с DS.
```

#### `R>` — `( -- a )(R: a -- )`

```
[31] R_FROM:  [DStackPush, LatchTos(FromTors), RStackPop, LatchMpc(Zero)]
              # push на DS (SRAM ← NOS, NOS ← TOS);
              # TOS ← старый TORS;
              # параллельно RStackPop: TORS ← RS_SRAM[--RSP].
```

#### `R@` — `( -- a )(R: a -- a)`

```
[32] R_FETCH: [DStackPush, LatchTos(FromTors), LatchMpc(Zero)]
              # push на DS, TOS ← TORS, RS не трогаем.
```

### 4.3. Сводная таблица занятых адресов

| mPC | Имя        | Заметки                                |
|-----|------------|----------------------------------------|
| 0   | FETCH_1    |                                        |
| 1   | FETCH_2    | + decode                               |
| 2   | NOP        | 1 такт                                 |
| 3   | HALT       | 1 такт                                 |
| 4   | LIT_1      |                                        |
| 5   | LIT_2      | stall возможен                         |
| 6   | DUP        | 1 такт                                 |
| 7   | DROP       | 1 такт                                 |
| 8   | SWAP       | 1 такт                                 |
| 9   | OVER       | 1 такт                                 |
| 10  | ADD        | 1 такт                                 |
| 11  | SUB        |                                        |
| 12  | MUL        |                                        |
| 13  | DIV        |                                        |
| 14  | MOD        |                                        |
| 15  | EQ         |                                        |
| 16  | LT         |                                        |
| 17  | GT         |                                        |
| 18  | AND        |                                        |
| 19  | OR         |                                        |
| 20  | INVERT     |                                        |
| 21  | LOAD_1     |                                        |
| 22  | LOAD_2     | stall возможен                         |
| 23  | STORE_1    |                                        |
| 24  | STORE_2    | stall возможен                         |
| 25  | JMP        | 1 такт                                 |
| 26  | JZ         | 1 такт                                 |
| 27  | CALL       | 1 такт                                 |
| 28  | RET        | 1 такт                                 |
| 29  | EXECUTE    | 1 такт                                 |
| 30  | TO_R       |                                        |
| 31  | R_FROM     |                                        |
| 32  | R_FETCH    |                                        |

Всего: 33 микроинструкции.

---

## 5. `MPC_OF_OPCODE`

Полная карта, генерируется по таблице выше:

```python
MPC_OF_OPCODE: dict[Opcode, int] = {
    Opcode.NOP:     2,
    Opcode.HALT:    3,
    Opcode.LIT:     4,
    Opcode.DUP:     6,
    Opcode.DROP:    7,
    Opcode.SWAP:    8,
    Opcode.OVER:    9,
    Opcode.ADD:     10,
    Opcode.SUB:     11,
    Opcode.MUL:     12,
    Opcode.DIV:     13,
    Opcode.MOD:     14,
    Opcode.EQ:      15,
    Opcode.LT:      16,
    Opcode.GT:      17,
    Opcode.AND:     18,
    Opcode.OR:      19,
    Opcode.INVERT:  20,
    Opcode.LOAD:    21,
    Opcode.STORE:   23,
    Opcode.JMP:     25,
    Opcode.JZ:      26,
    Opcode.CALL:    27,
    Opcode.RET:     28,
    Opcode.EXECUTE: 29,
    Opcode.TO_R:    30,
    Opcode.R_FROM:  31,
    Opcode.R_FETCH: 32,
}
```

Должны быть покрыты **все** 28 опкодов из `isa.py`. При добавлении нового опкода
(см. секция «Расширяемость» в ARCHITECTURE.md):
1. Добавить микропрограмму в `MPROGRAM` по следующему свободному адресу.
2. Добавить запись в `MPC_OF_OPCODE`.

---

## 6. Контракт для `microcode.py`

Файл должен экспортировать:

```python
# Селекторы (Enum)
class PcSel(Enum):     Next; Jmp; Jz; FromTors; FromTos
class MarSel(Enum):    FromPc; FromTos
class MdrSel(Enum):    FromMem; FromNos
class TosSel(Enum):    FromAlu; FromMdr; FromNos; FromTors
class NosSel(Enum):    FromTos
class TorsSel(Enum):   FromPc; FromTos
class MpcSel(Enum):    Zero; Next; Opcode
class AluOpSel(Enum):  Add; Sub; Mul; Div; Mod; Eq; Lt; Gt; And; Or; Invert
class MemOp(Enum):     Read; Write

# Сигналы (dataclass или NamedTuple)
@dataclass(frozen=True)
class LatchPc:     sel: PcSel
@dataclass(frozen=True)
class LatchIr:     pass
@dataclass(frozen=True)
class LatchMar:    sel: MarSel
@dataclass(frozen=True)
class LatchMdr:    sel: MdrSel
@dataclass(frozen=True)
class LatchTos:    sel: TosSel
@dataclass(frozen=True)
class LatchNos:    sel: NosSel
@dataclass(frozen=True)
class LatchTors:   sel: TorsSel
@dataclass(frozen=True)
class DStackPush:  pass
@dataclass(frozen=True)
class DStackPop:   pass
@dataclass(frozen=True)
class RStackPush:  pass
@dataclass(frozen=True)
class RStackPop:   pass
@dataclass(frozen=True)
class AluOp:       op: AluOpSel
@dataclass(frozen=True)
class MemRequest:  op: MemOp
@dataclass(frozen=True)
class LatchMpc:    sel: MpcSel
@dataclass(frozen=True)
class Halt:        pass

Signal = (LatchPc | LatchIr | LatchMar | LatchMdr | LatchTos | LatchNos |
          LatchTors | DStackPush | DStackPop | RStackPush | RStackPop |
          AluOp | MemRequest | LatchMpc | Halt)

# Микропрограмма
MPROGRAM: list[list[Signal]] = [
    # 0: FETCH_1
    [LatchMar(MarSel.FromPc), MemRequest(MemOp.Read), LatchPc(PcSel.Next), LatchMpc(MpcSel.Next)],
    # 1: FETCH_2
    [LatchIr(), LatchMpc(MpcSel.Opcode)],
    # ... все 33 микроинструкции по таблице ...
]

# Карта опкод → стартовый адрес в MPROGRAM
MPC_OF_OPCODE: dict[Opcode, int] = { ... }  # см. секцию 5
```

**Никакой логики исполнения** в `microcode.py` нет — только декларация типов и данные.

---

## 7. Doctest'ы, которые нужны в `microcode.py`

```python
def _validate_mprogram() -> None:
    """
    Проверки на консистентность микропрограммы:

    >>> from isa import Opcode
    >>> # У каждого опкода есть запись в MPC_OF_OPCODE.
    >>> all(op in MPC_OF_OPCODE for op in Opcode)
    True
    >>> # Все адреса в MPC_OF_OPCODE — валидные индексы MPROGRAM.
    >>> all(0 <= addr < len(MPROGRAM) for addr in MPC_OF_OPCODE.values())
    True
    >>> # Каждая микроинструкция кончается либо LatchMpc, либо Halt.
    >>> def _terminal(uinstr):
    ...     return any(isinstance(s, (LatchMpc, Halt)) for s in uinstr)
    >>> all(_terminal(u) for u in MPROGRAM)
    True
    >>> # FETCH_1 всегда по адресу 0.
    >>> MPROGRAM[0][0] == LatchMar(MarSel.FromPc)
    True
    """
```

(Это для иллюстрации — пусть Claude Code сделает похожие проверки в виде модульной
функции `_self_check()` с doctest-ами; запускаются автоматически через
`pytest --doctest-modules`.)

---

## 8. Что НЕ входит в `microcode.py`

- Реализация ALU (живёт в machine.py).
- DStack/RStack SRAM-операции (реализация — в machine.py).
- Cache, MMIO, MemoryRequest-логика (cache.py, machine.py).
- Связывание сигналов с методами DataPath/CU — это делает `_execute_signal()` в
  `machine.py`, по образцу `dispatch` из OCaml-референса (`microcoded.ml:104-112`).

---

## 9. Замечание о сложности

33 микроинструкции, ~14 селекторов, ~16 типов сигналов. Это **верхняя граница**
сложности микрокода — добавлять новые опкоды дёшево (1-3 строки в MPROGRAM
+ 1 строка в MPC_OF_OPCODE).

Что бы могло быть сложнее (но мы это сознательно отложили):
- Микрокод-уровневые условные переходы (поле COND в MIR) — **не нужны**, потому
  что есть атомарный `LatchPc(Jz)`, и ожидание кеша делается через stall на
  уровне tick(), а не через spin-микроинструкцию.
- Прерывания, MMU, FPU — выходит за рамки варианта.
