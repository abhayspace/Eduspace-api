"""Exam datesheet and report-card PDF generators (ReportLab)."""
from __future__ import annotations

import io
from typing import Any, List

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)
from pathlib import Path

INK = colors.HexColor("#111827")
MUTED = colors.HexColor("#6B7280")
LINE = colors.HexColor("#E5E7EB")
HEADER_BG = colors.HexColor("#F8FAFC")
ACCENT = colors.HexColor("#1E3A5F")
BAR_STUDENT = colors.HexColor("#857BED")
BAR_CLASS = colors.HexColor("#94A3B8")

_FONT_DIR = Path(__file__).resolve().parents[1] / "assets" / "fonts"
_FONTS_READY = False
_FONT_REG = "Helvetica"
_FONT_BOLD = "Helvetica-Bold"


def _ensure_fonts() -> tuple[str, str]:
    global _FONTS_READY, _FONT_REG, _FONT_BOLD
    if _FONTS_READY:
        return _FONT_REG, _FONT_BOLD
    regular = _FONT_DIR / "DejaVuSans.ttf"
    bold = _FONT_DIR / "DejaVuSans-Bold.ttf"
    try:
        if regular.is_file() and bold.is_file():
            registered = set(pdfmetrics.getRegisteredFontNames())
            if "DejaVuSans" not in registered:
                pdfmetrics.registerFont(TTFont("DejaVuSans", str(regular)))
            if "DejaVuSans-Bold" not in registered:
                pdfmetrics.registerFont(TTFont("DejaVuSans-Bold", str(bold)))
            _FONT_REG = "DejaVuSans"
            _FONT_BOLD = "DejaVuSans-Bold"
    except Exception:
        _FONT_REG = "Helvetica"
        _FONT_BOLD = "Helvetica-Bold"
    _FONTS_READY = True
    return _FONT_REG, _FONT_BOLD


def _p(text: str, style: ParagraphStyle) -> Paragraph:
    safe = (text or "—").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return Paragraph(safe, style)


def generate_datesheet_pdf(snapshot: dict[str, Any]) -> bytes:
    font_reg, font_bold = _ensure_fonts()
    school = snapshot.get("school") or {}
    exam_name = snapshot.get("exam_name") or "Examination"
    class_name = snapshot.get("class_name") or ""
    rows: List[dict] = snapshot.get("rows") or []

    styles = getSampleStyleSheet()
    title = ParagraphStyle(
        "ExamTitle",
        parent=styles["Heading1"],
        fontName=font_bold,
        fontSize=16,
        textColor=INK,
        alignment=TA_CENTER,
        spaceAfter=4,
    )
    sub = ParagraphStyle(
        "ExamSub",
        parent=styles["Normal"],
        fontName=font_reg,
        fontSize=11,
        textColor=MUTED,
        alignment=TA_CENTER,
        spaceAfter=12,
    )
    cell = ParagraphStyle(
        "ExamCell",
        parent=styles["Normal"],
        fontName=font_reg,
        fontSize=10,
        textColor=INK,
        alignment=TA_LEFT,
    )

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=16 * mm,
        bottomMargin=16 * mm,
    )
    story = [
        _p(school.get("school_name") or school.get("name") or "School", title),
        _p(f"Datesheet — {exam_name}" + (f" · {class_name}" if class_name else ""), sub),
        Spacer(1, 6),
    ]

    table_data = [
        [
            _p("S.No", cell),
            _p("Subject", cell),
            _p("Date", cell),
            _p("Max Marks", cell),
        ]
    ]
    for i, row in enumerate(rows, start=1):
        table_data.append(
            [
                _p(str(i), cell),
                _p(str(row.get("subject") or "—"), cell),
                _p(str(row.get("exam_date") or "TBD"), cell),
                _p(str(row.get("max_marks") or "—"), cell),
            ]
        )

    table = Table(table_data, colWidths=[18 * mm, 70 * mm, 45 * mm, 30 * mm])
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), HEADER_BG),
                ("TEXTCOLOR", (0, 0), (-1, 0), ACCENT),
                ("FONTNAME", (0, 0), (-1, 0), font_bold),
                ("GRID", (0, 0), (-1, -1), 0.5, LINE),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 8),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ]
        )
    )
    story.append(table)
    doc.build(story)
    return buf.getvalue()


