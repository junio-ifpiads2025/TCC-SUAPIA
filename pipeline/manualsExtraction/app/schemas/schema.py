from pydantic import BaseModel, HttpUrl, RootModel
from typing import Dict, List, Optional

# --- Saída ---
class PaginaManual(BaseModel):
    manual: str
    capitulo: Optional[str] = None
    titulo: str
    url_origem: str
    markdown: str
    hash_conteudo: str
    n_imagens: int = 0

    @property
    def breadcrumb(self) -> List[str]:
        return [p for p in (self.manual, self.capitulo, self.titulo) if p]

# --- Entrada (links.json) ---
class ManualLinksItem(BaseModel):
    urls: List[HttpUrl]

class LinksJsonRequest(RootModel[Dict[str, ManualLinksItem]]):
    pass
