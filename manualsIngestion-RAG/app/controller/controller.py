from fastapi import HTTPException
from fastapi.concurrency import run_in_threadpool
from app.schemas.schema import IngestaoRequest, IngestaoResponse
from app.services.service import processar_vetorizacao

async def controller_ingestao(payload: IngestaoRequest) -> IngestaoResponse:
    try:
        if not payload.manuais:
            raise HTTPException(status_code=400, detail="A lista de manuais está vazia.")
            
        # Roda o processamento pesado do LangChain em background
        total_chunks = await run_in_threadpool(processar_vetorizacao, payload.manuais)
        
        return IngestaoResponse(
            mensagem="Ingestão para o pgvector concluída com sucesso!",
            total_manuais=len(payload.manuais),
            total_blocos_gerados=total_chunks
        )
        
    except Exception as e:
        print(f"Erro na ingestão: {e}")
        raise HTTPException(status_code=500, detail=f"Falha na vetorização: {str(e)}")