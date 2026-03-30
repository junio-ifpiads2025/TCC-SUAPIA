from pydantic import BaseModel, HttpUrl
from typing import List

# --- Saída (Response) ---
class TopicoManual(BaseModel):
    topico: str
    texto: str
    links_imagens: List[str]

class ManualResponse(BaseModel):
    manual: str
    versao: str = "1.0"
    topicos: List[TopicoManual]

# --- Entrada (Request) ---
class LoteRequest(BaseModel):
    urls: List[HttpUrl]