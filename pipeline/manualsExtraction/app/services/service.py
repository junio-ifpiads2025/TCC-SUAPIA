import hashlib
import logging
import re
from typing import List, Optional

import httpx
from bs4 import BeautifulSoup, Tag
from markdownify import markdownify

from pipeline.manualsExtraction.app.schemas.schema import PaginaManual

logger = logging.getLogger("manualsExtraction")

# Corpo mínimo (em caracteres) para uma página valer a pena no RAG.
MIN_CORPO = 50

_ROTULOS_CALLOUT = {
    "info": "Informação",
    "warning": "Atenção",
    "danger": "Erro",
    "success": "Dica",
}


async def download_html(url: str) -> str:
    """Baixa o HTML bruto de uma URL; levanta exceção em 4xx/5xx."""
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
        response = await client.get(url, headers=headers)
        response.raise_for_status()
        return response.text


def _eh_inicio_secao(el: Tag) -> bool:
    """h1 que abre um capítulo ou uma página no export do BookStack."""
    if el.name != "h1":
        return False
    id_ = el.get("id", "")
    return id_.startswith(("page-", "chapter-"))


def _limpar_imagens(bloco: Tag) -> int:
    """Troca <img data:base64> pela URL pública (href do <a> pai) e devolve a contagem.

    O export embute as imagens em base64; sem URL pública a imagem é descartada.
    """
    total = 0
    for img in bloco.find_all("img"):
        src = img.get("src", "")
        pai = img.parent if img.parent and img.parent.name == "a" else None
        url = pai.get("href", "") if pai else ""
        if not url and src.startswith("http"):
            url = src
        if not url:
            img.decompose()
            continue
        alt = img.get("alt", "")
        if re.search(r"\.(png|jpe?g|gif|webp|svg)$", alt, re.I) or not alt:
            alt = "captura de tela"
        nova = bloco.new_tag("img", src=url, alt=alt)
        if pai:
            pai.replace_with(nova)
        else:
            img.replace_with(nova)
        total += 1
    return total


def _normalizar_blocos(bloco: Tag) -> None:
    """Ajusta marcações do BookStack para que o Markdown fique limpo."""
    for el in bloco.find_all(class_="callout"):
        tipo = next((c for c in el.get("class", []) if c in _ROTULOS_CALLOUT), "info")
        texto = el.get_text(" ", strip=True)
        if not texto:
            el.decompose()
            continue
        rotulo = f"{_ROTULOS_CALLOUT[tipo]}: "
        anterior = el.find_previous_sibling()
        if anterior is not None and anterior.name == "blockquote" and anterior.string.startswith(rotulo):
            # Callouts seguidos do mesmo tipo viram um único bloco.
            anterior.string = f"{anterior.string} {texto}"
            el.decompose()
            continue
        nova = bloco.new_tag("blockquote")
        nova.string = rotulo + texto
        el.replace_with(nova)

    # O BookStack usa h4-h6 como linha de "passo"; vira parágrafo em negrito.
    for el in bloco.find_all(["h4", "h5", "h6"]):
        texto = el.get_text(" ", strip=True)
        if not texto:
            el.decompose()
            continue
        nova = bloco.new_tag("p")
        forte = bloco.new_tag("strong")
        forte.string = texto
        nova.append(forte)
        el.replace_with(nova)

    for br in bloco.find_all("br"):
        br.replace_with(" ")


def _html_para_markdown(blocos: List[Tag]) -> tuple[str, int]:
    """Converte uma lista de elementos irmãos em Markdown. Retorna (md, n_imagens)."""
    cont = BeautifulSoup("<div></div>", "html.parser").div
    for b in blocos:
        cont.append(b.__copy__())
    n_imagens = _limpar_imagens(cont)
    _normalizar_blocos(cont)
    md = markdownify(str(cont), heading_style="ATX", bullets="-", strip=["span", "div", "a"])
    md = md.replace("\xa0", " ")
    md = re.sub(r"[ \t]+\n", "\n", md)
    md = re.sub(r"\n{3,}", "\n\n", md).strip()
    return md, n_imagens


def _texto_visivel(md: str) -> str:
    """Corpo sem imagens/markup, só para medir se há conteúdo."""
    sem_img = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", md)
    return re.sub(r"[#>*\-\s|]+", " ", sem_img).strip()


def hash_markdown(md: str) -> str:
    normalizado = " ".join(md.split()).lower()
    return hashlib.sha256(normalizado.encode("utf-8")).hexdigest()


