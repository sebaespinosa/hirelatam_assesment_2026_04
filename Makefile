.PHONY: install init-db eval-classifier ingest-ph ingest-mocks generate-mocks run-agent dashboard test lint fmt clean

install:
	uv sync

init-db:
	uv run python -m src.db.init

eval-classifier:
	uv run python -m evals.run_classifier

ingest-ph:
	uv run python -m src.sources.producthunt

ingest-mocks:
	uv run python -m src.sources.mocks

generate-mocks:
	uv run python -m src.sources.mock_generator

run-agent:
	uv run python run_agent.py

dashboard:
	uv run streamlit run dashboard.py

test:
	uv run pytest

lint:
	uv run ruff check .

fmt:
	uv run ruff format .

clean:
	rm -rf .venv .pytest_cache .ruff_cache
	find . -type d -name __pycache__ -exec rm -rf {} +
