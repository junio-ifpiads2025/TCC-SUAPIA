# 4.1 Levantamento de Requisitos

O levantamento de requisitos do SUAPIA foi realizado a partir da análise do contexto de uso do sistema institucional SUAP no IFPI, identificando as principais dificuldades enfrentadas pelos alunos no acesso a informações acadêmicas. As necessidades foram organizadas em seis épicos funcionais: autenticação e gestão de sessão, interação e experiência do usuário, pipeline de recebimento e fila de mensagens, agente de IA com RAG (busca nos manuais institucionais), agente de IA com MCP SUAP (dados acadêmicos transacionais) e resposta e envio outbound. Os requisitos foram classificados em Requisitos Funcionais (RF), Regras de Negócio (RN) e Requisitos Não Funcionais (RNF).

Cada requisito funcional é descrito por três elementos: **Descrição** (o que o sistema deve fazer), **Critério de Aceite** (como verificar se o requisito foi atendido) e **Dependências** (outros requisitos ou componentes necessários para sua realização).

---

## Épico 1 — Autenticação e Gestão de Sessão

*Objetivo: Garantir que apenas alunos autenticados acessem o sistema, vinculando o número de WhatsApp à conta SUAP.*

### Requisitos Funcionais

| ID | Requisito |
|----|-----------|
| **RF01** | **Descrição:** O sistema deve enviar uma mensagem de *onboarding* com um link exclusivo e seguro para login quando o número de WhatsApp não estiver vinculado a nenhuma matrícula. **Critério de Aceite:** Usuário sem vínculo recebe o link ao enviar qualquer mensagem; usuário com vínculo ativo prossegue normalmente. **Dependências:** Tabela `user_auth` no PostgreSQL; Redis para verificação de sessão. |
| **RF02** | **Descrição:** O sistema deve disponibilizar uma interface web para que o aluno informe sua matrícula e senha, com validação de campos obrigatórios antes do envio à API do SUAP. **Critério de Aceite:** Campos obrigatórios validados; credenciais enviadas ao SUAP; erros de validação retornam mensagem clara ao usuário sem prosseguir. **Dependências:** API oficial do SUAP. |
| **RF03** | **Descrição:** O sistema deve autenticar as credenciais informadas na API oficial do SUAP, tratando respostas de erro com mensagens informativas ao usuário. **Critério de Aceite:** Credenciais válidas resultam em token armazenado e vínculo persistido. Credenciais inválidas ou SUAP indisponível retornam mensagem de erro amigável. **Dependências:** RF02; Redis; PostgreSQL. |
| **RF04** | **Descrição:** O sistema deve encerrar a sessão do aluno ao receber o comando `/sair`, removendo o token e o vínculo permanente. O aluno precisará realizar novo login na próxima interação, e isso deve ser comunicado claramente. **Critério de Aceite:** Após o comando, qualquer nova mensagem do mesmo `chat_id` aciona o fluxo de *onboarding*. **Dependências:** RF01; Redis; PostgreSQL. |

### Regras de Negócio

| ID | Regra |
|----|-------|
| **RN01** | O vínculo `chat_id` → matrícula deve ser persistido na tabela `user_auth` do PostgreSQL como registro permanente. O token de acesso não é salvo em texto plano no banco — apenas no Redis com TTL. |
| **RN02** | O token armazenado no Redis deve ter TTL idêntico ao informado pela API do SUAP. Caso a API não informe o tempo de expiração, aplica-se TTL padrão de 8 horas como *fallback*. Token expirado exige novo login pelo aluno. |
| **RN03** | Token SUAP, senha e CPF jamais devem ser persistidos em logs, respostas da LLM ou texto plano no banco de dados, em nenhuma camada do sistema. |

---

## Épico 2 — Interação e UX

*Objetivo: Prover comunicação fluida e acessível via WhatsApp, com suporte a texto e comandos básicos.*

### Requisitos Funcionais

