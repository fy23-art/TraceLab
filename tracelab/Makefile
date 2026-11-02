.PHONY: dev-api dev-worker dev-web test lint up down seed

dev-api:
	cd backend && TRACELAB_ALLOW_PRIVATE_TARGETS=true uvicorn app.main:app --reload

dev-worker:
	cd backend && TRACELAB_ALLOW_PRIVATE_TARGETS=true python -m app.worker

dev-web:
	cd frontend && npm run dev

test:
	cd backend && python -m pytest -q

lint:
	cd backend && ruff check .
	cd frontend && npm run typecheck

up:
	docker compose up -d --build

down:
	docker compose down

seed:
	python scripts/seed_demo.py
