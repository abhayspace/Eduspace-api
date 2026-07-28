"""ReportLab A4 fee receipt PDF generator."""
from __future__ import annotations

import io
import logging
from pathlib import Path
from typing import Any, Optional
from urllib.request import urlopen

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    HRFlowable,
    Image,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

logger = logging.getLogger("eduspace.receipt.pdf")

INK = colors.HexColor("#111827")
MUTED = colors.HexColor("#6B7280")
LINE = colors.HexColor("#E5E7EB")
HEADER_BG = colors.HexColor("#F8FAFC")
ACCENT = colors.HexColor("#1E3A5F")

_FONT_DIR = Path(__file__).resolve().parents[2] / "assets" / "fonts"
_FONTS_READY = False
_FONT_REG = "Helvetica"
_FONT_BOLD = "Helvetica-Bold"


def _ensure_fonts() -> tuple[str, str]:
    """Register DejaVu (supports ₹). Fall back to Helvetica if fonts are missing."""
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
        else:
            logger.warning(
                "DejaVu fonts missing under %s — ₹ may not render; using Helvetica",
                _FONT_DIR,
            )
    except Exception as exc:
        logger.warning("receipt font registration failed: %s", exc)
        _FONT_REG = "Helvetica"
        _FONT_BOLD = "Helvetica-Bold"

    _FONTS_READY = True
    return _FONT_REG, _FONT_BOLD


def _money(amount: Any, currency: str = "INR") -> str:
    try:
        value = float(amount or 0)
    except (TypeError, ValueError):
        value = 0.0
    # DejaVu renders ₹; Helvetica fallback uses ASCII "Rs."
    font_reg, _ = _ensure_fonts()
    if (currency or "INR").upper() == "INR":
        symbol = "₹" if font_reg.startswith("DejaVu") else "Rs. "
    else:
        symbol = f"{currency} "
    return f"{symbol}{value:,.2f}"


def _p(text: str, style: ParagraphStyle) -> Paragraph:
    safe = (text or "—").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return Paragraph(safe, style)


def _try_logo(logo_url: Optional[str], max_w: float = 28 * mm, max_h: float = 22 * mm):
    if not logo_url:
        return None
    try:
        if logo_url.startswith("http://") or logo_url.startswith("https://"):
            data = urlopen(logo_url, timeout=4).read()  # noqa: S310 — school logo URLs
            return Image(io.BytesIO(data), width=max_w, height=max_h, kind="proportional")
        path = Path(logo_url)
        if path.is_file():
            return Image(str(path), width=max_w, height=max_h, kind="proportional")
    except Exception as exc:
        logger.warning("receipt logo load failed: %s", exc)
    return None


