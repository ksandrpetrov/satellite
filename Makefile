SHELL := /bin/bash
PYTHON ?= python3
VENV ?= venv
VENV_PY := $(VENV)/bin/python
VENV_PIP := $(VENV)/bin/pip
ENTRY := telegram_test_command.py
DOCKER_IMAGE ?= satellite:dev
GRAPHIFY_VERSION ?= 0.9.27
GRAPHIFY := uv tool run --from "graphifyy==$(GRAPHIFY_VERSION)" graphify
UV ?= uv
UV_VERSION ?= 0.11.32

.PHONY: help install install-dev install-server deploy venv env fernet-key run test compile lint format format-check typecheck check lock lock-check check-uv clean update docker-build docker-up docker-down docker-logs docker-smoke smoke-prod graphify-install graphify-update graphify-check

help:
	@echo "Targets:"
	@echo "  make install        bootstrap venv + runtime deps + .env (через scripts/install.sh)"
	@echo "  make install-dev    то же из generated requirements-dev.txt"
	@echo "  make install-server sudo установка на сервер (systemd) — scripts/install-server.sh"
	@echo "  make deploy         Docker-деплой на сервер (Ansible; nginx — внешний на хосте)"
	@echo "  make run            запустить бота через venv (long-polling)"
	@echo "  make test           pytest"
	@echo "  make compile        py_compile всех модулей (как в CI)"
	@echo "  make lint           ruff (lint)"
	@echo "  make format         ruff format"
	@echo "  make format-check   ruff format --check (как в CI)"
	@echo "  make typecheck      mypy на satellite/ (см. pyproject.toml)"
	@echo "  make check          lint + format-check + typecheck + compile + test"
	@echo "  make lock           обновить generated lock-файлы через uv $(UV_VERSION)"
	@echo "  make lock-check     проверить соответствие lock-файлов requirements*.in"
	@echo "  make env            создать .env из шаблона и сгенерировать TOKEN_ENCRYPTION_KEY"
	@echo "  make fernet-key     напечатать новый Fernet-ключ"
	@echo "  make docker-build   собрать локальный Docker-образ ($(DOCKER_IMAGE))"
	@echo "  make docker-up      docker compose up -d (локальный stack)"
	@echo "  make docker-down    docker compose down"
	@echo "  make docker-logs    docker compose logs -f satellite"
	@echo "  make docker-smoke   smoke собранного образа (import + /healthz)"
	@echo "  make smoke-prod     проверка публичного URL (SATELLITE_BASE_URL)"
	@echo "  make update         git pull + pip install -r requirements.txt"
	@echo "  make graphify-install установить Graphify CLI $(GRAPHIFY_VERSION) через uv"
	@echo "  make graphify-update  обновить кодовую часть knowledge graph (без LLM)"
	@echo "  make graphify-check   проверить, требуется ли semantic update"
	@echo "  make clean          удалить venv и кэши"

install:
	bash scripts/install.sh

install-dev:
	bash scripts/install.sh --dev

install-server:
	sudo bash scripts/install-server.sh

deploy:
	cd deploy/ansible && ansible-playbook site.yml

venv:
	@[ -d "$(VENV)" ] || $(PYTHON) -m venv $(VENV)

env: venv
	@[ -f .env ] || ( cp .env.example .env && \
		KEY=$$($(VENV_PY) -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())' 2>/dev/null || \
			 $(PYTHON) -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())') && \
		( sed -i '' "s|^TOKEN_ENCRYPTION_KEY=.*|TOKEN_ENCRYPTION_KEY=$$KEY|" .env 2>/dev/null || \
		  sed -i "s|^TOKEN_ENCRYPTION_KEY=.*|TOKEN_ENCRYPTION_KEY=$$KEY|" .env ) && \
		echo ".env создан, TOKEN_ENCRYPTION_KEY сгенерирован" )

fernet-key:
	@$(VENV_PY) -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())' 2>/dev/null || \
	 $(PYTHON) -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'

run:
	$(VENV_PY) $(ENTRY)

test:
	$(VENV_PY) -m pytest

compile:
	find satellite tests -name '*.py' ! -name '._*' -print0 | xargs -0 $(VENV_PY) -m py_compile

lint:
	$(VENV_PY) -m ruff check satellite tests

format:
	$(VENV_PY) -m ruff format satellite tests

format-check:
	$(VENV_PY) -m ruff format --check satellite tests

typecheck:
	$(VENV_PY) -m mypy satellite

check: lint format-check typecheck compile test

check-uv:
	@ACTUAL="$$($(UV) --version | awk '{print $$2}')"; \
	[ "$$ACTUAL" = "$(UV_VERSION)" ] || { \
		echo "ERROR: нужен uv $(UV_VERSION), найден $$ACTUAL"; \
		exit 1; \
	}

lock: check-uv
	$(UV) pip compile requirements.in \
		--universal \
		--python-version 3.11 \
		--upgrade \
		--custom-compile-command "make lock" \
		--output-file requirements.txt
	$(UV) pip compile requirements-dev.in \
		--universal \
		--python-version 3.11 \
		--upgrade \
		--custom-compile-command "make lock" \
		--output-file requirements-dev.txt

lock-check: check-uv
	@TMP_DIR="$$(mktemp -d)"; \
	trap 'rm -rf "$$TMP_DIR"' EXIT; \
	$(UV) pip compile requirements.in \
		--universal \
		--python-version 3.11 \
		--custom-compile-command "make lock" \
		--output-file "$$TMP_DIR/requirements.txt" >/dev/null; \
	$(UV) pip compile requirements-dev.in \
		--universal \
		--python-version 3.11 \
		--custom-compile-command "make lock" \
		--output-file "$$TMP_DIR/requirements-dev.txt" >/dev/null; \
	diff -u requirements.txt "$$TMP_DIR/requirements.txt"; \
	diff -u requirements-dev.txt "$$TMP_DIR/requirements-dev.txt"

docker-build:
	docker build -t $(DOCKER_IMAGE) .

docker-up:
	@[ -f .env ] || ( echo "ERROR: .env not found. Run 'make env' first." && exit 1 )
	docker compose up -d --build
	@echo "Bot started. Web App health: http://127.0.0.1:$$(grep '^WEBAPP_PORT=' .env | cut -d= -f2 || echo 8080)/healthz"

docker-down:
	docker compose down

docker-logs:
	docker compose logs -f satellite

docker-smoke: docker-build
	SMOKE_SKIP_PULL=1 bash scripts/docker-smoke-image.sh $(DOCKER_IMAGE)

smoke-prod:
	bash scripts/smoke-prod.sh

update:
	git pull --ff-only
	$(VENV_PIP) install -r requirements.txt

graphify-install:
	uv tool install --force "graphifyy==$(GRAPHIFY_VERSION)"
	uv tool update-shell
	$(GRAPHIFY) --version

graphify-update:
	$(GRAPHIFY) update .

graphify-check:
	$(GRAPHIFY) check-update .

clean:
	rm -rf $(VENV) .pytest_cache .mypy_cache .ruff_cache
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
