all: format lint test

# Прогон перед каждым коммитом: те же проверки, что и в CI.
check: lint test

format:
	ruff format . --exclude brainfuck-master

lint:
	ruff format --check . --exclude brainfuck-master
	ruff check . --exclude brainfuck-master
	mypy --strict isa.py

test:
	pytest -v

test-update-golden:
	pytest . -v --update-goldens

normalize-goldens:
	python scripts/normalize_goldens.py
