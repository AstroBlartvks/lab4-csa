all: format lint test

format:
	ruff format . --exclude brainfuck-master

lint:
	ruff check --fix . --exclude brainfuck-master
	mypy --strict isa.py

test:
	pytest -v

test-update-golden:
	pytest . -v --update-goldens

normalize-goldens:
	python scripts/normalize_goldens.py
