.PHONY: up down logs shell db test lint ingest health

up:
	docker compose up --build -d

down:
	docker compose down

logs:
	docker compose logs -f api

shell:
	docker compose exec api bash

db:
	docker compose exec db psql -U $${POSTGRES_USER:-finsight} -d $${POSTGRES_DB:-finsight}

test:
	cd backend && pytest -q

lint:
	cd backend && ruff check app tests

ingest:
	curl -sS -X POST localhost:8000/ingest | python3 -m json.tool

health:
	curl -sS localhost:8000/health | python3 -m json.tool
