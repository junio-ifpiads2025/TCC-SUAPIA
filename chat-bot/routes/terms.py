"""
Endpoint público que expõe o Termo de Compromisso de Uso do SUAP-IA.

Endpoints:
  GET /terms       — retorna metadados + conteúdo em Markdown (JSON).
  GET /terms/view  — retorna página HTML legível pelo usuário.
"""

from fastapi import APIRouter
from fastapi.responses import HTMLResponse, JSONResponse

from config import AGENT_NAME

router = APIRouter(prefix="/terms", tags=["terms"])

TERMS_VERSION = "1.0"
TERMS_EFFECTIVE_DATE = "2026-05-22"

TERMS_CONTENT = """\
# Termo de Compromisso de Uso Responsável — Projeto SUAPIA

## PREÂMBULO

O presente Termo regula o uso do **Projeto SUAPIA** e de seu agente de inteligência artificial \
**Sidi**, chatbot de assistência institucional desenvolvido como Trabalho de Conclusão de Curso \
no Instituto Federal de Educação, Ciência e Tecnologia do Piauí (IFPI). O SUAPIA utiliza \
tecnologias de IA generativa com arquitetura RAG (*Retrieval-Augmented Generation*) e integração \
com a **API oficial do SUAP**, acessível via WhatsApp por meio do agente Sidi.

O uso do sistema implica a **aceitação integral** das condições aqui estabelecidas, em \
conformidade com:

- A **Lei Geral de Proteção de Dados Pessoais — LGPD** (Lei nº 13.709/2018);
- A **Resolução Normativa CONSUP/OSUPCOL/REI/IFPI Nº 251/2025**, que integra a IA generativa \
às diretrizes de segurança da informação institucional;
- As **normas de segurança cibernética** do Governo Federal aplicáveis a instituições públicas \
de ensino.

---

## CLÁUSULA 1 — DO OBJETO E IDENTIFICAÇÃO DO SISTEMA

**1.1.** Este Termo estabelece os direitos, deveres e responsabilidades do **USUÁRIO** no uso \
do Projeto SUAPIA e do agente Sidi, bem como as obrigações do **RESPONSÁVEL PELO SISTEMA** \
quanto ao tratamento de dados pessoais e à segurança das informações.

**1.2.** Para fins deste Termo, adotam-se as seguintes definições:

- **SUAPIA**: nome do projeto de pesquisa e desenvolvimento do TCC, que engloba toda a \
arquitetura técnica do sistema (RAG, integração com WhatsApp, banco de dados e API do SUAP);
- **Sidi**: nome do agente de IA com o qual o usuário interage diretamente pelo WhatsApp — \
é a "voz" do SUAPIA;
- **SUAP**: Sistema Unificado de Administração Pública, plataforma institucional do IFPI que \
centraliza dados acadêmicos e administrativos.

**1.3.** O SUAPIA/Sidi destina-se exclusivamente a auxiliar a comunidade acadêmica do IFPI na \
obtenção de informações institucionais, como datas acadêmicas, normas, frequências, notas e \
demais dados disponibilizados pelo SUAP.

---

## CLÁUSULA 2 — DA API OFICIAL DO SUAP E DO TRATAMENTO DAS CREDENCIAIS

**2.1. Uso da API Oficial**

O SUAPIA utiliza exclusivamente a **API REST oficial do SUAP**, criada e mantida pela DIGTI \
(Diretoria de Gestão de Tecnologia da Informação) do IFRN e disponível para toda a Rede Federal. \
Essa interface foi desenvolvida para apoiar projetos de ensino, pesquisa e extensão, permitindo \
que aplicações autorizadas consultem dados do SUAP de forma segura e controlada.

**2.2. Como funciona a autenticação (JWT)**

O fluxo de autenticação do SUAPIA segue o padrão de mercado **JWT (JSON Web Token)**:

1. O usuário informa sua **matrícula e senha do SUAP** no formulário de login do SUAPIA;
2. Essas credenciais são enviadas diretamente ao servidor oficial do SUAP via HTTPS, \
sem que o SUAPIA as armazene em nenhum momento;
3. O SUAP valida as credenciais e, em caso de sucesso, devolve um **token de acesso \
temporário** (JWT) — semelhante a um crachá eletrônico com prazo de validade;
4. O SUAPIA armazena esse token **somente na memória temporária (Redis)**, com tempo \
de expiração definido pelo próprio SUAP;
5. A cada consulta do usuário, o Sidi utiliza esse token para buscar os dados na API \
do SUAP em nome do usuário;
6. Quando o token expira, a sessão é encerrada automaticamente e o usuário precisa \
fazer login novamente.

**2.3. Garantia de não armazenamento de credenciais**

> **Declaração expressa:** A matrícula e a senha informadas pelo usuário no formulário de \
login **NUNCA são gravadas no banco de dados do SUAPIA**, em nenhuma hipótese. Esses dados \
trafegam exclusivamente entre o navegador do usuário e o servidor oficial do SUAP por \
conexão criptografada (HTTPS), sendo descartados imediatamente após a obtenção do token.

O banco de dados do SUAPIA armazena **apenas**:

| Dado | O que é | Por que é armazenado |
|---|---|---|
| Número de telefone (WhatsApp) | Identificador de sessão | Roteamento de mensagens |
| Matrícula SUAP | Número de matrícula | Vínculo de identidade para auditoria |
| Data/hora do aceite deste Termo | Timestamp de consentimento | Exigência LGPD Art. 8º §5º |

O **token JWT** e a **senha** são armazenados exclusivamente de forma volátil (Redis, sem \
persistência em disco) e nunca no banco de dados relacional.

---

## CLÁUSULA 3 — DO TRATAMENTO DE DADOS PESSOAIS (LGPD)

**3.1. Base Legal**

O tratamento de dados pessoais pelo SUAPIA fundamenta-se no **Art. 7º, incisos II e III da \
LGPD** — execução de procedimento relacionado ao uso de serviço ao qual o titular aderiu \
voluntariamente, e cumprimento de obrigação legal pelo controlador.

**3.2. Princípios Observados (Art. 6º, LGPD)**

- **Finalidade**: coleta exclusiva para as finalidades declaradas neste Termo;
- **Adequação**: compatibilidade com as finalidades informadas ao titular;
- **Necessidade**: limitação ao mínimo necessário para a prestação do serviço;
- **Transparência**: garantia de informações claras ao titular sobre o tratamento;
- **Segurança**: medidas técnicas e administrativas para proteção dos dados;
- **Prevenção**: adoção de medidas para prevenir danos ao titular;
- **Não discriminação**: vedação do uso dos dados para fins discriminatórios.

**3.3. Dados Sensíveis**

O sistema **não coleta nem trata dados sensíveis** conforme definidos no Art. 11 da LGPD \
(origem racial, convicção religiosa, opinião política, saúde, dados biométricos, etc.). \
Caso o usuário os forneça espontaneamente, não serão armazenados.

**3.4. Compartilhamento de Dados**

Os dados tratados pelo SUAPIA **não serão compartilhados com terceiros** para fins comerciais. \
O acesso ao SUAP ocorre mediante autenticação institucional, sob os termos do próprio sistema \
e da API oficial do SUAP.

**3.5. Retenção e Exclusão**

- O histórico de conversas é mantido apenas durante a sessão ativa (Redis com TTL);
- Credenciais (senha) não são retidas em nenhum momento;
- O token JWT é descartado automaticamente ao expirar;
- O titular poderá solicitar a exclusão dos demais dados a qualquer momento.

**3.6. Direitos do Titular (Art. 18, LGPD)**

O usuário, na qualidade de titular dos dados, tem direito a:

- Confirmar a existência de tratamento de seus dados;
- Acessar os dados tratados;
- Corrigir dados incompletos, inexatos ou desatualizados;
- Solicitar a anonimização, bloqueio ou eliminação de dados desnecessários;
- Revogar o consentimento a qualquer momento;
- Opor-se ao tratamento realizado em descumprimento da LGPD.

---

## CLÁUSULA 4 — DAS RESPONSABILIDADES DO USUÁRIO

Em conformidade com as **diretrizes de uso responsável de IA do IFPI**, o usuário se compromete a:

**4.1.** Utilizar o sistema exclusivamente para fins **lícitos e institucionais**, vedado o uso \
para atividades que contrariem as normas do IFPI ou a legislação vigente;

**4.2.** **Não inserir** nos campos de interação do Sidi dados sigilosos, senhas de terceiros, \
tokens de acesso ou quaisquer informações que possam comprometer a segurança institucional;

**4.3.** **Não compartilhar** suas credenciais de acesso ao SUAP com terceiros, tampouco \
permitir que terceiros utilizem sua conta no sistema;

**4.4.** **Revisar criticamente** as respostas geradas pela IA, reconhecendo que o sistema pode \
produzir informações imprecisas ("alucinações") e que a responsabilidade pela tomada de decisões \
permanece com o usuário;

**4.5.** **Declarar** o uso da IA quando as informações obtidas pelo Sidi forem utilizadas em \
trabalhos acadêmicos, relatórios ou documentos oficiais, em conformidade com as normas de \
integridade acadêmica do IFPI;

**4.6.** **Comunicar imediatamente** ao responsável pelo sistema qualquer comportamento irregular, \
falha de segurança, exposição indevida de dados ou resposta inadequada gerada pelo Sidi;

**4.7.** **Não utilizar** o sistema para fins de automação abusiva, spam, sobrecarga intencional \
dos serviços ou qualquer prática que prejudique outros usuários.

---

## CLÁUSULA 5 — DAS RESPONSABILIDADES DO RESPONSÁVEL PELO SISTEMA

O responsável pelo desenvolvimento e manutenção do SUAPIA compromete-se a:

**5.1.** Adotar medidas técnicas e organizacionais adequadas para garantir a **disponibilidade, \
integridade e confidencialidade** das informações, conforme a tríade de segurança do IFPI;

**5.2.** Garantir que o sistema opere em conformidade com a **LGPD** e com as diretrizes da \
Resolução Normativa CONSUP/OSUPCOL/REI/IFPI Nº 251/2025;

**5.3.** Utilizar exclusivamente a **API oficial do SUAP** para acesso a dados institucionais, \
não recorrendo a técnicas de raspagem de dados (*web scraping*) ou acessos não autorizados;

**5.4.** **Não armazenar** credenciais de acesso do usuário (matrícula/senha) em nenhum \
repositório persistente — banco de dados, arquivos de log ou sistemas de monitoramento;

**5.5.** Notificar a Autoridade Nacional de Proteção de Dados (ANPD) e os titulares afetados em \
caso de **incidente de segurança**, nos termos do Art. 48 da LGPD;

**5.6.** Realizar **revisões periódicas** das respostas geradas pelo Sidi, aprimorando a base \
de conhecimento para reduzir imprecisões;

**5.7.** Disponibilizar canal de atendimento para exercício dos **direitos dos titulares** \
previstos na LGPD.

---

## CLÁUSULA 6 — DOS LIMITES DO SISTEMA

**6.1.** O Sidi é uma ferramenta de **apoio informacional** e não substitui orientação \
presencial de professores, coordenadores ou servidores do IFPI.

**6.2.** As respostas geradas pela IA têm caráter **informativo e auxiliar**, não constituindo \
ato administrativo, decisão oficial ou compromisso institucional.

**6.3.** Em caso de divergência entre a resposta do Sidi e a informação oficial do SUAP ou de \
setores competentes do IFPI, **prevalece a fonte oficial**.

---

## CLÁUSULA 7 — DAS SANÇÕES

**7.1.** O uso do sistema em desacordo com este Termo poderá acarretar:

- Suspensão ou bloqueio imediato do acesso ao SUAPIA/Sidi;
- Comunicação às instâncias competentes do IFPI para apuração disciplinar;
- Responsabilização civil, administrativa e penal, conforme a legislação aplicável, incluindo \
o Art. 42 da LGPD (reparação de danos causados pelo tratamento indevido de dados).

---

## CLÁUSULA 8 — DAS DISPOSIÇÕES FINAIS

**8.1.** Este Termo poderá ser atualizado a qualquer tempo para adequação a novas normas legais \
ou institucionais, sendo o usuário notificado das alterações.

**8.2.** O foro competente para dirimir quaisquer questões oriundas deste Termo é o da \
**Comarca de Teresina/PI**, em conformidade com a sede do IFPI.

**8.3.** Os casos omissos serão resolvidos com base na LGPD, no Marco Civil da Internet \
(Lei nº 12.965/2014) e nas normas institucionais do IFPI vigentes.

---

*Documento elaborado em conformidade com a Lei nº 13.709/2018 (LGPD) e a \
Resolução Normativa CONSUP/OSUPCOL/REI/IFPI Nº 251/2025.*
"""