| ID | Requisito |
|----|-----------|
| **RF05** | **Descrição:** O sistema deve exibir um menu inicial com as opções disponíveis na primeira interação após o login e sempre que o comando `/menu` for acionado. **Critério de Aceite:** Menu exibido após login e ao digitar `/menu`. Cada opção direciona corretamente ao fluxo correspondente. **Dependências:** RF03. |
| **RF06** | **Descrição:** O assistente deve interpretar mensagens em texto livre para identificar a intenção do aluno e direcionar a consulta ao fluxo correto — RAG, MCP SUAP ou ambos. **Critério de Aceite:** Perguntas em linguagem natural ativam o fluxo adequado e retornam resposta contextualizada. **Dependências:** Épicos 4 e 5. |
| **RF07** | **Descrição:** Em qualquer falha interna, o sistema deve retornar ao usuário uma mensagem de erro genérica e amigável, sem expor detalhes técnicos. **Critério de Aceite:** Nenhuma *stack trace*, nome de tabela, *endpoint* ou token é exibido ao usuário em nenhuma situação. **Dependências:** Todos os épicos. |

### Regras de Negócio

| ID | Regra |
|----|-------|
| **RN04** | Os comandos suportados são `/menu` e `/sair`. Outros comandos de barra retornam mensagem informando as opções disponíveis. O agente opera com *system prompt* restritivo, respondendo apenas perguntas dentro do escopo acadêmico e institucional do SUAP. |

---

## Épico 3 — Pipeline e Fila de Mensagens

*Objetivo: Garantir o recebimento confiável, validação, enfileiramento e processamento assíncrono de todas as mensagens recebidas via WhatsApp.*

### Requisitos Funcionais

| ID | Requisito |
|----|-----------|
| **RF08** | **Descrição:** O sistema deve receber mensagens de texto via *webhook*, identificando o remetente pelo `chat_id` e extraindo o conteúdo da interação. **Critério de Aceite:** *Payload* recebido é parseado; `chat_id` extraído; mensagem encaminhada para validação. **Dependências:** WAHA; FastAPI. |
| **RF09** | **Descrição:** O sistema deve validar a integridade do *payload* recebido quanto à estrutura, campos obrigatórios e origem. *Payloads* inválidos devem ser rejeitados com resposta HTTP 4xx e registrados em log. **Critério de Aceite:** *Payload* inválido é rejeitado silenciosamente e logado. *Payload* válido prossegue para verificação de sessão. **Dependências:** RF08. |
| **RF10** | **Descrição:** Antes de enfileirar, o sistema deve verificar se o `chat_id` possui autenticação ativa e se o limite diário de mensagens não foi atingido. **Critério de Aceite:** Não autenticado → *onboarding*. Cota excedida → aviso ao usuário. Autenticado e dentro do limite → mensagem enfileirada. **Dependências:** Redis; PostgreSQL; RF03. |
| **RF11** | **Descrição:** O sistema deve inserir as mensagens validadas na fila de processamento, registrando o `chat_id`, o conteúdo, o tipo, o *timestamp* de entrada e os metadados necessários. **Critério de Aceite:** Registro inserido com status `pending` e *timestamp* correto. **Dependências:** PostgreSQL; RF10. |
| **RF12** | **Descrição:** O sistema deve processar as mensagens enfileiradas de forma assíncrona, atualizando o status para `processing` durante o tratamento, `completed` ao concluir com sucesso e `failed` em caso de erro. Não há *retry* automático. **Critério de Aceite:** Mensagem `completed` tem resposta registrada. Mensagem `failed` tem erro logado. Nenhuma mensagem permanece em `processing` além do *timeout* configurado. **Dependências:** RF11; Épicos 4 e 5. |

### Regras de Negócio

