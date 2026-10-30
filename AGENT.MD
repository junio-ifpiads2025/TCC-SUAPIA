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
- `models/` cuida de persistência e estrutura de dados.
- Não misture acesso a banco, regra de negócio e camada HTTP no mesmo arquivo.
- Integrações externas (LLM, WhatsApp, MCP) ficam isoladas atrás de seus próprios módulos.

## 5. Equilíbrio

SOLID e Clean Code servem à simplicidade, não o contrário. Se aplicar um princípio deixar o código mais complexo sem ganho real, prefira a solução simples.
