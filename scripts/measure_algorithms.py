#!/usr/bin/env python3
"""Собирает характеристики всех golden-алгоритмов для README.

Для каждого golden/*.yml считает: строки исходника (LoC без комментариев),
размер бинаря в словах, число тактов и статистику кеша. Печатает
Markdown-таблицу. Запускается вручную.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TypedDict

from ruamel.yaml import YAML

# Скрипт лежит в scripts/, корень проекта (где isa.py и т.д.) — на уровень выше.
sys.path.insert(0, str(Path(__file__).parent.parent))

from isa import to_bytes
from machine import simulation
from translator import translate

GOLDEN_DIR = Path(__file__).parent.parent / "golden"

# Для каждого алгоритма: имя → лимит тактов (prob1 — длительный).
LIMITS = {
    "prob1": 50_000_000,
}


class Measurement(TypedDict):
    name: str
    loc: int
    code_words: int
    ticks: int
    hits: int
    misses: int
    writebacks: int


def measure(yml_path: Path) -> Measurement:
    """Прогнать один golden и собрать его характеристики."""
    yaml = YAML()
    with yml_path.open(encoding="utf-8") as f:
        data = yaml.load(f)

    source = str(data["in_source"])
    stdin = str(data["in_stdin"])
    input_tokens = [ord(c) for c in stdin]
    limit = LIMITS.get(yml_path.stem, 1_000_000)

    # LoC = непустые строки исходника, не начинающиеся с комментария \
    loc = sum(1 for line in source.splitlines() if line.strip() and not line.strip().startswith("\\"))

    code = translate(source)
    _output, ticks, stats = simulation(code, input_tokens, limit=limit)

    # Размер кода — количество слов (32 бита) в бинаре.
    code_words = len(to_bytes(code)) // 4

    return {
        "name": yml_path.stem,
        "loc": loc,
        "code_words": code_words,
        "ticks": ticks,
        "hits": stats.hits,
        "misses": stats.misses,
        "writebacks": stats.writebacks,
    }


def main() -> None:
    """Измерить все golden/*.yml и напечатать Markdown-таблицу."""
    results: list[Measurement] = []
    for yml in sorted(GOLDEN_DIR.glob("*.yml")):
        print(f"Measuring {yml.name}...", flush=True)
        results.append(measure(yml))

    print()
    print("| Алгоритм | LoC | Размер кода (слов) | Тактов | Cache hits | misses | writebacks |")
    print("|---|---|---|---|---|---|---|")
    for r in results:
        print(
            f"| {r['name']} | {r['loc']} | {r['code_words']} | "
            f"{r['ticks']} | {r['hits']} | {r['misses']} | {r['writebacks']} |"
        )


if __name__ == "__main__":
    main()