| ID | Regra |
|----|-------|
| **RN05** | A origem das requisições ao *webhook* deve ser validada por *IP allowlist* ou verificação de assinatura do WAHA, para rejeitar *payloads* de fontes externas não autorizadas. |
| **RN06** | O limite diário de uso é fixado em 25 mensagens por conta vinculada. O contador é armazenado no Redis e reseta automaticamente à meia-noite no fuso horário de Brasília (`America/Sao_Paulo`, UTC-3). Em caso de indisponibilidade do Redis, o sistema bloqueia novas interações e retorna mensagem de instabilidade temporária. |
| **RN07** | Mensagens com status `processing` por mais de 2 minutos são automaticamente marcadas como `failed` por um processo de limpeza periódico. O *timeout* é configurável via variável de ambiente. A tabela de fila deve possuir índice composto nos campos `status` e `created_at` para consulta eficiente. |
| **RN08** | O processamento deve respeitar a ordem FIFO por `chat_id`. Usuários distintos podem ser processados em paralelo. |

---

## Épico 4 — Agente de IA: RAG (Busca nos Manuais)

*Objetivo: Processar consultas institucionais buscando trechos relevantes nos manuais do SUAP via busca vetorial e gerando respostas fundamentadas exclusivamente nesse conteúdo.*

### Requisitos Funcionais

| ID | Requisito |
|----|-----------|
| **RF13** | **Descrição:** O agente deve receber a mensagem do usuário junto com o histórico conversacional e classificar o tipo de consulta: institucional (RAG), dados acadêmicos pessoais (MCP SUAP) ou ambos. **Critério de Aceite:** Consultas classificadas corretamente são roteadas ao fluxo adequado. Consultas mistas acionam RAG e MCP SUAP em paralelo, com resultados combinados na resposta final. **Dependências:** RF12; tabela `thread_history` no PostgreSQL. |
| **RF14** | **Descrição:** Para consultas institucionais, o sistema deve converter a pergunta em representação vetorial e buscar os trechos mais semanticamente relevantes nos manuais do SUAP indexados no banco vetorial. **Critério de Aceite:** Retorna os trechos com maior similaridade semântica. Trechos abaixo do limiar configurado são descartados antes de serem enviados ao modelo. **Dependências:** PostgreSQL com pgvector; modelo de *embedding*. |
| **RF15** | **Descrição:** A resposta deve ser formulada exclusivamente com base nos trechos recuperados. Se nenhum trecho relevante for encontrado, o sistema deve informar o usuário e sugerir contato com a secretaria acadêmica. **Critério de Aceite:** Nenhuma informação é gerada fora do conteúdo dos manuais. Ausência de contexto relevante resulta em mensagem de encaminhamento, não em resposta inventada. **Dependências:** RF14; LLM. |
| **RF16** | **Descrição:** Se o agente falhar por *timeout* ou erro de rede, o sistema deve retornar ao usuário uma mensagem de *fallback* pré-configurada informando a indisponibilidade temporária. **Critério de Aceite:** Usuário recebe mensagem de *fallback*. Mensagem é marcada como `failed` na fila com o erro registrado. **Dependências:** RF12; RF15. |

### Regras de Negócio

| ID | Regra |
|----|-------|
| **RN09** | O limiar mínimo de similaridade para considerar um trecho relevante é configurável via variável de ambiente, com valor padrão de 0,75. Trechos com pontuação abaixo desse limiar não são enviados ao modelo gerador. |
| **RN10** | O histórico conversacional é persistido na tabela `thread_history` do PostgreSQL, vinculado ao `chat_id`. Apenas as últimas 10 mensagens são carregadas por interação. Mensagens mais antigas são descartadas automaticamente. O limite é configurável via variável de ambiente. |

---

## Épico 5 — Agente de IA: MCP SUAP (Dados Acadêmicos)

*Objetivo: Permitir que o aluno consulte seus dados acadêmicos pessoais diretamente pelo WhatsApp, acionando as ferramentas do SUAP por meio do token de acesso autenticado.*

### Requisitos Funcionais

