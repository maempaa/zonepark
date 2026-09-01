.DEFAULT_GOAL := help
COMPOSE := docker compose

help:  ## Muestra esta ayuda
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-12s\033[0m %s\n",$$1,$$2}'

env:  ## Crea .env a partir de .env.example si no existe
	@test -f .env || (cp .env.example .env && echo "  .env creado")

up: env  ## Levanta el stack en DESARROLLO (recarga en caliente)
	$(COMPOSE) up -d --build

# ── Producción ──────────────────────────────────────────────────────────
PROD := docker compose -f docker-compose.yml -f docker-compose.prod.yml

red:  ## Crea la red compartida con el túnel de Cloudflare
	@docker network create zonepark-publica 2>/dev/null && echo "  creada" || echo "  ya existía"

produccion: red  ## Rota los secretos de desarrollo y deja .env listo para producción
	./scripts/preparar-produccion.sh

deploy: red  ## Publica en producción: construye, migra y levanta
	$(PROD) up -d --build
	@echo
	@$(PROD) ps

respaldo:  ## Copia comprimida de la base de datos
	./scripts/respaldo.sh

prod-logs:  ## Sigue los logs de producción
	$(PROD) logs -f

prod-ps:  ## Estado de los servicios de producción
	$(PROD) ps

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

PRUEBAS := docker compose -f docker-compose.test.yml

test:  ## Corre las pruebas en una base desechable, sin tocar producción
	@$(PRUEBAS) up --build --abort-on-container-exit --exit-code-from pruebas 2>&1 \
		| grep -vE '^(zonepark-pruebas|db-pruebas)' || true
	@$(PRUEBAS) down -v >/dev/null 2>&1 || true

lint:  ## Revisa formato y estilo
	$(COMPOSE) exec api ruff check app tests

shell:  ## Abre una shell en el contenedor de la API
	$(COMPOSE) exec api bash

psql:  ## Abre psql contra la base de datos
	$(COMPOSE) exec db psql -U $${POSTGRES_USER:-zonepark} -d $${POSTGRES_DB:-zonepark}

.PHONY: help env up down reset logs ps migrate revision seed test lint shell psql \
	red produccion deploy respaldo prod-logs prod-ps