@router.get("", response_class=JSONResponse)
async def get_terms():
    """Retorna metadados e conteúdo do Termo de Compromisso de Uso em formato JSON."""
    return {
        "version": TERMS_VERSION,
        "effective_date": TERMS_EFFECTIVE_DATE,
        "title": "Termo de Compromisso de Uso Responsável — Projeto SUAPIA (Agente Sidi)",
        "format": "markdown",
        "content": TERMS_CONTENT,
    }


@router.get("/view", response_class=HTMLResponse)
async def view_terms():
    """Renderiza o Termo de Compromisso de Uso como página HTML legível."""
    paragraphs = []
    in_table = False
    for line in TERMS_CONTENT.splitlines():
        is_table_row = line.startswith("| ") and not line.startswith("|---")
        is_separator = line.startswith("|---")

        if is_separator:
            continue

        if is_table_row:
            if not in_table:
                paragraphs.append('<div class="table-wrap"><table>')
                in_table = True
            cells = "</td><td>".join(c.strip() for c in line.split("|")[1:-1])
            paragraphs.append(f"<tr><td>{cells}</td></tr>")
            continue

        if in_table:
            paragraphs.append("</table></div>")
            in_table = False

        if line.startswith("# "):
            paragraphs.append(f"<h1>{line[2:]}</h1>")
        elif line.startswith("## "):
            paragraphs.append(f"<h2>{line[3:]}</h2>")
        elif line.startswith("---"):
            paragraphs.append("<hr/>")
        elif line.startswith("- "):
            paragraphs.append(f"<li>{line[2:]}</li>")
        elif line.strip() == "":
            paragraphs.append("<br/>")
        else:
            paragraphs.append(f"<p>{line}</p>")

    if in_table:
        paragraphs.append("</table></div>")

    body = "\n".join(paragraphs)

    return f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1.0"/>
  <title>Termo de Uso — SUAPIA / {AGENT_NAME}</title>
  <style>
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
      background: #f0f4f8;
      color: #1f2937;
      padding: 1.5rem 1rem;
    }}
    .container {{
      max-width: 800px;
      margin: 0 auto;
      background: #fff;
      border-radius: 12px;
      box-shadow: 0 4px 20px rgba(0,0,0,.08);
      padding: 2.5rem 3rem;
    }}
    h1 {{ font-size: 1.5rem; color: #1a56db; margin-bottom: 1rem; }}
    h2 {{ font-size: 1.1rem; color: #1e40af; margin: 1.5rem 0 .5rem; }}
    p  {{ font-size: .93rem; line-height: 1.7; margin-bottom: .5rem; }}
    li {{ font-size: .93rem; line-height: 1.7; margin-left: 1.5rem; list-style: disc; }}
    hr {{ border: none; border-top: 1px solid #e5e7eb; margin: 1.5rem 0; }}
    .table-wrap {{ overflow-x: auto; -webkit-overflow-scrolling: touch; margin: .75rem 0; }}
    table {{ border-collapse: collapse; width: 100%; min-width: 360px; font-size: .9rem; }}
    td {{ border: 1px solid #d1d5db; padding: .5rem .75rem; }}
    tr:first-child td {{ background: #f3f4f6; font-weight: 600; }}
    .badge {{
      display: inline-block;
      background: #dbeafe;
      color: #1e40af;
      font-size: .75rem;
      font-weight: 600;
      padding: .2rem .6rem;
      border-radius: 999px;
      margin-bottom: 1rem;
    }}
    .footer {{ margin-top: 2rem; font-size: .8rem; color: #6b7280; text-align: center; }}
    @media (max-width: 600px) {{
      .container {{ padding: 1.5rem 1.25rem; border-radius: 8px; }}
      h1 {{ font-size: 1.25rem; }}
      h2 {{ font-size: 1rem; }}
    }}
  </style>
</head>
<body>
  <div class="container">
    <span class="badge">Versão {TERMS_VERSION} &nbsp;·&nbsp; Em vigor desde {TERMS_EFFECTIVE_DATE}</span>
    {body}
    <p class="footer">
      Instituto Federal de Educação, Ciência e Tecnologia do Piauí — IFPI<br/>
      Elaborado em conformidade com a LGPD (Lei nº 13.709/2018) e a
      Resolução Normativa CONSUP/OSUPCOL/REI/IFPI Nº 251/2025.
    </p>
  </div>
</body>
</html>"""
