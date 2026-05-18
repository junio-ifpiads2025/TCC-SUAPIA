from typing import List
from fastapi import HTTPException
from fastapi.concurrency import run_in_threadpool
from app.schemas.schema import IngestaoRequest, IngestaoResponse, ItemExtracaoManual
from app.services.service import processar_vetorizacao

async def controller_ingestao(payload: IngestaoRequest) -> IngestaoResponse:
    try:
        if not payload.manuais:
            raise HTTPException(status_code=400, detail="A lista de manuais está vazia.")

        total_chunks = await run_in_threadpool(processar_vetorizacao, payload.manuais)

        return IngestaoResponse(
            mensagem="Ingestão para o pgvector concluída com sucesso!",
            total_manuais=len(payload.manuais),
            total_blocos_gerados=total_chunks
        )

    except Exception as e:
        print(f"Erro na ingestão: {e}")
        raise HTTPException(status_code=500, detail=f"Falha na vetorização: {str(e)}")

async def controller_ingestao_arquivo_json(itens: List[ItemExtracaoManual]) -> IngestaoResponse:
    try:
        if not itens:
            raise HTTPException(status_code=400, detail="A lista de itens está vazia.")

        # Achata todos os resultados de cada item em uma única lista de manuais
        manuais = [manual for item in itens for manual in item.resultados]

        if not manuais:
            raise HTTPException(status_code=400, detail="Nenhum manual encontrado nos itens.")

        total_chunks = await run_in_threadpool(processar_vetorizacao, manuais)

        return IngestaoResponse(
            mensagem="Ingestão do arquivo JSON concluída com sucesso!",
            total_manuais=len(manuais),
            total_blocos_gerados=total_chunks
        )

    except HTTPException:
        raise
    except Exception as e:
        print(f"Erro na ingestão do arquivo JSON: {e}")
        raise HTTPException(status_code=500, detail=f"Falha na vetorização: {str(e)}")