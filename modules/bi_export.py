"""SE_SHEETSAI — BI export: PDF dashboard snapshot. Respects governance."""

from __future__ import annotations

import io
from typing import Any, Dict, List, Optional

from modules.bi_models import get_dashboard, get_widgets_for_dashboard
from modules.bi_queries import execute_widget_query
from modules.bi_security import apply_governance_to_query


def generate_dashboard_pdf(
    dashboard_id: str,
    dashboard_row: Dict[str, Any],
    widgets: List[Dict[str, Any]],
    user_ctx: Dict[str, Any],
) -> bytes:
    """Generate a PDF snapshot of dashboard data (tables). Returns PDF bytes.

    Respects governance (apply_governance_to_query per widget).
    Requires reportlab. If not installed, raises ImportError.
    """
    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import cm
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak
    except ImportError:
        raise ImportError("reportlab is required for PDF export. pip install reportlab")

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        rightMargin=1.5 * cm,
        leftMargin=1.5 * cm,
        topMargin=1.5 * cm,
        bottomMargin=1.5 * cm,
    )
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        name="BITitle",
        parent=styles["Heading1"],
        fontSize=16,
        spaceAfter=12,
    )
    story: List[Any] = []
    title = dashboard_row.get("title") or dashboard_id
    story.append(Paragraph(title, title_style))
    story.append(Spacer(1, 0.5 * cm))

    for i, w in enumerate(widgets):
        w_title = w.get("title") or w.get("widget_id") or f"Widget {i + 1}"
        story.append(Paragraph(w_title, styles["Heading2"]))
        story.append(Spacer(1, 0.3 * cm))

        q = w.get("query") or w.get("query_json") or {}
        if isinstance(q, str):
            try:
                import json
                q = json.loads(q)
            except Exception:
                q = {}
        query = apply_governance_to_query(
            q,
            user_ctx.get("user", ""),
            dashboard_row,
            department=user_ctx.get("department"),
        )
        w_with_query = {**w, "query": query}
        try:
            result = execute_widget_query(w_with_query, user_ctx)
        except Exception:
            result = {"columns": [], "rows": []}
        columns = result.get("columns") or []
        rows = result.get("rows") or []

        if columns and rows:
            table_data = [[str(c) for c in columns]]
            for r in rows:
                table_data.append([str(r.get(c, "")) for c in columns])
            t = Table(table_data, repeatRows=1)
            t.setStyle(
                TableStyle(
                    [
                        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2563eb")),
                        ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
                        ("FONTSIZE", (0, 0), (-1, -1), 9),
                        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafc")]),
                    ]
                )
            )
            story.append(t)
        else:
            story.append(Paragraph("No data", styles["Normal"]))
        story.append(Spacer(1, 0.8 * cm))

    doc.build(story)
    buf.seek(0)
    return buf.read()
