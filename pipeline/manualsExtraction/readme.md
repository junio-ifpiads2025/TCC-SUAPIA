# 📖 CLI de Extração de Manuais (SUAP)

CLI que baixa o export HTML (BookStack) dos manuais do SUAP e gera **um arquivo `.md` por página**, pronto para RAG.

## Saída

```
output/<AAAAMMDD_HHMMSS>/<manual>/[<capitulo>/]<pagina>.md
```

Cada `.md` tem front matter YAML (`manual`, `capitulo`, `titulo`, `breadcrumb`, `url_origem`, `hash_conteudo`, `n_imagens`, `extraido_em`) seguido do conteúdo em Markdown (listas, tabelas, passos em negrito, avisos como `> Informação: ...`, imagens inline `![..](url)`).

Regras:
* Páginas com corpo < 50 caracteres e sem imagem são descartadas.
* Conteúdo repetido (mesmo `hash_conteudo`, ex.: "SUAP Edu" x "Projeto de Ensino") é gravado uma única vez.
* Sem estrutura reconhecida, a página inteira vira um único arquivo (com warning no log).
* Cada execução grava numa pasta nova com data/hora; execuções anteriores não são tocadas.

## Estrutura

* `cli.py` / `__main__.py`: entrada da CLI (argparse).
* `app/controllers/controller.py`: orquestração assíncrona, dedup e gravação dos `.md`.
* `app/services/service.py`: download (httpx), parsing (BeautifulSoup) e conversão (markdownify).
* `app/schemas/schema.py`: modelos Pydantic.

## Instalação

```bash
pip install -r pipeline/manualsExtraction/requirements.txt
```

## Uso (a partir da raiz do repositório)

```bash
# Lista de URLs de export -> output/<data_hora>/<manual>/...
python -m pipeline.manualsExtraction lote URL [URL ...]

# links.json agrupado por nome (dedup vale entre todos os manuais)
python -m pipeline.manualsExtraction links-json links.json

# Diretório de saída customizado
python -m pipeline.manualsExtraction -o ./saida links-json links.json
```

Código de saída: `0` tudo ok, `1` alguma URL falhou, `2` erro ao ler o `links.json`.
