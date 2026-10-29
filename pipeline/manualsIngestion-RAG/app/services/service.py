import hashlib
import os
import uuid
from functools import lru_cache
from typing import Dict, List, Tuple

from dotenv import load_dotenv
from langchain_core.documents import Document
from langchain_openai import OpenAIEmbeddings
from langchain_postgres import PGVector
from langchain_text_splitters import RecursiveCharacterTextSplitter
from sqlalchemy import text

from app.schemas.schema import ManualResponse

load_dotenv()

# Pegando as variáveis do .env com valores padrão de fallback
PG_CONNECTION = os.getenv(
    "PGVECTOR_CONNECTION_STRING",
    "postgresql+psycopg://admin:adminpassword@localhost:5432/vetordatabase"
)
NOME_COLECAO = os.getenv("PGVECTOR_COLLECTION", "manuais_suap_ifpi")
MODELO_EMBEDDING = os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")
CHUNK_SIZE = int(os.getenv("INGESTAO_CHUNK_SIZE", "800"))
CHUNK_OVERLAP = int(os.getenv("INGESTAO_CHUNK_OVERLAP", "150"))
TAMANHO_LOTE = int(os.getenv("INGESTAO_TAMANHO_LOTE", "100"))

# Namespace fixo: mesmo conteúdo gera sempre o mesmo ID (reingestão = upsert)
_NAMESPACE_IDS = uuid.UUID("6f1c2f0e-52a4-4d57-9a43-0c4a3e5b1d11")


@lru_cache(maxsize=1)
def _get_vector_store() -> PGVector:
    return PGVector(
        embeddings=OpenAIEmbeddings(model=MODELO_EMBEDDING),
        collection_name=NOME_COLECAO,
        connection=PG_CONNECTION,
        use_jsonb=True,
    )


def _montar_documentos(manuais: List[ManualResponse]) -> Tuple[List[Document], int]:
    """Gera um Document por tópico, descartando textos vazios e tópicos duplicados."""
    documentos: List[Document] = []
    vistos = set()
    ignorados = 0

    for manual in manuais:
        for topico in manual.topicos:
            texto = topico.texto.strip()
            if not texto:
                ignorados += 1
                continue

            chave = hashlib.sha256(
                f"{manual.manual}\x00{manual.versao}\x00{topico.topico}\x00{texto}".encode()
            ).hexdigest()
            if chave in vistos:
                ignorados += 1
                continue
            vistos.add(chave)

            documentos.append(Document(
                page_content=texto,
                metadata={
                    "manual": manual.manual,
                    "versao": manual.versao,
                    "topico": topico.topico,
                    "links_imagens": topico.links_imagens,
                },
            ))

    return documentos, ignorados


def _dividir_em_blocos(documentos: List[Document]) -> List[Document]:
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
        separators=["\n\n", "\n", ". ", "; ", " ", ""],
    )
    blocos = splitter.split_documents(documentos)

    # Índice do bloco dentro do tópico: base do ID determinístico
    contadores: Dict[Tuple[str, str, str], int] = {}
    for bloco in blocos:
        m = bloco.metadata
        chave = (m["manual"], m["versao"], m["topico"])
        indice = contadores.get(chave, 0)
        contadores[chave] = indice + 1

        bloco.metadata["chunk_index"] = indice
        bloco.id = str(uuid.uuid5(_NAMESPACE_IDS, "|".join((*chave, str(indice)))))
        bloco.page_content = (
            f"Manual: {m['manual']}\n"
            f"Tópico: {m['topico']}\n"
            f"Conteúdo: {bloco.page_content}"
        )

    total_por_topico = contadores
    for bloco in blocos:
        m = bloco.metadata
        bloco.metadata["total_chunks"] = total_por_topico[(m["manual"], m["versao"], m["topico"])]

    return blocos


def _remover_blocos_antigos(store: PGVector, manuais: List[ManualResponse]) -> None:
    """Remove chunks anteriores dos manuais enviados, evitando órfãos quando o texto encolhe."""
    nomes = sorted({m.manual for m in manuais})
    with store.session_maker() as session:
        session.execute(
            text(
                "DELETE FROM langchain_pg_embedding "
                "WHERE collection_id = (SELECT uuid FROM langchain_pg_collection WHERE name = :colecao) "
                "AND cmetadata->>'manual' = ANY(:nomes)"
            ),
            {"colecao": NOME_COLECAO, "nomes": nomes},
        )
        session.commit()


def processar_vetorizacao(manuais: List[ManualResponse]) -> Dict[str, int]:
    """Converte manuais em chunks e grava no pgvector de forma idempotente.

    Reenviar o mesmo manual substitui seus chunks em vez de duplicá-los.
    """
    documentos, ignorados = _montar_documentos(manuais)
    if not documentos:
        return {"blocos": 0, "ignorados": ignorados}

    blocos = _dividir_em_blocos(documentos)
    store = _get_vector_store()

    # Só limpa manuais que de fato têm conteúdo novo para gravar
    com_conteudo = {d.metadata["manual"] for d in documentos}
    _remover_blocos_antigos(store, [m for m in manuais if m.manual in com_conteudo])

    for i in range(0, len(blocos), TAMANHO_LOTE):
        lote = blocos[i:i + TAMANHO_LOTE]
        store.add_documents(lote, ids=[b.id for b in lote])

    return {"blocos": len(blocos), "ignorados": ignorados}