| ID | Requisito |
|----|-----------|
| **RF17** | **Descrição:** Para consultas de dados acadêmicos pessoais, o agente deve acionar as ferramentas MCP SUAP disponíveis, utilizando o token de acesso do aluno autenticado. **Critério de Aceite:** O token é recuperado do Redis e repassado às ferramentas MCP. Dados retornados pela API do SUAP são utilizados para compor a resposta. **Dependências:** RF03; Redis; MCP SUAP. |
| **RF18** | **Descrição:** O sistema deve disponibilizar ao agente as seguintes ferramentas MCP do SUAP: consulta de perfil do aluno, notas, faltas, diários de classe, materiais de aula, mensagens institucionais, períodos letivos e disciplinas matriculadas. **Critério de Aceite:** Cada ferramenta retorna os dados correspondentes da API do SUAP quando acionada pelo agente. Ferramentas indisponíveis resultam em mensagem informativa ao usuário. **Dependências:** RF17; API do SUAP. |
| **RF19** | **Descrição:** O agente deve apresentar ao aluno, para cada disciplina matriculada, a quantidade de faltas registradas e a quantidade máxima de faltas permitidas, calculada com base na carga horária da disciplina. **Critério de Aceite:** O cálculo é exibido por disciplina. Disciplinas com controle especial de frequência exibem nota informativa ao invés do cálculo padrão. **Dependências:** RF18; RN11; RN12. |
| **RF20** | **Descrição:** O sistema deve tratar o caso em que o aluno não possui matrícula ativa no semestre corrente, exibindo mensagem informativa e sugerindo verificar períodos anteriores ou contatar a coordenação. **Critério de Aceite:** Quando a API retorna ausência de matrícula ativa, o usuário recebe orientação clara. Nenhum erro técnico é exposto. **Dependências:** RF18. |

### Regras de Negócio

| ID | Regra |
|----|-------|
| **RN11** | O limite de faltas permitidas por disciplina corresponde a 25% da carga horária total, arredondado para baixo. A quantidade de faltas restantes é obtida subtraindo as faltas registradas desse limite. |
| **RN12** | Disciplinas classificadas como estágio, TCC ou atividades complementares devem ser excluídas do cálculo padrão de 25%, exibindo nota informativa de que o controle de frequência dessas modalidades segue regras específicas. |
| **RN13** | O token de acesso do aluno utilizado nas chamadas MCP deve ser sempre recuperado do Redis no momento da execução, nunca persistido em logs ou texto plano. Em caso de token expirado ou inválido, o sistema deve solicitar novo login ao aluno antes de prosseguir. |

---

## Épico 6 — Resposta e Envio Outbound

*Objetivo: Enviar a resposta gerada ao usuário via WhatsApp e registrar a interação para manutenção do histórico conversacional.*

### Requisitos Funcionais

| ID | Requisito |
|----|-----------|
| **RF21** | **Descrição:** Após o agente gerar a resposta, o sistema deve enviá-la ao usuário via WAHA Client. Se o envio falhar, a mensagem deve ser marcada como `failed` e o erro registrado em log. **Critério de Aceite:** Entrega confirmada → status `completed` e `thread_history` atualizado. Falha → status `failed` com erro logado. **Dependências:** WAHA; Épicos 4 e 5; PostgreSQL. |
| **RF22** | **Descrição:** A resposta gerada e a mensagem original do usuário devem ser registradas no histórico conversacional, vinculadas ao `chat_id`, para que interações futuras possam recuperar o contexto. **Critério de Aceite:** Cada ciclo de interação (mensagem do usuário + resposta do sistema) é persistido na tabela `thread_history`. **Dependências:** PostgreSQL; RF21. |

---

## Requisitos Não Funcionais

| ID | Descrição | Categoria |
|----|-----------|-----------|
| **RNF01** | A integração com o WhatsApp deve ser feita via *webhooks* processados de forma assíncrona, evitando gargalos de *timeout* na resposta da API. | Desempenho |
| **RNF02** | Dados sensíveis (Token SUAP, senha, CPF) jamais devem ser persistidos em logs ou texto plano no banco de dados, em nenhuma camada do sistema. | Segurança |
| **RNF03** | O sistema deve registrar logs estruturados (JSON) de todas as interações, erros e chamadas a APIs externas, com nível de detalhe configurável via variável de ambiente (`DEBUG`, `INFO`, `ERROR`). | Manutenibilidade |
