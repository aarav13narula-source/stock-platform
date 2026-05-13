"""CSV + PDF report generators."""
import csv
import io
from datetime import datetime

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, Table,
                                TableStyle, PageBreak)


def to_csv(rows, headers=None):
    out = io.StringIO()
    w = csv.writer(out)
    if not rows:
        if headers:
            w.writerow(headers)
        return out.getvalue()
    keys = headers or list(rows[0].keys())
    w.writerow(keys)
    for r in rows:
        w.writerow([r.get(k, "") for k in keys])
    return out.getvalue()


def build_pdf(title, sections):
    """sections = [(heading, rows, headers)] — produce a styled PDF."""
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=landscape(A4),
                            rightMargin=1*cm, leftMargin=1*cm,
                            topMargin=1*cm, bottomMargin=1*cm)
    styles = getSampleStyleSheet()
    title_s = ParagraphStyle("ti", parent=styles["Title"], fontSize=20,
                             textColor=colors.HexColor("#0b5fff"))
    sub_s = ParagraphStyle("su", parent=styles["Heading2"], fontSize=14,
                           textColor=colors.HexColor("#222"))
    body_s = styles["BodyText"]
    elems = [Paragraph(title, title_s),
             Paragraph(f"Generated: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}",
                       body_s),
             Spacer(1, 0.5*cm)]
    for heading, rows, headers in sections:
        elems.append(Paragraph(heading, sub_s))
        elems.append(Spacer(1, 0.2*cm))
        if not rows:
            elems.append(Paragraph("<i>No data.</i>", body_s))
            elems.append(Spacer(1, 0.5*cm))
            continue
        hdrs = headers or list(rows[0].keys())
        data = [hdrs] + [[str(r.get(h, ""))[:60] for h in hdrs] for r in rows]
        t = Table(data, repeatRows=1)
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0b5fff")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1),
             [colors.whitesmoke, colors.HexColor("#eef4ff")]),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ]))
        elems.append(t)
        elems.append(Spacer(1, 0.6*cm))
    doc.build(elems)
    buf.seek(0)
    return buf.getvalue()
