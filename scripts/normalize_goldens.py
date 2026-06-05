#!/usr/bin/env python3
"""Нормализация golden/*.yml: многострочные поля → literal block scalar (|-).

pytest-golden при --update-goldens сохраняет многострочные значения как
double-quoted scalar с \\n, что нечитаемо. Этот скрипт переписывает поля
in_source / out_log / out_code_hex / out_stdout в literal block scalar,
чтобы Forth-исходник и журнал читались как код.

Запускается ВРУЧНУЮ после `pytest --update-goldens` (см. `make normalize-goldens`),
в CI не входит.
"""

from __future__ import annotations

from pathlib import Path

from ruamel.yaml import YAML
from ruamel.yaml.scalarstring import LiteralScalarString

GOLDEN_DIR = Path(__file__).parent.parent / "golden"
MULTILINE_FIELDS = ("in_source", "out_log", "out_code_hex", "out_stdout")


def normalize(path: Path) -> None:
    """Переписать многострочные поля одного YAML в стиль |-."""
    yaml = YAML()
    yaml.preserve_quotes = True
    yaml.width = 10000  # не переносить длинные строки автоматически

    with path.open("r", encoding="utf-8") as f:
        data = yaml.load(f)

    changed = False
    for field in MULTILINE_FIELDS:
        value = data.get(field)
        if isinstance(value, str) and "\n" in value and not isinstance(value, LiteralScalarString):
            data[field] = LiteralScalarString(value)
            changed = True

    if changed:
        with path.open("w", encoding="utf-8") as f:
            yaml.dump(data, f)
        print(f"normalized: {path.name}")
    else:
        print(f"unchanged:  {path.name}")


def main() -> None:
    """Пройти по всем golden/*.yml и нормализовать стиль scalar'ов."""
    for yml in sorted(GOLDEN_DIR.glob("*.yml")):
        normalize(yml)


if __name__ == "__main__":
    main()
