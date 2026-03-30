from typing import List
from fastapi import APIRouter
from app.schemas.schema import LoteRequest, ManualResponse
from app.controllers.controller import processar_lote_controller

router = APIRouter()

@router.post("/processar/lote", response_model=List[ManualResponse])
async def endpoint_processar_lote(payload: LoteRequest):
    # Passamos apenas a lista de urls contida no payload para o controller
    return await processar_lote_controller(payload.urls)