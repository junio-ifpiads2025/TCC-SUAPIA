import httpx
from bs4 import BeautifulSoup
from app.schemas.schema import TopicoManual, ManualResponse


async def download_html(url: str) -> str:
    """Faz o download assíncrono do HTML bruto de uma URL.

    A função usa um User-Agent de navegador para reduzir bloqueios simples
    e levanta exceção caso a resposta HTTP retorne erro (4xx/5xx).
    """

    # Simula um navegador real para evitar bloqueios por User-Agent genérico.
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }

    # Timeout alto para páginas longas e redirecionamentos habilitados.
    async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
        # Dispara a requisição GET para a URL informada.
        response = await client.get(url, headers=headers)
        # Se a resposta for de erro, interrompe o fluxo com exceção.
        response.raise_for_status()
        # Retorna o HTML como texto bruto para ser processado depois.
        return response.text


def extrair_dados_estilo_js(html_content: str) -> ManualResponse:
    """Extrai título, tópicos, texto e imagens a partir de um HTML de manual.

    A estratégia reproduz a navegação típica de um parser em JavaScript:
    - localiza links do sumário,
    - encontra o elemento âncora correspondente,
    - percorre os irmãos seguintes até detectar o início da próxima seção.
    """

    # Converte o HTML em árvore DOM navegável.
    soup = BeautifulSoup(html_content, 'html.parser')

    # Define um valor padrão para casos em que não exista título identificável.
    titulo_manual = "Manual sem Título"

    # Busca título usando prioridades comuns de marcação: h1, classe de título, <title>.
    titulo_tag = soup.select_one('h1, .page-title, title')
    if titulo_tag:
        # Extrai texto limpo do título removendo espaços nas bordas.
        titulo_manual = titulo_tag.get_text(strip=True)

    # Mapeia possíveis links de sumário para guiar a extração por seção.
    links = soup.select('.table-of-contents a, .page-content ul li a')

    # Lista final de tópicos extraídos que será retornada na resposta.
    conteudos = []

    for link in links:
        # Texto exibido no link (nome do tópico no sumário).
        texto_topico = link.get_text(strip=True)

        # Obtém o href; se não existir, usa string vazia para evitar None.
        href = link.get('href', '')

        # Normaliza o alvo removendo '#', ex.: '#instalacao' -> 'instalacao'.
        id_alvo = href.replace('#', '') if '#' in href else href

        # Procura no DOM o elemento cujo id corresponde ao link do sumário.
        alvo = soup.find(id=id_alvo)

        # Acumula os fragmentos textuais da seção atual.
        conteudo_texto = []

        # Acumula URLs de imagens associadas à seção (sem duplicação).
        imagens_da_secao = []

        if alvo:
            # Começa no próximo irmão do alvo (equivalente ao nextElementSibling do JS).
            proximo = alvo.find_next_sibling()

            while proximo:
                # Alguns documentos delimitam seções com ids page-* ou chapter-*.
                id_proximo = proximo.get('id', '')

                # Para quando detecta o início de uma nova seção.
                if id_proximo and (id_proximo.startswith('page-') or id_proximo.startswith('chapter-')):
                    break

                # Extrai texto visível do bloco atual e adiciona à seção.
                conteudo_texto.append(proximo.get_text(separator=" ", strip=True))

                # Coleta links para imagens que seguem o padrão "uploads/images".
                links_com_imagens = proximo.select('a[href*="uploads/images"]')
                for a in links_com_imagens:
                    url_direta = a.get('href')
                    if url_direta and url_direta not in imagens_da_secao:
                        imagens_da_secao.append(url_direta)

                # Coleta também imagens embutidas em tags <img>.
                imgs_soltas = proximo.select('img')
                for img in imgs_soltas:
                    src = img.get('src')
                    if src and src.startswith('http') and src not in imagens_da_secao:
                        imagens_da_secao.append(src)

                # Avança entre irmãos até atingir o limite da seção.
                proximo = proximo.find_next_sibling()

        # Junta todos os blocos em um único texto e normaliza espaços extras.
        texto_final = " ".join(conteudo_texto)
        texto_final = " ".join(texto_final.split())

        # Monta o objeto estruturado do tópico para resposta final.
        conteudos.append(
            TopicoManual(
                topico=texto_topico,
                texto=texto_final,
                links_imagens=imagens_da_secao
            )
        )

    # Retorna a estrutura completa contendo título do manual e seus tópicos.
    return ManualResponse(
        manual=titulo_manual,
        topicos=conteudos
    )