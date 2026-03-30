import asyncio
import json
import os
from datetime import datetime
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
        else:
            respostas_finais.append(resultado)
            
    # --- NOVO: GERAR O ARQUIVO JSON LOCALMENTE ---
    if respostas_finais:
        try:
            # Cria a pasta 'output' na raiz do manualsExtraction se não existir
            os.makedirs("output", exist_ok=True)
            
            # Converte os modelos Pydantic para dicionários
            # Nota: Usando .model_dump() para Pydantic v2. Se usar v1, mude para .dict()
            dados_json = [resposta.model_dump() for resposta in respostas_finais]
            
            # Gera um nome de arquivo único com base no timestamp
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            caminho_arquivo = f"output/manuais_{timestamp}.json"
            
            # Salva o arquivo JSON com formatação legível (indent=4) e suportando acentos (ensure_ascii=False)
            with open(caminho_arquivo, "w", encoding="utf-8") as f:
                json.dump(dados_json, f, ensure_ascii=False, indent=4)
                
            print(f"✅ Arquivo JSON gerado com sucesso em: {caminho_arquivo}")
        except Exception as e:
            print(f"⚠️ Erro ao salvar o arquivo JSON: {e}")
    # ---------------------------------------------
            
    return respostas_finais