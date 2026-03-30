from fastapi import FastAPI
from fastapi import FastAPI
from app.urls.url import router as manual_router

app = FastAPI(
    title="Ingestor de Manuais IFPI (RAG)",
    description="API para processamento e extração em lote de dados de manuais HTML.",
    version="1.0.0"
)

# Inclui as rotas do ficheiro urls.py
app.include_router(manual_router, prefix="/api/v1")