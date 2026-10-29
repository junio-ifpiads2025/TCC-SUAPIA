"""CLI de ingestão de manuais no pgvector.

Execute a partir da raiz do repositório:
    python pipeline/manualsIngestion-RAG [CAMINHO]

CAMINHO é a pasta de .md gerada pela extração (output/<data_hora>) ou um .json legado.
Sem CAMINHO, usa a execução mais recente em pipeline/manualsExtraction/output.
"""
import argparse
import logging
import sys
from pathlib import Path
from typing import Optional

from app.controller.controller import ingerir_caminho

OUTPUT_EXTRACAO = Path(__file__).resolve().parents[1] / "manualsExtraction" / "output"


def _execucao_mais_recente() -> Optional[Path]:
    pastas = sorted((p for p in OUTPUT_EXTRACAO.glob("*") if p.is_dir()), key=lambda p: p.name)
    return pastas[-1] if pastas else None


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="manualsIngestion",
        description="Vetoriza os manuais extraídos e grava no pgvector (idempotente: reenviar substitui o manual).",
    )
    parser.add_argument(
        "caminho", nargs="?", type=Path,
        help="Pasta de .md da extração ou arquivo .json (padrão: execução mais recente em "
             f"{OUTPUT_EXTRACAO}).",
    )
    return parser


def main(argv=None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = _build_parser().parse_args(argv)

    caminho = args.caminho or _execucao_mais_recente()
    if caminho is None:
        print(f"❌ Nenhuma execução em {OUTPUT_EXTRACAO}. Rode a extração ou informe o caminho.", file=sys.stderr)
        return 2
    if not caminho.exists():
        print(f"❌ {caminho} não existe.", file=sys.stderr)
        return 2

    print(f"→ Ingerindo {caminho}")
    try:
        resposta = ingerir_caminho(caminho)
    except Exception as e:
        print(f"❌ Falha na ingestão: {e}", file=sys.stderr)
        return 1

    print(
        f"{resposta.mensagem} manuais={resposta.total_manuais} "
        f"blocos={resposta.total_blocos_gerados} ignorados={resposta.topicos_ignorados}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
