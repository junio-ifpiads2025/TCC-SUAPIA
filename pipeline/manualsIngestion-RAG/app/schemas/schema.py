from pydantic import BaseModel
from typing import List

class TopicoManual(BaseModel):
    topico: str
    texto: str
    links_imagens: List[str]

class ManualResponse(BaseModel):
    manual: str
    versao: str = "1.0"
    topicos: List[TopicoManual]

class IngestaoRequest(BaseModel):
    manuais: List[ManualResponse]

class ItemExtracaoManual(BaseModel):
    nome: str
    resultados: List[ManualResponse]

class IngestaoResponse(BaseModel):
    mensagem: str
    total_manuais: int
    total_blocos_gerados: int