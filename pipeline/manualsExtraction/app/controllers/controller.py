import asyncio
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from pipeline.manualsExtraction.app.schemas.schema import LinksJsonRequest, PaginaManual
from pipeline.manualsExtraction.app.services.service import download_html, extrair_paginas

OUTPUT_DIR_PADRAO = Path(__file__).resolve().parents[2] / "output"


def _slug(texto: str) -> str:
    texto = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    texto = re.sub(r"[^a-zA-Z0-9]+", "-", texto).strip("-").lower()
    return texto[:80] or "sem-titulo"


async def processar_url_unica(url: str, nome_manual: Optional[str] = None) -> List[PaginaManual]:
    html_content = await download_html(url)
    return await asyncio.to_thread(extrair_paginas, html_content, url, nome_manual)


async def _processar_urls(urls: List[str], nome_manual: Optional[str] = None) -> Tuple[List[PaginaManual], int]:
    """Processa URLs em paralelo; falhas são logadas e ignoradas. Retorna (páginas, urls_ok)."""
    resultados = await asyncio.gather(*(processar_url_unica(u, nome_manual) for u in urls), return_exceptions=True)

    paginas: List[PaginaManual] = []
    ok = 0
    for url, resultado in zip(urls, resultados):
        if isinstance(resultado, Exception):
            print(f"❌ Falha na URL {url} -> {resultado}")
        else:
            ok += 1
            paginas.extend(resultado)
    return paginas, ok


def _front_matter(p: PaginaManual) -> str:
    def q(v: str) -> str:
        return '"' + v.replace("\\", "\\\\").replace('"', '\\"') + '"'

    linhas = [
        "---",
        f"manual: {q(p.manual)}",
        f"capitulo: {q(p.capitulo)}" if p.capitulo else "capitulo: null",
        f"titulo: {q(p.titulo)}",
        f"breadcrumb: {q(' > '.join(p.breadcrumb))}",
        f"url_origem: {q(p.url_origem)}",
        f"hash_conteudo: {p.hash_conteudo}",
        f"n_imagens: {p.n_imagens}",
        f"extraido_em: {datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}",
        "---",
    ]
    return "\n".join(linhas)


def _caminho(p: PaginaManual, output_dir: Path, usados: set) -> Path:
    pasta = output_dir / _slug(p.manual)
    if p.capitulo:
        pasta = pasta / _slug(p.capitulo)
    base = _slug(p.titulo)
    caminho = pasta / f"{base}.md"
    n = 2
    while caminho in usados:
        caminho = pasta / f"{base}-{n}.md"
        n += 1
    usados.add(caminho)
    return caminho


def _salvar_paginas(paginas: List[PaginaManual], output_dir: Path) -> Dict[str, int]:
    """Grava um .md por página, pulando conteúdo repetido (mesmo hash)."""
    output_dir = output_dir / datetime.now().strftime("%Y%m%d_%H%M%S")
    vistos: Dict[str, Path] = {}
    usados: set = set()
    gravados = duplicados = 0

    for p in paginas:
        if p.hash_conteudo in vistos:
            duplicados += 1
            print(f"⏭️  Duplicado ignorado: {' > '.join(p.breadcrumb)} (igual a {vistos[p.hash_conteudo].name})")
            continue
        caminho = _caminho(p, output_dir, usados)
        caminho.parent.mkdir(parents=True, exist_ok=True)
        corpo = f"{_front_matter(p)}\n\n# {p.titulo}\n\n{p.markdown}\n"
        caminho.write_text(corpo, encoding="utf-8")
        vistos[p.hash_conteudo] = caminho
        gravados += 1

    print(f"✅ {gravados} arquivo(s) .md em {output_dir} ({duplicados} duplicado(s) ignorado(s))")
    return {"gravados": gravados, "duplicados": duplicados}


async def processar_lote(urls: List[str], output_dir: Path = OUTPUT_DIR_PADRAO) -> Tuple[List[PaginaManual], int]:
    paginas, ok = await _processar_urls(urls)
    if paginas:
        _salvar_paginas(paginas, output_dir)
    return paginas, ok


async def processar_links_json(payload: LinksJsonRequest, output_dir: Path = OUTPUT_DIR_PADRAO) -> Tuple[List[PaginaManual], int]:
    """Processa o links.json; o dedup por hash vale entre todos os manuais."""
    todas: List[PaginaManual] = []
    ok_total = 0

    for nome_manual, item in payload.root.items():
        urls = [str(url) for url in item.urls]
        print(f"📄 Processando manual: {nome_manual} ({len(urls)} URL(s))")
        paginas, ok = await _processar_urls(urls, nome_manual)
        todas.extend(paginas)
        ok_total += ok

    if todas:
        _salvar_paginas(todas, output_dir)
    return todas, ok_total
