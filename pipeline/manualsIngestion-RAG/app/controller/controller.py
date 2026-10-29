from pathlib import Path

from app.schemas.schema import IngestaoResponse
from app.services.loader import carregar_arquivo_json, carregar_pasta_md
from app.services.service import processar_vetorizacao


def ingerir_caminho(caminho: Path) -> IngestaoResponse:
    """Ingere uma pasta de .md (saída da extração) ou um .json legado no pgvector."""
    if caminho.is_dir():
        manuais = carregar_pasta_md(caminho)
    else:
        manuais = carregar_arquivo_json(caminho)

    if not manuais:
        raise ValueError(f"Nenhum manual encontrado em {caminho}.")

    resultado = processar_vetorizacao(manuais)
    return IngestaoResponse(
        mensagem="Ingestão para o pgvector concluída com sucesso!",
        total_manuais=len(manuais),
        total_blocos_gerados=resultado["blocos"],
        topicos_ignorados=resultado["ignorados"],
    )
