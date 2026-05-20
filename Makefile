# Makefile
dev:
	docker-compose up -d

migrate:
	alembic upgrade head

worker:
	celery -A app.workers.celery_app worker -Q documents,ai -c 4 -l INFO

test:
	pytest tests/ -v --cov=app --cov-report=term-missing

lint:
	ruff check app/ tests/ && mypy app/

format:
	ruff format app/ tests/
