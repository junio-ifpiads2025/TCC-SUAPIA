from typing import List
from fastapi import APIRouter
from app.schemas.schema import LinksJsonRequest, LoteRequest, ManualLinksResponse, ManualResponse
from app.controllers.controller import processar_links_json_controller, processar_lote_controller

router = APIRouter()

@router.post("/processar/lote", response_model=List[ManualResponse])
async def endpoint_processar_lote(payload: LoteRequest):
    return await processar_lote_controller(payload.urls)

@router.post("/processar/links-json", response_model=List[ManualLinksResponse])
async def endpoint_processar_links_json(payload: LinksJsonRequest):
    """Recebe o links.json com manuais agrupados por nome e processa todas as URLs."""
    return await processar_links_json_controller(payload)