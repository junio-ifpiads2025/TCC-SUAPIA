"""
Exportação de gráficos e tabelas do painel admin em PDF (reportlab, gráficos vetoriais).

Funções puras: recebem dados e devolvem os bytes do PDF.
"""

import io
from datetime import datetime, timedelta, timezone

from reportlab.graphics.charts.barcharts import VerticalBarChart
from reportlab.graphics.charts.lineplots import LinePlot
from reportlab.graphics.shapes import Drawing, Rect, String
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

BRT = timezone(timedelta(hours=-3))
BLUE = colors.HexColor("#1d4ed8")
GREEN = colors.HexColor("#16a34a")
ORANGE = colors.HexColor("#ea580c")
_styles = getSampleStyleSheet()


def _fmt(n) -> str:
    return f"{n:,}".replace(",", ".") if isinstance(n, int) else str(n)


def _table(header: list[str], rows: list[list], col_widths=None, align_right_from: int = 1) -> Table:
    data = [header] + [[_fmt(c) for c in r] for r in rows]
    t = Table(data, colWidths=col_widths, repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), BLUE),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("ALIGN", (align_right_from, 0), (-1, -1), "RIGHT"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f1f5f9")]),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#cbd5e1")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    return t


def _line_chart(title: str, labels: list[str], series: list[tuple[str, list[int], colors.Color]],
                width: float, height: float = 180) -> Drawing:
    d = Drawing(width, height + 24)
    d.add(String(0, height + 10, title, fontName="Helvetica-Bold", fontSize=10))
    plot = LinePlot()
    plot.x, plot.y, plot.width, plot.height = 40, 28, width - 60, height - 28
    plot.data = [[(i, v) for i, v in enumerate(vals)] for _, vals, _ in series]
    for i, (_, _, color) in enumerate(series):
        plot.lines[i].strokeColor = color
        plot.lines[i].strokeWidth = 1.6
    n = len(labels)
    step = max(1, n // 10)
    plot.xValueAxis.valueMin, plot.xValueAxis.valueMax = 0, max(n - 1, 1)
    plot.xValueAxis.valueSteps = list(range(0, n, step))
    plot.xValueAxis.labelTextFormat = lambda v: labels[int(v)] if 0 <= int(v) < n else ""
    plot.xValueAxis.labels.fontSize = 7
    plot.yValueAxis.valueMin = 0
    plot.yValueAxis.labels.fontSize = 7
    plot.yValueAxis.labelTextFormat = "%d"
    d.add(plot)
    for i, (name, _, color) in enumerate(series):
        x = 40 + i * 120
        d.add(String(x + 10, 4, name, fontSize=7))
        d.add(Rect(x, 3, 7, 7, fillColor=color, strokeColor=color))
    return d


def _bar_chart(title: str, labels: list[str], values: list[int], width: float, height: float = 150) -> Drawing:
    d = Drawing(width, height + 24)
    d.add(String(0, height + 10, title, fontName="Helvetica-Bold", fontSize=10))
    bar = VerticalBarChart()
    bar.x, bar.y, bar.width, bar.height = 40, 28, width - 60, height - 28
    bar.data = [values or [0]]
    bar.bars[0].fillColor = BLUE
    bar.categoryAxis.categoryNames = labels or [""]
    bar.categoryAxis.labels.fontSize = 7
    bar.valueAxis.valueMin = 0
    bar.valueAxis.labels.fontSize = 7
    bar.valueAxis.labelTextFormat = "%d"
    d.add(bar)
    return d


def _build(story: list, landscape_mode: bool = False) -> bytes:
    buf = io.BytesIO()
    size = landscape(A4) if landscape_mode else A4
    doc = SimpleDocTemplate(buf, pagesize=size, leftMargin=1.5 * cm, rightMargin=1.5 * cm,
                            topMargin=1.5 * cm, bottomMargin=1.5 * cm, title="SUAP-IA")
    doc.build(story)
    return buf.getvalue()


def _header(title: str, subtitle: str) -> list:
    stamp = datetime.now(BRT).strftime("%d/%m/%Y %H:%M")
    return [
        Paragraph(title, _styles["Title"]),
        Paragraph(f"{subtitle} · gerado em {stamp}", _styles["Normal"]),
        Spacer(1, 12),
    ]


def usage_report_pdf(report: dict) -> bytes:
    """PDF do painel de uso: resumo, gráficos (mensagens e tokens por dia) e tabelas."""
    daily = report["daily"]
    totals = report["totals"]
    width = A4[0] - 3 * cm
    labels = [r["date"][8:10] + "/" + r["date"][5:7] for r in daily]

    story = _header("SUAP-IA — Uso e consumo de tokens", f"Últimos {report['days']} dias")
    story.append(_table(
        ["Mensagens respondidas", "Chamadas ao LLM", "Tokens de entrada", "Tokens de saída", "Total de tokens", "Tokens/mensagem"],
        [[totals["messages"], totals["calls"], totals["prompt"], totals["completion"], totals["total"],
          totals["avg_tokens_per_message"]]], align_right_from=0))
    story.append(Spacer(1, 14))
    story.append(_line_chart("Tokens por dia", labels, [
        ("Entrada", [r["prompt"] for r in daily], BLUE),
        ("Saída", [r["completion"] for r in daily], ORANGE),
    ], width))
    story.append(Spacer(1, 10))
    story.append(_line_chart("Mensagens respondidas e usuários ativos por dia", labels, [
        ("Mensagens", [r["messages"] for r in daily], GREEN),
        ("Usuários", [r["users"] for r in daily], BLUE),
    ], width))
    story.append(Spacer(1, 14))

    if report["by_model"]:
        story.append(_bar_chart("Tokens por modelo", [m["name"] for m in report["by_model"]],
                                [m["total"] for m in report["by_model"]], width))
        story.append(Spacer(1, 8))
        story.append(Paragraph("Consumo por modelo", _styles["Heading3"]))
        story.append(_table(["Modelo", "Chamadas", "Entrada", "Saída", "Total"],
                            [[m["name"], m["calls"], m["prompt"], m["completion"], m["total"]]
                             for m in report["by_model"]]))
        story.append(Spacer(1, 10))
    if report["by_source"]:
        story.append(Paragraph("Consumo por origem", _styles["Heading3"]))
        story.append(_table(["Origem", "Chamadas", "Entrada", "Saída", "Total"],
                            [[m["name"], m["calls"], m["prompt"], m["completion"], m["total"]]
                             for m in report["by_source"]]))
        story.append(Spacer(1, 10))

    story.append(Paragraph("Detalhamento diário", _styles["Heading3"]))
    story.append(_table(
        ["Data", "Mensagens", "Usuários", "Chamadas", "Entrada", "Saída", "Total"],
        [[r["date"], r["messages"], r["users"], r["calls"], r["prompt"], r["completion"], r["total"]]
         for r in reversed(daily)]))
    return _build(story)


def logs_pdf(rows: list[dict], filters: str) -> bytes:
    """PDF da tabela de logs de acesso (já filtrada)."""
    story = _header("SUAP-IA — Log de acesso", filters or "Sem filtros")
    body = []
    for r in rows:
        created = r["created_at"]
        when = created.astimezone(BRT).strftime("%d/%m/%Y %H:%M:%S") if created else ""
        who = r.get("matricula") or r["chat_id"]
        if r.get("nome"):
            who = f"{who} ({r['nome']})"
        body.append([when, who[:40], r["event"], r.get("provider") or "", r.get("duration_ms") or "",
                     (r.get("detail") or "")[:70]])
    story.append(_table(["Data/hora", "Usuário", "Evento", "Provider", "ms", "Detalhe"], body,
                        col_widths=[3.3 * cm, 5 * cm, 3.4 * cm, 2 * cm, 1.4 * cm, 10 * cm],
                        align_right_from=4))
    return _build(story, landscape_mode=True)
