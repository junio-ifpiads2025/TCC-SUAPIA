# AGENT.MD

Diretrizes para agentes de IA que trabalham neste repositório.

## 1. Sempre fazer brainstorm antes de agir

Antes de escrever ou alterar código, faça um brainstorm:

- Entenda o problema e o objetivo real do pedido.
- Liste ao menos 2 abordagens possíveis, com prós e contras.
- Escolha a mais simples que resolva o problema e justifique a escolha.
- Identifique arquivos, módulos e riscos afetados.
- Só então implemente.

Em caso de dúvida que mude o resultado, pergunte ao usuário antes de implementar.

## 2. Simplicidade acima de tudo

- Prefira o código mais simples que resolve o problema atual.
- Evite excesso de engenharia (over-engineering): sem abstrações, camadas, configurações ou generalizações "para o futuro".
- Não crie classes, interfaces ou padrões de projeto sem necessidade concreta.
- Não adicione dependências novas se a biblioteca padrão ou o código existente resolver.
- Não implemente além do que foi pedido.
- Se há duas soluções, escolha a mais curta e legível.

## 3. Clean Code

- Nomes claros e descritivos para variáveis, funções e classes.
- Funções pequenas, com um único propósito.
- Evite duplicação (DRY), mas não abstraia cedo demais.
- Evite comentários óbvios; o código deve se explicar. Comente apenas o "porquê".
- Trate erros de forma explícita; não engula exceções.
- Evite números e strings mágicos; use constantes.
- Mantenha o estilo do código ao redor (nomes, idioma, densidade de comentários).

## 4. SOLID e separação de responsabilidades

Foco principal: **separação de responsabilidades**.

- **S** — Cada módulo/classe/função tem uma única razão para mudar.
- **O** — Estenda comportamento sem reescrever código estável.
- **L** — Subtipos devem poder substituir seus tipos base.
- **I** — Interfaces pequenas e específicas.
- **D** — Dependa de abstrações, não de implementações concretas.

Aplicação neste projeto:

- `routes/` apenas recebe a requisição, valida a entrada e delega. Sem regra de negócio.
- `services/` contém a lógica de negócio, uma responsabilidade por serviço.
- Organização por domínio: `services/chat` e `routes/chat` (conversa/WhatsApp), `services/admin` e `routes/admin` (painel), `services/shared` (usado pelos dois: logger, sessão, auth, ACL, logs, uso, prompt, guardrails, skills, knowledge). `chat` nunca importa `admin`; `admin` pode importar `chat` e `shared`.
- `models/` cuida de persistência e estrutura de dados.
- Não misture acesso a banco, regra de negócio e camada HTTP no mesmo arquivo.
- Integrações externas (LLM, WhatsApp, MCP) ficam isoladas atrás de seus próprios módulos.

## 5. Documentação: os `readme.md` são a fonte da verdade

Os `readme.md` (raiz, `chat/`, `pipeline/*`) são a **fonte da verdade do TCC escrito**. Toda modificação que altere comportamento, regra de negócio, arquitetura, modelo de dados, fluxo ou configuração **deve atualizar o(s) `readme.md` afetado(s) na mesma entrega**. Uma tarefa não está concluída sem isso.

Público e tom: o texto serve de base para um trabalho acadêmico. Descreva o funcionamento do software de forma **não técnica** (o que faz, para quem, por quê e com quais regras), usando termos de código apenas quando necessário. Escreva em português.

Cada `readme.md` de componente deve conter, quando aplicável ao escopo:

- **Visão geral**: problema, objetivo e público-alvo.
- **Requisitos funcionais** (RF-xx) e **requisitos não funcionais** (RNF-xx): desempenho, segurança, privacidade, disponibilidade, usabilidade etc.
- **Regras de negócio** (RN-xx): permissões, limites de uso, critérios de resposta, guardrails, aceite de termos.
- **Histórias de usuário**: "Como <perfil>, quero <ação>, para <benefício>", com critérios de aceite. Perfis: estudante, administrador, etc.
- **Arquitetura**: visão geral dos componentes, camadas, integrações externas (LLM, WhatsApp/Telegram, MCP, banco vetorial) e fluxo de dados; diagramas (Mermaid) quando ajudarem.
- **Modelagem do banco de dados**: entidades, atributos principais, relacionamentos e finalidade de cada tabela/coleção (diagrama ER em Mermaid).
- **Fluxos principais**: ex.: fluxo de uma mensagem, autenticação, fila, ingestão de manuais.
- **Decisões e limitações**: escolhas relevantes, trade-offs e pontos conhecidos.

Ao alterar código:

1. Identifique quais seções do `readme.md` são impactadas (requisitos, regras, histórias, arquitetura, banco, fluxos).
2. Atualize apenas o que mudou, sem deixar o texto desatualizado ou contraditório; remova o que deixou de existir.
3. Mantenha os IDs (RF/RNF/RN) estáveis; ao criar novos, use o próximo número livre.
4. Se uma alteração de estrutura de pastas ou módulos ocorrer, atualize também a descrição de arquitetura e a seção de organização (ver seção 4).

## 6. LGPD (Lei nº 13.709/2018)

Todo código deve ser escrito em conformidade com a LGPD. Dados pessoais aqui incluem, no mínimo: matrícula SUAP, `chat_id`/número de telefone, nome, conteúdo das conversas e logs que os identifiquem.

- **Minimização**: colete e armazene apenas o necessário para a finalidade. Não registre dado pessoal "por precaução".
- **Finalidade e base legal**: todo novo tratamento de dado pessoal deve ter finalidade clara e documentada no `readme.md`. O aceite dos termos de uso é o registro de consentimento/ciência; não trate dados antes dele.
- **Retenção**: dado pessoal novo nasce com prazo de retenção e rotina de descarte/anonimização. Não crie tabela de dados pessoais sem prazo definido.
- **Direitos do titular**: o design deve permitir acesso, correção, exportação e exclusão dos dados de um titular (por `chat_id`/matrícula).
- **Segurança**: nunca registrar senhas, tokens, cookies, CPF ou segredos em log. Mascare dado pessoal em logs e telas (ex.: número parcial). Segredos só em variáveis de ambiente. Acesso a dado pessoal no painel exige autenticação de administrador e deve ser auditado.
- **Terceiros (LLM, WhatsApp/Telegram)**: envie ao provedor externo somente o necessário à resposta; evite incluir identificadores pessoais no prompt.
- **Privacidade por padrão**: funcionalidades novas que exibam ou guardem conteúdo de conversas (histórico, feedback, exportações) devem vir com mascaramento e retenção desde o início.
- **Incidentes**: erros devem falhar de forma segura, sem vazar dado pessoal em mensagens de erro ou stack traces.
- Documente no `readme.md` (RNF de privacidade e RN) qualquer alteração que mude o tratamento de dados pessoais.

## 7. Equilíbrio

SOLID e Clean Code servem à simplicidade, não o contrário. Se aplicar um princípio deixar o código mais complexo sem ganho real, prefira a solução simples.
