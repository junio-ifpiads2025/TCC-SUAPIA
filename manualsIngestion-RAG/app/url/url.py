from fastapi import APIRouter
from app.schemas.schema import IngestaoRequest, IngestaoResponse
from app.controllers.controller import controller_ingestao

router = APIRouter()

@router.post("/ingestao/lote", response_model=IngestaoResponse)
async def endpoint_ingestao(payload: IngestaoRequest):
    return await controller_ingestao(payload)