# 📖 API de Extração de Manuais (SUAP)

Este projeto é uma API desenvolvida em **FastAPI** concebida para fazer o download e a extração estruturada de dados de manuais online do SUAP (em formato HTML). 

A aplicação recebe um lote de URLs, descarrega o conteúdo de forma assíncrona e utiliza um *parser* inteligente para extrair o título do manual, os tópicos, o texto formatado e os links de imagens, devolvendo tudo num ficheiro JSON estruturado.

## 🚀 Tecnologias Utilizadas

* **[FastAPI](https://fastapi.tiangolo.com/):** Framework web rápido para a construção da API.
* **[HTTPX](https://www.python-httpx.org/):** Cliente HTTP assíncrono para o download das páginas.
* **[BeautifulSoup4](https://www.crummy.com/software/BeautifulSoup/bs4/doc/):** Biblioteca para extração e *parsing* do HTML.
* **[Pydantic](https://docs.pydantic.dev/):** Para validação de dados e estruturação dos esquemas (JSON).

## 📁 Estrutura do Projeto

* `app/main.py`: Ponto de entrada da aplicação FastAPI.
* `app/urls/url.py`: Definição das rotas (endpoints).
* `app/controllers/controller.py`: Lógica de orquestração e processamento assíncrono em lote.
* `app/services/service.py`: Lógica pesada de download (HTTP) e *parsing* do HTML (BeautifulSoup).
* `app/schemas/schema.py`: Modelos de dados para as requisições e respostas.

---

## 🛠️ Como Instalar e Configurar

**1. Clone o repositório ou navegue até à pasta do projeto:**
```bash
cd seu_projeto

uvicorn app.main:app --reload --port 8000