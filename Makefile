.PHONY: install test lint typecheck check serve snapshot

install:
	pip install -e ".[dev]"

test:
	pytest

lint:
	ruff check src tests
	ruff format --check src tests

typecheck:
	mypy src

check: lint typecheck test

serve:
	python -m pams.interfaces.api

snapshot:
	python -m pams.interfaces.cli snapshot