def _ancora_ou_url(url: str, ancora: Optional[str]) -> str:
    return f"{url}#{ancora}" if ancora else url


def _mapa_capitulos(raiz: Tag) -> dict:
    """Mapeia id da página -> título do capítulo, lendo o sumário aninhado (ul.contents)."""
    topo = raiz.select_one("ul.contents")
    mapa: dict = {}
    if topo is None:
        return mapa
    capitulo = None
    for filho in topo.find_all(recursive=False):
        if filho.name == "li":
            a = filho.find("a")
            href = a.get("href", "") if a else ""
            capitulo = a.get_text(" ", strip=True) if href.startswith("#chapter-") else None
        elif filho.name == "ul" and capitulo:
            for a in filho.select("a[href^='#page-']"):
                mapa[a["href"][1:]] = capitulo
    return mapa


def extrair_paginas(html_content: str, url: str, nome_manual: Optional[str] = None) -> List[PaginaManual]:
    """Extrai páginas em Markdown de um export HTML do BookStack (livro, capítulo ou página)."""
    soup = BeautifulSoup(html_content, "html.parser")
    raiz = soup.select_one(".page-content")
    if raiz is None:
        logger.warning("Sem .page-content em %s; usando <body> inteiro.", url)
        raiz = soup.body or soup

    titulo_doc = soup.title.get_text(strip=True) if soup.title else "Manual sem Título"
    manual = nome_manual or titulo_doc

    filhos = [c for c in raiz.find_all(recursive=False)]
    # Export de página avulsa: o conteúdo fica num único <div> sem classe.
    if not any(_eh_inicio_secao(c) for c in filhos):
        interno = next((c for c in filhos if c.name == "div" and c.find("h1")), None)
        if interno is not None:
            filhos = [c for c in interno.find_all(recursive=False)]

    # Divide em seções: cada h1 page-/chapter- abre uma; sem nenhuma, a página é uma seção só.
    secoes = []  # (tipo, titulo, ancora, blocos)
    atual = None
    prefixo: List[Tag] = []
    for el in filhos:
        if _eh_inicio_secao(el):
            id_ = el["id"]
            atual = ("chapter" if id_.startswith("chapter-") else "page",
                     el.get_text(" ", strip=True), id_, [])
            secoes.append(atual)
            continue
        if "page-break" in (el.get("class") or []) or "chapter-hint" in (el.get("class") or []) \
                or "contents" in (el.get("class") or []) or "text-muted" in (el.get("class") or []) \
                or el.name == "hr":
            continue
        if atual is None:
            prefixo.append(el)
        else:
            atual[3].append(el)

    if not secoes:
        # Página avulsa (h1#bkmrk-page-title) ou HTML fora do padrão: fallback = página inteira.
        h1 = next((e for e in prefixo if e.name == "h1"), None)
        titulo = h1.get_text(" ", strip=True) if h1 else titulo_doc
        corpo = [e for e in prefixo if e is not h1]
        if h1 is None:
            logger.warning("Sem h1 em %s; usando <title> e conteúdo inteiro como um tópico.", url)
        secoes.append(("page", titulo, None, corpo))

    capitulo_de = _mapa_capitulos(raiz)
    if "/chapter/" in url:
        h1_cap = next((e for e in raiz.find_all("h1", recursive=False) if not e.get("id")), None)
        capitulo_padrao = h1_cap.get_text(" ", strip=True) if h1_cap else None
    else:
        capitulo_padrao = None

    paginas: List[PaginaManual] = []
    for tipo, titulo, ancora, blocos in secoes:
        md, n_img = _html_para_markdown(blocos)
        corpo_vazio = len(_texto_visivel(md)) < MIN_CORPO
        if corpo_vazio and n_img == 0:
            logger.info("Descartado (corpo < %d chars): %s > %s", MIN_CORPO, manual, titulo)
            continue
        paginas.append(
            PaginaManual(
                manual=manual,
                capitulo=None if tipo == "chapter" else capitulo_de.get(ancora, capitulo_padrao),
                titulo=titulo,
                url_origem=_ancora_ou_url(url, ancora),
                markdown=md,
                hash_conteudo=hash_markdown(md),
                n_imagens=n_img,
            )
        )

    if not paginas:
        logger.warning("Nenhuma página com conteúdo extraída de %s", url)
    return paginas
