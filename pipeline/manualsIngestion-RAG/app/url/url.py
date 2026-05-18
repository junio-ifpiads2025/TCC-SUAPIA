from typing import List
from fastapi import APIRouter
from app.schemas.schema import IngestaoRequest, IngestaoResponse, ItemExtracaoManual
from app.controller.controller import controller_ingestao, controller_ingestao_arquivo_json

router = APIRouter()

@router.post("/ingestao/lote", response_model=IngestaoResponse)
async def endpoint_ingestao(payload: IngestaoRequest):
    return await controller_ingestao(payload)

@router.post("/ingestao/arquivo-json", response_model=IngestaoResponse)
async def endpoint_ingestao_arquivo_json(itens: List[ItemExtracaoManual]):
    return await controller_ingestao_arquivo_json(itens)