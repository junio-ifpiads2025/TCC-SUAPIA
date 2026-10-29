"""CLI de extração de manuais do SUAP.

Execute a partir da raiz do repositório:
    python -m pipeline.manualsExtraction.cli lote URL [URL ...]
    python -m pipeline.manualsExtraction.cli links-json links.json
"""
import argparse
import asyncio
import logging
import sys
from pathlib import Path

from pydantic import ValidationError

from pipeline.manualsExtraction.app.controllers.controller import (
    OUTPUT_DIR_PADRAO,
    processar_links_json,
    processar_lote,
)
from pipeline.manualsExtraction.app.schemas.schema import LinksJsonRequest


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="manualsExtraction",
        description="Baixa manuais HTML do SUAP (export BookStack) e gera um .md por página.",
    )
    parser.add_argument(
        "-o", "--output-dir", type=Path, default=OUTPUT_DIR_PADRAO,
        help=f"Diretório de saída dos .md (padrão: {OUTPUT_DIR_PADRAO})",
    )
    sub = parser.add_subparsers(dest="comando", required=True)

    lote = sub.add_parser("lote", help="Processa uma lista de URLs.")
    lote.add_argument("urls", nargs="+", help="URLs dos manuais.")

    links = sub.add_parser("links-json", help="Processa um links.json (manuais agrupados por nome).")
    links.add_argument("arquivo", type=Path, help="Caminho do links.json.")

    return parser


def main(argv=None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = _build_parser().parse_args(argv)

    if args.comando == "lote":
        _, ok = asyncio.run(processar_lote(args.urls, args.output_dir))
        total = len(args.urls)
    else:
        try:
            payload = LinksJsonRequest.model_validate_json(args.arquivo.read_text(encoding="utf-8"))
        except (OSError, ValidationError) as e:
            print(f"❌ Erro ao ler {args.arquivo}: {e}", file=sys.stderr)
            return 2
        _, ok = asyncio.run(processar_links_json(payload, args.output_dir))
        total = sum(len(i.urls) for i in payload.root.values())

    print(f"Concluído: {ok}/{total} URL(s) processada(s).")
    return 0 if ok == total else 1


if __name__ == "__main__":
    sys.exit(main())
