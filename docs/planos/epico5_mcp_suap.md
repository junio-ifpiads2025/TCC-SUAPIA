# Plano — Épico 5: Agente de IA — MCP SUAP (Dados Acadêmicos)

> Requisitos cobertos: RF17, RF18, RF19, RF20 | Regras: RN11, RN12, RN13

**Depende de:** Épico 1 (token no Redis), Épico 3 (processador de fila), `suap-mcp` (git `-e`)

---

## Objetivo

Permitir que o agente consulte dados acadêmicos pessoais do aluno (notas, faltas, disciplinas etc.) usando o token SUAP recuperado do Redis e as ferramentas MCP existentes.

---

## Arquivos a criar / modificar

| Arquivo | Ação |
|---------|------|
| `services/mcp_client.py` | Modificar — garantir conformidade com RN13 |
| `services/agent_orchestrator.py` | Modificar — integrar recuperação de token e tratamento RF20 |
| `services/falta_calculator.py` | Criar — lógica de RN11 e RN12 |

---

## Ferramentas MCP disponíveis (RF18)

As seguintes ferramentas devem estar expostas no formato OpenAI tool-calling:

| Ferramenta | Dado retornado |
|-----------|---------------|
| `get_perfil` | Nome, matrícula, curso |
| `get_notas` | Notas por disciplina e período |
| `get_faltas` | Faltas registradas por disciplina |
| `get_diarios` | Diários de classe |
| `get_materiais` | Materiais de aula disponíveis |
| `get_mensagens` | Mensagens institucionais |
| `get_periodos` | Períodos letivos |
| `get_disciplinas` | Disciplinas matriculadas no período atual |

---

## Passos

### 5.1 — Recuperação de token (RF17, RN13)

Em `agent_orchestrator.py`, antes de invocar qualquer ferramenta MCP:

```python
token = await session_service.get_token(chat_id)
if not token:
    return "Sua sessão expirou. Envie qualquer mensagem para receber o link de login.", []
```

- Token recuperado do Redis no momento da execução, nunca em cache local (RN13).
- Token passado como parâmetro às ferramentas; nunca logado.

### 5.2 — `services/mcp_client.py` — Conformidade com RN13

Revisar todos os pontos onde o token poderia aparecer em logs:

```python
# utils/security.py
headers = sanitize_log({"Authorization": f"Bearer {token}", ...})
logger.debug("mcp_request", extra={"headers": headers})  # token removido pelo sanitize
```

Garantir que `sanitize_log` remove chaves: `authorization`, `token`, `senha`, `password`, `cpf`.

### 5.3 — `services/falta_calculator.py` — Cálculo de faltas (RF19, RN11, RN12)

```python
MODALIDADES_ESPECIAIS = {"estágio", "tcc", "atividades complementares"}

def calcular_limite_faltas(carga_horaria: int) -> int:
    return int(carga_horaria * 0.25)  # RN11: 25%, arredondado para baixo

def formatar_faltas_por_disciplina(disciplinas: list[dict]) -> str:
    linhas = []
    for d in disciplinas:
        if d["tipo"].lower() in MODALIDADES_ESPECIAIS:
            # RN12: exibe nota informativa
            linhas.append(f"• {d['nome']}: controle de frequência segue regras específicas.")
        else:
            limite = calcular_limite_faltas(d["carga_horaria"])
            restantes = limite - d["faltas"]
            linhas.append(
                f"• {d['nome']}: {d['faltas']}/{limite} faltas "
                f"({'restam ' + str(restantes) if restantes >= 0 else 'LIMITE EXCEDIDO'})"
            )
    return "\n".join(linhas)
```

### 5.4 — Tratamento de matrícula inativa (RF20)

No orquestrador, após chamar `get_disciplinas`:

```python
if not disciplinas or len(disciplinas) == 0:
    return (
        "Não encontrei matrícula ativa no semestre corrente. "
        "Verifique períodos anteriores ou entre em contato com a coordenação."
    ), []
```

### 5.5 — Ferramentas indisponíveis (RF18)

Cada chamada MCP envolve try/except:
```python
except httpx.RequestError:
    return f"A ferramenta '{tool_name}' está temporariamente indisponível.", []
```

### 5.6 — Loop ReAct (agent_orchestrator)

O orquestrador já implementa tool-calling loop. Garantir:
1. Token injetado em cada chamada de ferramenta.
2. Máximo de iterações configurável (evitar loop infinito).
3. Exceção capturada → `FALLBACK_TEXT`.

---

## Critérios de Aceite

- **RF17:** Token recuperado do Redis e repassado às ferramentas; dados da API usados na resposta.
- **RF18:** Todas as ferramentas listadas retornam dados corretos quando acionadas; ferramentas indisponíveis informam o usuário.
- **RF19:** Faltas exibidas por disciplina com limite calculado corretamente (25% da CH).
- **RF20:** Ausência de matrícula ativa → mensagem orientativa, sem erro técnico.
- **RN11:** `floor(carga_horaria * 0.25)` aplicado.
- **RN12:** Estágio, TCC e complementares exibem nota especial em vez do cálculo padrão.
- **RN13:** Token nunca aparece em logs; token expirado → solicita novo login antes de prosseguir.
