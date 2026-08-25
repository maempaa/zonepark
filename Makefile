.DEFAULT_GOAL := help
COMPOSE := docker compose

help:  ## Muestra esta ayuda
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-12s\033[0m %s\n",$$1,$$2}'

env:  ## Crea .env a partir de .env.example si no existe
	@test -f .env || (cp .env.example .env && echo "  .env creado")

up: env  ## Levanta el stack en desarrollo
	$(COMPOSE) up -d --build

down:  ## Baja el stack
	$(COMPOSE) down

reset:  ## Baja el stack y borra la base de datos
	$(COMPOSE) down -v

logs:  ## Sigue los logs de todos los servicios
	$(COMPOSE) logs -f

ps:  ## Estado de los servicios
	$(COMPOSE) ps

migrate:  ## Aplica las migraciones pendientes
	$(COMPOSE) exec api alembic upgrade head

revision:  ## Genera una migración. Uso: make revision m="mensaje"
	$(COMPOSE) exec api alembic revision --autogenerate -m "$(m)"

seed:  ## Carga datos iniciales
	$(COMPOSE) exec api python -m app.db.seed

test:  ## Corre las pruebas del backend
	$(COMPOSE) exec api pytest -q

lint:  ## Revisa formato y estilo
	$(COMPOSE) exec api ruff check app tests

shell:  ## Abre una shell en el contenedor de la API
	$(COMPOSE) exec api bash

psql:  ## Abre psql contra la base de datos
	$(COMPOSE) exec db psql -U $${POSTGRES_USER:-zonepark} -d $${POSTGRES_DB:-zonepark}

.PHONY: help env up down reset logs ps migrate revision seed test lint shell psql
