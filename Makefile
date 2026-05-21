SHELL := /bin/bash
PYTHON ?= python3
VENV ?= venv
VENV_PY := $(VENV)/bin/python
VENV_PIP := $(VENV)/bin/pip
ENTRY := telegram_test_command.py
DOCKER_IMAGE ?= satellite:dev

.PHONY: help install install-dev install-server deploy venv env fernet-key run test compile lint format typecheck check clean update docker-build docker-up docker-down docker-logs

help:
	@echo "Targets:"
	@echo "  make install        bootstrap venv + runtime deps + .env (через scripts/install.sh)"
	@echo "  make install-dev    то же + requirements-dev.txt"
	@echo "  make install-server sudo установка на сервер (systemd) — scripts/install-server.sh"
	@echo "  make deploy         Docker-деплой на сервер (Ansible; nginx — внешний на хосте)"
	@echo "  make run            запустить бота через venv (long-polling)"
	@echo "  make test           pytest"
	@echo "  make compile        py_compile всех модулей (как в CI)"
	@echo "  make lint           ruff (lint)"
	@echo "  make format         ruff format"
	@echo "  make typecheck      mypy на satellite/ (см. pyproject.toml)"
	@echo "  make check          lint + typecheck + compile + test"
	@echo "  make env            создать .env из шаблона и сгенерировать TOKEN_ENCRYPTION_KEY"
	@echo "  make fernet-key     напечатать новый Fernet-ключ"
	@echo "  make docker-build   собрать локальный Docker-образ ($(DOCKER_IMAGE))"
	@echo "  make docker-up      docker compose up -d (локальный stack)"
	@echo "  make docker-down    docker compose down"
	@echo "  make docker-logs    docker compose logs -f satellite"
	@echo "  make update         git pull + pip install -r requirements.txt"
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

typecheck:
	$(VENV_PY) -m mypy satellite

check: lint typecheck compile test

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

update:
	git pull --ff-only
	$(VENV_PIP) install -r requirements.txt

clean:
	rm -rf $(VENV) .pytest_cache .mypy_cache .ruff_cache
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
