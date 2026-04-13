import asyncio
import json
import os
from datetime import datetime
from typing import List
from fastapi import HTTPException
from fastapi.concurrency import run_in_threadpool
from app.schemas.schema import LinksJsonRequest, ManualLinksResponse, ManualResponse
from app.services.service import download_html, extrair_dados_estilo_js

async def processar_url_unica_controller(url: str) -> ManualResponse:
    try:
        html_content = await download_html(url)
        resultado = await run_in_threadpool(extrair_dados_estilo_js, html_content)
        return resultado
    except Exception as e:
        print(f"Erro ao processar {url}: {e}")
        raise HTTPException(status_code=400, detail=str(e))

async def _processar_urls(urls: List[str]) -> List[ManualResponse]:
    """Processa uma lista de URLs e retorna os resultados sem salvar arquivo."""
    tarefas = [processar_url_unica_controller(url) for url in urls]
    resultados = await asyncio.gather(*tarefas, return_exceptions=True)

    respostas_finais = []
    for i, resultado in enumerate(resultados):
        if isinstance(resultado, Exception):
            print(f"Falha na URL {urls[i]} -> {resultado}")
        else:
            respostas_finais.append(resultado)

    return respostas_finais

def _salvar_json(dados, caminho_arquivo: str) -> None:
    os.makedirs("output", exist_ok=True)
    with open(caminho_arquivo, "w", encoding="utf-8") as f:
        json.dump(dados, f, ensure_ascii=False, indent=4)
    print(f"✅ Arquivo JSON gerado com sucesso em: {caminho_arquivo}")

async def processar_lote_controller(urls: List[str]) -> List[ManualResponse]:
    respostas_finais = await _processar_urls(urls)

    if respostas_finais:
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            _salvar_json(
                [r.model_dump() for r in respostas_finais],
                f"output/manuais_{timestamp}.json"
            )
        except Exception as e:
            print(f"⚠️ Erro ao salvar o arquivo JSON: {e}")

    return respostas_finais

async def processar_links_json_controller(payload: LinksJsonRequest) -> List[ManualLinksResponse]:
    """Processa todos os manuais do links.json, agrupando resultados por nome."""
    respostas: List[ManualLinksResponse] = []

    for nome_manual, item in payload.root.items():
        urls = [str(url) for url in item.urls]
        print(f"📄 Processando manual: {nome_manual} ({len(urls)} URL(s))")
        resultados = await _processar_urls(urls)
        respostas.append(ManualLinksResponse(nome=nome_manual, resultados=resultados))

    if respostas:
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            dados = [
                {"nome": r.nome, "resultados": [res.model_dump() for res in r.resultados]}
                for r in respostas
            ]
            _salvar_json(dados, f"output/links_json_{timestamp}.json")
        except Exception as e:
            print(f"⚠️ Erro ao salvar o arquivo JSON: {e}")

    return respostas