"""
Cálculo e formatação de faltas por disciplina.

Regras aplicadas:
- RN11: limite de faltas = 25% da carga horária (arredondado para baixo).
- RN12: disciplinas de estágio, TCC e atividades complementares não seguem
  o cálculo padrão — exibem nota informativa em vez do contador.
"""

# Modalidades que possuem controle de frequência diferenciado (RN12)
MODALIDADES_ESPECIAIS = {"estágio", "tcc", "atividades complementares"}


def calcular_limite_faltas(carga_horaria: int) -> int:
    """
    Retorna o limite máximo de faltas permitidas para uma disciplina.
    RN11: 25% da carga horária, arredondado para baixo (int truncado).
    """
    return int(carga_horaria * 0.25)


def formatar_faltas_por_disciplina(disciplinas: list[dict]) -> str:
    """
    Formata a situação de faltas de cada disciplina em texto legível para WhatsApp.

    Espera que cada item do lista contenha:
      - 'nome'          : nome da disciplina
      - 'tipo'          : tipo/modalidade (ex: 'regular', 'estágio', 'tcc')
      - 'carga_horaria' : carga horária total em horas
      - 'faltas'        : número de faltas registradas

    Disciplinas com modalidade especial (RN12) exibem nota informativa.
    Disciplinas regulares exibem contador com limite e alertam se excedido (RN11).
    """
    if not disciplinas:
        return "Nenhuma disciplina encontrada para o período informado."

    linhas = []
    for d in disciplinas:
        nome = d.get("nome", "Disciplina desconhecida")
        tipo = d.get("tipo", "").lower()

        if tipo in MODALIDADES_ESPECIAIS:
            # RN12: não aplica regra dos 25% para modalidades especiais
            linhas.append(f"• {nome}: controle de frequência segue regras específicas desta modalidade.")
        else:
            carga_horaria = d.get("carga_horaria", 0)
            faltas = d.get("faltas", 0)
            limite = calcular_limite_faltas(carga_horaria)
            restantes = limite - faltas

            if restantes < 0:
                situacao = f"⚠️ LIMITE EXCEDIDO ({abs(restantes)} falta(s) acima do limite)"
            elif restantes == 0:
                situacao = "⚠️ No limite de faltas"
            else:
                situacao = f"restam {restantes} falta(s)"

            linhas.append(f"• {nome}: {faltas}/{limite} faltas — {situacao}")

    return "\n".join(linhas)