def generate_receipt_pdf(snapshot: dict[str, Any]) -> bytes:
    """Build a professional A4 fee receipt PDF from a snapshot dict."""
    font_reg, font_bold = _ensure_fonts()

    school = snapshot.get("school") or {}
    student = snapshot.get("student") or {}
    receipt = snapshot.get("receipt") or {}
    payment = snapshot.get("payment") or {}
    fee_lines = snapshot.get("fee_lines") or []
    totals = snapshot.get("totals") or {}
    currency = (payment.get("currency") or totals.get("currency") or "INR").upper()

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=16 * mm,
        rightMargin=16 * mm,
        topMargin=14 * mm,
        bottomMargin=14 * mm,
        title=f"Fee Receipt {receipt.get('receipt_number') or ''}",
    )

    styles = getSampleStyleSheet()
    school_name = ParagraphStyle(
        "SchoolName",
        parent=styles["Heading1"],
        fontName=font_bold,
        fontSize=16,
        textColor=ACCENT,
        spaceAfter=2,
        leading=20,
    )
    meta = ParagraphStyle(
        "Meta",
        parent=styles["Normal"],
        fontName=font_reg,
        fontSize=9,
        textColor=MUTED,
        leading=12,
    )
    section = ParagraphStyle(
        "Section",
        parent=styles["Normal"],
        fontSize=10,
        textColor=ACCENT,
        fontName=font_bold,
        spaceBefore=8,
        spaceAfter=4,
    )
    body = ParagraphStyle(
        "Body",
        parent=styles["Normal"],
        fontName=font_reg,
        fontSize=9,
        textColor=INK,
        leading=12,
    )
    body_right = ParagraphStyle("BodyRight", parent=body, alignment=TA_RIGHT)
    footer = ParagraphStyle(
        "Footer",
        parent=styles["Normal"],
        fontName=font_reg,
        fontSize=8,
        textColor=MUTED,
        alignment=TA_CENTER,
        leading=11,
    )
    title_style = ParagraphStyle(
        "ReceiptTitle",
        parent=styles["Normal"],
        fontSize=13,
        textColor=INK,
        fontName=font_bold,
        alignment=TA_CENTER,
        spaceBefore=6,
        spaceAfter=8,
    )
    bold_body = ParagraphStyle("BoldBody", parent=body, fontName=font_bold)
    bold_right = ParagraphStyle("BoldRight", parent=body_right, fontName=font_bold)

    story: list = []

    # ---- Header: logo + school ----
    logo = _try_logo(school.get("logo_url"))
    address_parts = [
        school.get("address"),
        ", ".join(p for p in [school.get("city"), school.get("state"), school.get("pincode")] if p),
    ]
    address_line = " · ".join(p for p in address_parts if p)
    contact_bits = []
    if school.get("phone"):
        contact_bits.append(f"Phone: {school['phone']}")
    if school.get("email"):
        contact_bits.append(f"Email: {school['email']}")
    if school.get("website"):
        contact_bits.append(school["website"])
    if school.get("gst_number"):
        contact_bits.append(f"GST: {school['gst_number']}")

    school_block = [
        _p(school.get("school_name") or school.get("name") or "School", school_name),
        _p(address_line or "—", meta),
        _p(" · ".join(contact_bits) if contact_bits else " ", meta),
    ]

    if logo:
        header = Table([[logo, school_block]], colWidths=[32 * mm, 146 * mm])
    else:
        header = Table([[school_block]], colWidths=[178 * mm])
    header.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("BACKGROUND", (0, 0), (-1, -1), HEADER_BG),
                ("BOX", (0, 0), (-1, -1), 0.4, LINE),
                ("TOPPADDING", (0, 0), (-1, -1), 8),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
            ]
        )
    )
    story.append(header)
    story.append(Spacer(1, 6))
    story.append(Paragraph("FEE RECEIPT", title_style))
    story.append(HRFlowable(width="100%", thickness=1, color=ACCENT, spaceAfter=6))

    # ---- Receipt meta ----
    story.append(Paragraph("Receipt Information", section))
    receipt_rows = [
        [
            _p("Receipt Number", meta),
            _p(str(receipt.get("receipt_number") or "—"), body),
            _p("Invoice Number", meta),
            _p(str(receipt.get("invoice_number") or payment.get("invoice_number") or "—"), body),
        ],
        [
            _p("Receipt Date", meta),
            _p(str(receipt.get("receipt_date") or receipt.get("generated_at") or "—")[:10], body),
            _p("Payment Date", meta),
            _p(str(payment.get("payment_date") or "—")[:10], body),
        ],
    ]
    meta_table = Table(receipt_rows, colWidths=[38 * mm, 51 * mm, 38 * mm, 51 * mm])
    meta_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), colors.white),
                ("BOX", (0, 0), (-1, -1), 0.4, LINE),
                ("INNERGRID", (0, 0), (-1, -1), 0.3, LINE),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    story.append(meta_table)

    # ---- Student ----
    story.append(Paragraph("Student Information", section))
    student_rows = [
        [
            _p("Student Name", meta),
            _p(str(student.get("full_name") or "—"), body),
            _p("Admission No.", meta),
            _p(str(student.get("admission_no") or "—"), body),
        ],
        [
            _p("Roll Number", meta),
            _p(str(student.get("roll_no") or "—"), body),
            _p("Class / Section", meta),
            _p(
                f"{student.get('class_name') or '—'} / {student.get('section_name') or '—'}",
                body,
            ),
        ],
    ]
    student_table = Table(student_rows, colWidths=[38 * mm, 51 * mm, 38 * mm, 51 * mm])
    student_table.setStyle(
        TableStyle(
            [
                ("BOX", (0, 0), (-1, -1), 0.4, LINE),
                ("INNERGRID", (0, 0), (-1, -1), 0.3, LINE),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    story.append(student_table)

    # ---- Fee breakdown ----
    story.append(Paragraph("Fee Breakdown", section))
    fee_header = [
        _p("#", meta),
        _p("Particulars", meta),
        _p("Amount", meta),
    ]
    fee_data = [fee_header]
    if fee_lines:
        for idx, line in enumerate(fee_lines, start=1):
            fee_data.append(
                [
                    _p(str(idx), body),
                    _p(str(line.get("title") or line.get("name") or "Fee"), body),
                    _p(_money(line.get("amount"), currency), body_right),
                ]
            )
    else:
        fee_data.append(
            [
                _p("1", body),
                _p("Fee Payment", body),
                _p(_money(totals.get("subtotal") or payment.get("amount"), currency), body_right),
            ]
        )

    discount = float(totals.get("discount") or payment.get("discount") or 0)
    fine = float(totals.get("fine") or payment.get("fine") or 0)
    previous_due = float(totals.get("previous_due") or 0)
    tax = float(totals.get("tax") or payment.get("tax") or 0)
    total_paid = float(
        totals.get("total_paid")
        or payment.get("total")
        or payment.get("amount")
        or 0
    )

    def _extra(label: str, amount: float) -> None:
        fee_data.append(
            [
                _p("", body),
                _p(label, body),
                _p(_money(amount, currency), body_right),
            ]
        )

    if discount:
        _extra("Discount", -abs(discount))
    if fine:
        _extra("Fine", fine)
    if previous_due:
        _extra("Previous Due", previous_due)
    if tax:
        _extra("Tax", tax)

    fee_data.append(
        [
            _p("", body),
            _p("Total Paid", bold_body),
            _p(_money(total_paid, currency), bold_right),
        ]
    )

    fee_table = Table(fee_data, colWidths=[12 * mm, 126 * mm, 40 * mm])
    fee_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), HEADER_BG),
                ("BOX", (0, 0), (-1, -1), 0.4, LINE),
                ("INNERGRID", (0, 0), (-1, -1), 0.3, LINE),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("BACKGROUND", (0, -1), (-1, -1), HEADER_BG),
            ]
        )
    )
    story.append(fee_table)

    # ---- Payment info ----
    story.append(Paragraph("Payment Information", section))
    pay_rows = [
        [
            _p("Payment Status", meta),
            _p(str(payment.get("payment_status") or "PAID").upper(), body),
            _p("Payment Method", meta),
            _p(str(payment.get("payment_method") or "—"), body),
        ],
        [
            _p("Gateway", meta),
            _p(str(payment.get("gateway_name") or "—"), body),
            _p("Currency", meta),
            _p(currency, body),
        ],
        [
            _p("Gateway Txn ID", meta),
            _p(str(payment.get("transaction_reference") or payment.get("gateway_payment_id") or "—"), body),
            _p("Gateway Payment ID", meta),
            _p(str(payment.get("gateway_payment_id") or "—"), body),
        ],
        [
            _p("Order ID", meta),
            _p(str(payment.get("gateway_order_id") or "—"), body),
            _p("", meta),
            _p("", body),
        ],
    ]
    pay_table = Table(pay_rows, colWidths=[38 * mm, 51 * mm, 38 * mm, 51 * mm])
    pay_table.setStyle(
        TableStyle(
            [
                ("BOX", (0, 0), (-1, -1), 0.4, LINE),
                ("INNERGRID", (0, 0), (-1, -1), 0.3, LINE),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    story.append(pay_table)

    # ---- Signature area + footer ----
    story.append(Spacer(1, 18))
    sig = Table(
        [
            [
                Paragraph("Authorized Signatory / Stamp", meta),
                Paragraph("Student / Parent Acknowledgement", meta),
            ],
            [Spacer(1, 22 * mm), Spacer(1, 22 * mm)],
            [
                HRFlowable(width="90%", thickness=0.5, color=LINE),
                HRFlowable(width="90%", thickness=0.5, color=LINE),
            ],
        ],
        colWidths=[89 * mm, 89 * mm],
    )
    sig.setStyle(
        TableStyle(
            [
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("VALIGN", (0, 0), (-1, -1), "BOTTOM"),
            ]
        )
    )
    story.append(sig)
    story.append(Spacer(1, 14))
    story.append(Paragraph("This is a computer-generated receipt.", footer))
    story.append(Paragraph("No signature is required.", footer))

    doc.build(story)
    return buf.getvalue()
