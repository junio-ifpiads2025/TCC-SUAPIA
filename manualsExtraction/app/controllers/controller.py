import asyncio
from typing import List
from fastapi import HTTPException
from fastapi.concurrency import run_in_threadpool
from app.schemas.schema import ManualResponse
from app.services.service import download_html, extrair_dados_estilo_js

async def processar_url_unica_controller(url: str) -> ManualResponse:
    try:
        # 1. Baixa o HTML
        html_content = await download_html(url)
        
        # 2. Faz o parsing pesado usando ThreadPool
        resultado = await run_in_threadpool(extrair_dados_estilo_js, html_content)
        return resultado
        
    except Exception as e:
        print(f"Erro ao processar {url}: {e}")
        raise HTTPException(status_code=400, detail=str(e))

async def processar_lote_controller(urls: List[str]) -> List[ManualResponse]:
    # Cria as tarefas assíncronas para processar todas as URLs do lote simultaneamente
    tarefas = [processar_url_unica_controller(str(url)) for url in urls]
    
    # Executa todas juntas (se der erro em uma, não para as outras)
    resultados = await asyncio.gather(*tarefas, return_exceptions=True)
    
    respostas_finais = []
    for i, resultado in enumerate(resultados):
        if isinstance(resultado, Exception):
            print(f"Falha na URL {urls[i]} -> {resultado}")
            # Se preferir, você pode adicionar um dicionário de erro na lista de respostas
        else:
            respostas_finais.append(resultado)
            
    return respostas_finais