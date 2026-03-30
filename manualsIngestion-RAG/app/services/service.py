import os
from typing import List
from dotenv import load_dotenv
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_openai import OpenAIEmbeddings
from langchain_qdrant import QdrantVectorStore
from app.schemas.schema import ManualResponse

load_dotenv()

# Pegando as variáveis do .env com valores padrão de fallback
URL_QDRANT = os.getenv("QDRANT_URL", "http://localhost:6333")
NOME_COLECAO = os.getenv("QDRANT_COLLECTION", "manuais_suap_ifpi")
MODELO_EMBEDDING = os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")

def processar_vetorizacao(manuais: List[ManualResponse]) -> int:
    """Converte a lista de manuais em documentos vetoriais e envia para o Qdrant."""
    documentos = []
    
    for manual in manuais:
        for topico in manual.topicos:
            texto = topico.texto.strip()
            if not texto:
                continue 
                
            doc = Document(
                page_content=texto,
                metadata={
                    "manual": manual.manual,
                    "versao": manual.versao,
                    "topico": topico.topico,
                    "links_imagens": topico.links_imagens
                }
            )
            documentos.append(doc)

    if not documentos:
        return 0

    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=800, 
        chunk_overlap=150,
        separators=["\n\n", "\n", ".", " ", ""]
    )
    blocos = text_splitter.split_documents(documentos)

    # Utilizando o modelo vindo do .env
    embeddings = OpenAIEmbeddings(model=MODELO_EMBEDDING)
    
    QdrantVectorStore.from_documents(
        blocos,
        embeddings,
        url=URL_QDRANT,
        prefer_grpc=False,
        collection_name=NOME_COLECAO
    )
    
    return len(blocos)