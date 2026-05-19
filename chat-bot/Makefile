VENV = .venv
PYTHON = $(VENV)/bin/python
PIP = $(VENV)/bin/pip
UVICORN = $(VENV)/bin/uvicorn
APP = main:app

.PHONY: help install dev prod

help:
	@echo "Comandos disponíveis:"
	@echo "  make install  — cria venv e instala dependências"
	@echo "  make dev      — inicia servidor em modo desenvolvimento (reload automático, usa .env)"
	@echo "  make prod     — inicia servidor em modo produção (usa .env.prod)"

install:
	python3 -m venv $(VENV)
	$(PIP) install --upgrade pip
	$(PIP) install -r requirements.txt

dev:
	bash -c 'set -a && source .env.dev && set +a && $(UVICORN) $(APP) --host 0.0.0.0 --port 8002 --reload'

prod:
	bash -c 'set -a && source .env.prod && set +a && $(UVICORN) $(APP) --host 0.0.0.0 --port 8002 --workers 4'
