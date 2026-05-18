from pydantic import BaseModel, HttpUrl, RootModel
from typing import Dict, List

# --- Saída (Response) ---
class TopicoManual(BaseModel):
    topico: str
    texto: str
    links_imagens: List[str]

class ManualResponse(BaseModel):
    manual: str
    versao: str = "1.0"
    topicos: List[TopicoManual]

class ManualLinksResponse(BaseModel):
    nome: str
    resultados: List[ManualResponse]

# --- Entrada (Request) ---
class LoteRequest(BaseModel):
    urls: List[HttpUrl]

class ManualLinksItem(BaseModel):
    urls: List[HttpUrl]

class LinksJsonRequest(RootModel[Dict[str, ManualLinksItem]]):
    pass