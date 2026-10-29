import json
import re
from pathlib import Path
from typing import Dict, List

from app.schemas.schema import ItemExtracaoManual, ManualResponse, TopicoManual

_FRONT_MATTER = re.compile(r"\A---\n(.*?)\n---\n", re.DOTALL)
_IMAGEM_MD = re.compile(r"!\[[^\]]*\]\(([^)\s]+)\)")
_H1_INICIAL = re.compile(r"\A\s*# .*\n")


def _valor_front_matter(bruto: str):
    """Valores textuais vêm entre aspas JSON; os demais (hash, data) ficam como string."""
    try:
        return json.loads(bruto)
    except ValueError:
        return bruto


def _ler_pagina_md(caminho: Path) -> tuple[str, TopicoManual] | None:
    conteudo = caminho.read_text(encoding="utf-8")
    achado = _FRONT_MATTER.match(conteudo)
    if not achado:
        return None

    meta = {}
    for linha in achado.group(1).splitlines():
        chave, sep, valor = linha.partition(":")
        if sep:
            meta[chave.strip()] = _valor_front_matter(valor.strip())

    manual, titulo = meta.get("manual"), meta.get("titulo")
    if not manual or not titulo:
        return None

    corpo = _H1_INICIAL.sub("", conteudo[achado.end():], count=1).strip()
    capitulo = meta.get("capitulo")
    # Capítulo entra no tópico: títulos repetidos em capítulos distintos não colidem nos IDs
    topico = f"{capitulo} > {titulo}" if capitulo else titulo

    return manual, TopicoManual(
        topico=topico,
        texto=corpo,
        links_imagens=list(dict.fromkeys(_IMAGEM_MD.findall(corpo))),
    )


def carregar_pasta_md(pasta: Path) -> List[ManualResponse]:
    """Lê os .md gerados pela extração (output/<data_hora>/<manual>/...) agrupando por manual."""
    manuais: Dict[str, ManualResponse] = {}
    for caminho in sorted(pasta.rglob("*.md")):
        pagina = _ler_pagina_md(caminho)
        if pagina is None:
            continue
        nome, topico = pagina
        manuais.setdefault(nome, ManualResponse(manual=nome, topicos=[])).topicos.append(topico)
    return list(manuais.values())


def carregar_arquivo_json(arquivo: Path) -> List[ManualResponse]:
    """Formato legado da extração: lista de {nome, resultados: [ManualResponse]}."""
    itens = [ItemExtracaoManual.model_validate(i) for i in json.loads(arquivo.read_text(encoding="utf-8"))]
    return [manual for item in itens for manual in item.resultados]