def generate_report_card_pdf(snapshot: dict[str, Any]) -> bytes:
    font_reg, font_bold = _ensure_fonts()
    school = snapshot.get("school") or {}
    student = snapshot.get("student") or {}
    exam_name = snapshot.get("exam_name") or "Examination"
    subjects: List[dict] = snapshot.get("subjects") or []

    styles = getSampleStyleSheet()
    title = ParagraphStyle(
        "RcTitle",
        parent=styles["Heading1"],
        fontName=font_bold,
        fontSize=16,
        textColor=INK,
        alignment=TA_CENTER,
        spaceAfter=4,
    )
    sub = ParagraphStyle(
        "RcSub",
        parent=styles["Normal"],
        fontName=font_reg,
        fontSize=11,
        textColor=MUTED,
        alignment=TA_CENTER,
        spaceAfter=10,
    )
    body = ParagraphStyle(
        "RcBody",
        parent=styles["Normal"],
        fontName=font_reg,
        fontSize=10,
        textColor=INK,
        spaceAfter=4,
    )
    cell = ParagraphStyle(
        "RcCell",
        parent=styles["Normal"],
        fontName=font_reg,
        fontSize=9,
        textColor=INK,
    )

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=16 * mm,
        rightMargin=16 * mm,
        topMargin=14 * mm,
        bottomMargin=14 * mm,
    )
    story = [
        _p(school.get("school_name") or school.get("name") or "School", title),
        _p(f"Report Card — {exam_name}", sub),
        _p(f"Student: {student.get('full_name') or '—'}", body),
        _p(
            f"Class: {student.get('class_name') or '—'}  ·  Section: {student.get('section_name') or '—'}",
            body,
        ),
        Spacer(1, 8),
    ]

    table_data = [
        [
            _p("Subject", cell),
            _p("Marks", cell),
            _p("Max", cell),
            _p("%", cell),
            _p("Grade", cell),
            _p("Class Avg", cell),
        ]
    ]
    for row in subjects:
        marks = float(row.get("marks_obtained") or 0)
        max_m = float(row.get("max_marks") or 100) or 100
        pct = round((marks / max_m) * 100, 1)
        avg = row.get("class_average")
        table_data.append(
            [
                _p(str(row.get("subject") or "—"), cell),
                _p(f"{marks:g}", cell),
                _p(f"{max_m:g}", cell),
                _p(f"{pct:g}", cell),
                _p(str(row.get("grade") or "—"), cell),
                _p(f"{float(avg):.1f}" if avg is not None else "—", cell),
            ]
        )

    table = Table(table_data, colWidths=[42 * mm, 22 * mm, 20 * mm, 20 * mm, 22 * mm, 28 * mm])
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), HEADER_BG),
                ("GRID", (0, 0), (-1, -1), 0.5, LINE),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 7),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
            ]
        )
    )
    story.append(table)
    story.append(Spacer(1, 14))
    story.append(_p("Subject comparison (student vs class average)", body))
    story.append(Spacer(1, 6))

    # Simple horizontal bar comparison table
    bar_rows = [[_p("Subject", cell), _p("Student", cell), _p("Class avg", cell)]]
    for row in subjects:
        marks = float(row.get("marks_obtained") or 0)
        max_m = float(row.get("max_marks") or 100) or 100
        avg = float(row.get("class_average") or 0)
        student_bar = "█" * max(1, int(round((marks / max_m) * 12)))
        class_bar = "█" * max(1, int(round((avg / max_m) * 12))) if avg else "—"
        bar_rows.append(
            [
                _p(str(row.get("subject") or "—"), cell),
                _p(f"{student_bar} {marks:g}", cell),
                _p(f"{class_bar} {avg:g}" if avg else "—", cell),
            ]
        )
    bars = Table(bar_rows, colWidths=[45 * mm, 60 * mm, 60 * mm])
    bars.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), HEADER_BG),
                ("GRID", (0, 0), (-1, -1), 0.4, LINE),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    story.append(bars)
    doc.build(story)
    return buf.getvalue()
