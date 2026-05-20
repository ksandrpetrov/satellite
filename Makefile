SHELL := /bin/bash
PYTHON ?= python3
VENV ?= venv
VENV_PY := $(VENV)/bin/python
VENV_PIP := $(VENV)/bin/pip
ENTRY := telegram_test_command.py

.PHONY: help install install-dev install-server deploy venv env run test compile lint clean update

help:
	@echo "Targets:"
	@echo "  make install        bootstrap venv + runtime deps + .env (через scripts/install.sh)"
	@echo "  make install-dev    то же + requirements-dev.txt"
	@echo "  make install-server sudo установка на сервер (systemd) — scripts/install-server.sh"
	@echo "  make deploy         Docker-деплой на сервер (Ansible + Traefik + Certbot)"
	@echo "  make run            запустить бота через venv (long-polling)"
	@echo "  make test           pytest"
	@echo "  make compile        py_compile всех модулей (как в CI)"
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

run:
	$(VENV_PY) $(ENTRY)

test:
	$(VENV_PY) -m pytest

compile:
	find satellite tests -name '*.py' ! -name '._*' -print0 | xargs -0 $(VENV_PY) -m py_compile

update:
	git pull --ff-only
	$(VENV_PIP) install -r requirements.txt

clean:
	rm -rf $(VENV) .pytest_cache .mypy_cache .ruff_cache
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
