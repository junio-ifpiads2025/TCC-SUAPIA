# Makefile raiz — atalhos para as pipelines do SUAP-IA
#
# Fluxo completo:
#   make install-all  ->  make db-up  ->  make extract-links  ->  make ingest
#   ->  make qa-generate  ->  make eval

SHELL := /bin/bash

PIPELINE_DIR  := pipeline
EXTRACTION    := $(PIPELINE_DIR)/manualsExtraction
INGESTION     := $(PIPELINE_DIR)/manualsIngestion-RAG
QA_GEN        := $(PIPELINE_DIR)/q&a-generator
EVALUATION    := $(PIPELINE_DIR)/evaluation
CHATBOT       := chat

LINKS_JSON    ?= pipeline/manualsExtraction/links.json
EXTRACTION_OUT := $(EXTRACTION)/output

# Pasta de .md (ou .json legado) a ingerir; vazio = execução mais recente da extração
SRC ?=

# Cada pipeline usa um venv próprio em <pipeline>/.venv
define venv_install
	python3 -m venv "$(1)/.venv"
	"$(1)/.venv/bin/pip" install --upgrade pip
	"$(1)/.venv/bin/pip" install -r "$(1)/requirements.txt"
endef

.DEFAULT_GOAL := help

.PHONY: help install-all install-extraction install-ingestion install-qa install-eval \
        db-up db-down db-logs db-shell db-count \
        extract extract-links ingest ingest-reset \
        qa-generate eval \
        chatbot-install chatbot-dev chatbot-prod \
        clean-output

help:
	@echo "Pipelines SUAP-IA"
	@echo ""
	@echo "Setup"
	@echo "  make install-all          instala venvs de todas as pipelines"
	@echo "  make install-<nome>       extraction | ingestion | qa | eval"
	@echo ""
	@echo "Banco (pgvector)"
	@echo "  make db-up / db-down      sobe / derruba o postgres"
	@echo "  make db-logs              logs do container"
	@echo "  make db-count             conta chunks por coleção"
	@echo "  make db-shell             abre psql"
	@echo ""
	@echo "1. Extração (HTML -> .md)"
	@echo "  make extract-links        extrai de LINKS_JSON (padrão: pipeline/manualsExtraction/links.json)"
	@echo "  make extract URLS='u1 u2' extrai uma lista de URLs"
	@echo ""
	@echo "2. Ingestão (.md -> pgvector)"
	@echo "  make ingest               ingere a extração mais recente (ou SRC=pasta|arquivo.json)"
	@echo "  make ingest-reset         APAGA a coleção no banco (pede confirmação)"
	@echo ""
	@echo "3. Avaliação"
	@echo "  make qa-generate          gera dataset sintético Q&A (Gemini)"
	@echo "  make eval                 roda RAGAS sobre o dataset mais recente"
	@echo ""
	@echo "Chat"
	@echo "  make chatbot-install | chatbot-dev | chatbot-prod"
	@echo ""
	@echo "  make clean-output         remove saídas geradas pela extração"

# ---------- Setup ----------
install-all: install-extraction install-ingestion install-qa install-eval

install-extraction:
	$(call venv_install,$(EXTRACTION))

install-ingestion:
	$(call venv_install,$(INGESTION))

install-qa:
	$(call venv_install,$(QA_GEN))

install-eval:
	$(call venv_install,$(EVALUATION))

# ---------- Banco ----------
db-up:
	docker compose -f dockercompose.yml up -d db

db-down:
	docker compose -f dockercompose.yml stop db

db-logs:
	docker compose -f dockercompose.yml logs -f db

db-shell:
	docker exec -it postgres_vector psql -U admin -d vetordatabase

db-count:
	@docker exec postgres_vector psql -U admin -d vetordatabase -c \
	  "SELECT c.name AS colecao, count(e.*) AS chunks FROM langchain_pg_collection c LEFT JOIN langchain_pg_embedding e ON e.collection_id = c.uuid GROUP BY c.name;"

# ---------- 1. Extração ----------
# Roda da raiz: o pacote é importado como pipeline.manualsExtraction
extract-links:
	@test -f "$(LINKS_JSON)" || { echo "❌ $(LINKS_JSON) não encontrado"; exit 2; }
	"$(EXTRACTION)/.venv/bin/python" -m pipeline.manualsExtraction links-json "$(LINKS_JSON)"

extract:
	@test -n "$(URLS)" || { echo "❌ Use: make extract URLS='https://... https://...'"; exit 2; }
	"$(EXTRACTION)/.venv/bin/python" -m pipeline.manualsExtraction lote $(URLS)

# ---------- 2. Ingestão ----------
# Roda da raiz; a pasta da pipeline é executável (__main__.py) e usa imports 'app.*'
ingest:
	"$(INGESTION)/.venv/bin/python" "$(INGESTION)" $(SRC)

# Ingestão é idempotente (reenviar substitui o manual); reset só para limpar a coleção toda
ingest-reset:
	@read -p "Apagar coleção 'manuais_suap_ifpi' do banco? [y/N] " r; [ "$$r" = "y" ] || { echo "cancelado"; exit 1; }
	docker exec postgres_vector psql -U admin -d vetordatabase -c \
	  "DELETE FROM langchain_pg_embedding WHERE collection_id = (SELECT uuid FROM langchain_pg_collection WHERE name='manuais_suap_ifpi');"

# ---------- 3. Avaliação ----------
qa-generate:
	cd "$(QA_GEN)" && .venv/bin/python main.py

eval:
	cd "$(EVALUATION)" && .venv/bin/python main.py

# ---------- Chat-bot ----------
chatbot-install:
	$(MAKE) -C $(CHATBOT) install

chatbot-dev:
	$(MAKE) -C $(CHATBOT) dev

chatbot-prod:
	$(MAKE) -C $(CHATBOT) prod

# ---------- Limpeza ----------
clean-output:
	rm -rf $(EXTRACTION_OUT)/*/ $(EXTRACTION_OUT)/*.json
