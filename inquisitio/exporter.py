from __future__ import annotations

import sys
from io import BytesIO
from pathlib import Path
from xml.sax.saxutils import escape

from docx import Document
from docx.enum.style import WD_STYLE_TYPE
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from .production import FORM_205_REQUESTS


def _display(value: object) -> str:
    return value if isinstance(value, str) else "" if value is None else str(value)


def _setup_document() -> Document:
    document = Document()
    section = document.sections[0]
    section.top_margin = Inches(0.65)
    section.bottom_margin = Inches(0.65)
    section.left_margin = Inches(0.8)
    section.right_margin = Inches(0.8)
    document.styles["Normal"].font.name = "Arial"
    document.styles["Normal"].font.size = Pt(10.5)
    for style_name in ("Title", "Heading 1", "Heading 2", "Heading 3"):
        document.styles[style_name].font.color.rgb = RGBColor(0, 0, 0)
    return document


def _response_style(document: Document, name: str, *, left: float = 0, first: float = 0,
                    before: float = 0, after: float = 0, line_spacing: float = 1.0,
                    bold: bool = False):
    style = document.styles.add_style(name, WD_STYLE_TYPE.PARAGRAPH)
    style.font.name = "Arial"
    style.font.size = Pt(12)
    style.font.bold = bold
    style.font.color.rgb = RGBColor(0, 0, 0)
    style.paragraph_format.left_indent = Inches(left)
    style.paragraph_format.first_line_indent = Inches(first)
    style.paragraph_format.space_before = Pt(before)
    style.paragraph_format.space_after = Pt(after)
    style.paragraph_format.line_spacing = line_spacing
    return style


def _setup_response_document() -> Document:
    """Create the pleading-style document used for served-response review."""
    document = Document()
    section = document.sections[0]
    section.top_margin = Inches(1.0)
    section.bottom_margin = Inches(1.0)
    section.left_margin = Inches(1.0)
    section.right_margin = Inches(1.0)
    normal = document.styles["Normal"]
    normal.font.name = "Arial"
    normal.font.size = Pt(12)
    normal.font.color.rgb = RGBColor(0, 0, 0)
    normal.paragraph_format.space_after = Pt(0)
    title = document.styles["Title"]
    title.font.name = "Arial"
    title.font.size = Pt(12)
    title.font.bold = True
    title.font.color.rgb = RGBColor(0, 0, 0)
    title.paragraph_format.space_after = Pt(18)
    _response_style(document, "Pleading Introduction", first=0.5, after=6, line_spacing=2.0)
    _response_style(document, "Interrogatory Question", left=0.75, first=-0.5, before=4, after=5)
    _response_style(document, "Interrogatory Subpart", left=1.25, first=-0.5, before=3, after=4)
    _response_style(document, "Interrogatory Answer", left=0, before=6, after=10, bold=True)
    _response_style(document, "Production Request", left=0.5, first=-0.5, before=5, after=5)
    return document


def _remove_table_borders(table) -> None:
    properties = table._tbl.tblPr
    borders = properties.first_child_found_in("w:tblBorders")
    if borders is None:
        borders = OxmlElement("w:tblBorders")
        properties.append(borders)
    for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
        element = borders.find(qn(f"w:{edge}"))
        if element is None:
            element = OxmlElement(f"w:{edge}")
            borders.append(element)
        element.set(qn("w:val"), "nil")


def _set_cell_text(cell, value: object, *, bold: bool = True) -> None:
    paragraph = cell.paragraphs[0]
    paragraph.paragraph_format.space_after = Pt(8)
    run = paragraph.add_run(_display(value))
    run.bold = bold
    run.font.name = "Arial"
    run.font.size = Pt(12)


def _responding_party(record: dict) -> str:
    metadata = record.get("metadata", {})
    role = _display(metadata.get("responding_party_role")).strip().lower()
    if role == "defendant":
        return _display(metadata.get("defendant")) or "Defendant"
    if role == "plaintiff":
        return _display(metadata.get("plaintiff")) or "Plaintiff"
    form_id = _display(record.get("form_id") or record.get("form", {}).get("form_id"))
    if form_id == "202":
        return _display(metadata.get("plaintiff")) or "Plaintiff"
    return _display(metadata.get("responding_party")) or "Responding Party"


def _add_pleading_caption(document: Document, record: dict) -> None:
    metadata = record.get("metadata", {})
    table = document.add_table(rows=4, cols=3)
    table.autofit = False
    widths = (Inches(3.35), Inches(0.35), Inches(2.8))
    for row in table.rows:
        for cell, width in zip(row.cells, widths):
            cell.width = width
            cell.margin_top = 0
            cell.margin_bottom = 0
    _remove_table_borders(table)
    rows = (
        (f"DOCKET NO.: {_display(metadata.get('docket_number'))}", ":", "SUPERIOR COURT"),
        (_display(metadata.get("plaintiff")) or "Plaintiff", ":", f"JUDICIAL DISTRICT OF {_display(metadata.get('judicial_district'))}"),
        ("v.", ":", f"AT {_display(metadata.get('court', record.get('form', {}).get('court', '')))}"),
        (_display(metadata.get("defendant")) or "Defendant", ":", _display(metadata.get("response_date"))),
    )
    for row, values in zip(table.rows, rows):
        for cell, value in zip(row.cells, values):
            _set_cell_text(cell, value)
    document.add_paragraph()


def _legal_answer(value: object) -> str:
    text = _display(value).strip()
    if not text:
        return "[No response entered - attorney review required.]"
    normalized = text.rstrip(". ").lower()
    if normalized == "yes":
        return "Yes."
    if normalized == "no":
        return "No."
    if normalized in {"n/a", "not applicable"}:
        return "N/A."
    return text


def _add_answer_paragraph(document: Document, label: str, answer: object) -> None:
    paragraph = document.add_paragraph(style="Interrogatory Answer")
    paragraph.paragraph_format.tab_stops.add_tab_stop(Inches(1.25))
    paragraph.add_run(label).bold = True
    paragraph.add_run("\t" + _legal_answer(answer)).bold = True


def _response_title(record: dict) -> str:
    if _display(record.get("form_id")) == "202":
        return "PLAINTIFF'S RESPONSES TO DEFENDANT'S\nINTERROGATORIES AND REQUESTS FOR PRODUCTION"
    role = _display(record.get("metadata", {}).get("responding_party_role")).strip().upper()
    owner = f"{role}'S" if role in {"PLAINTIFF", "DEFENDANT"} else "RESPONDING PARTY'S"
    return f"{owner} RESPONSES TO\nCHILD SUPPORT INTERROGATORIES"


def _register_pdf_fonts() -> tuple[str, str]:
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    regular = root / "assets" / "InquisitioSans.ttf"
    bold = root / "assets" / "InquisitioSans-Bold.ttf"
    if "InquisitioSans" not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont("InquisitioSans", regular))
        pdfmetrics.registerFont(TTFont("InquisitioSans-Bold", bold))
        pdfmetrics.registerFontFamily(
            "InquisitioSans", normal="InquisitioSans", bold="InquisitioSans-Bold",
            italic="InquisitioSans", boldItalic="InquisitioSans-Bold",
        )
    return "InquisitioSans", "InquisitioSans-Bold"


def _production_items(record: dict):
    entries = record.get("production") or {}
    for number, original in enumerate(FORM_205_REQUESTS, start=1):
        item = entries.get(f"205-{number}", {})
        yield number, _display(item.get("request") or original), item


def _production_response(item: dict) -> str:
    """Only a human-entered response can populate Form 205 output."""
    return _display(item.get("response", "")).strip() or "[Production response not verified - attorney review required.]"


def export_case(record: dict) -> bytes:
    document = _setup_response_document()
    form = record["form"]
    form_id = _display(form.get("form_id", record.get("form_id")))
    _add_pleading_caption(document, record)
    warning = document.add_paragraph("ATTORNEY REVIEW DRAFT - NOT FOR SERVICE")
    warning.alignment = WD_ALIGN_PARAGRAPH.CENTER
    warning.runs[0].bold = True

    heading = document.add_paragraph()
    heading.alignment = WD_ALIGN_PARAGRAPH.CENTER
    heading.paragraph_format.space_after = Pt(14)
    run = heading.add_run(_response_title(record))
    run.bold = True
    run.underline = True
    run.font.size = Pt(12)

    party = _responding_party(record)
    introduction = document.add_paragraph(style="Pleading Introduction")
    introduction.add_run(
        f"The undersigned submits the following responses of {party} to Connecticut Practice Book "
        f"Form {form_id}, {form.get('title', 'Interrogatories')}. {_display(form.get('deadline_text'))}"
    )
    if form_id == "202":
        definition = document.add_paragraph(style="Pleading Introduction")
        definition.add_run(
            'Definition: "You" means the Plaintiff to whom these interrogatories are directed. '
            "If suit was instituted by the representative of an estate, ward, or incapable person, "
            '"you" also refers to that decedent, ward, or incapable person unless the context clearly indicates otherwise.'
        )
    instruction = document.add_paragraph(style="Pleading Introduction")
    instruction.add_run(
        "Each response provides the information presently known, possessed, or controlled by the responding party. "
        "Each subpart is answered separately. If an interrogatory cannot be answered in full, the response states "
        "the supported information available and identifies any item requiring attorney review."
    )

    answers = record.get("answers", {})
    if any(citation.get("ocr_sourced") for answer in answers.values() for citation in answer.get("supporting_citations", [])):
        ocr_notice = document.add_paragraph("OCR-sourced evidence is used in this draft. Verify all transcribed values against the original scanned PDF before approval.")
        ocr_notice.paragraph_format.space_after = Pt(10)
    last_number = None
    for item in form["items"]:
        if item["number"] != last_number:
            last_number = item["number"]
            paragraph = document.add_paragraph(style="Interrogatory Question")
            paragraph.paragraph_format.keep_with_next = True
            paragraph.paragraph_format.tab_stops.add_tab_stop(Inches(0.75))
            paragraph.add_run(f"{item['number']}.\t")
            if item.get("prompt"):
                paragraph.add_run(item["prompt"])
        if item.get("label"):
            question = document.add_paragraph(style="Interrogatory Subpart")
            question.paragraph_format.keep_with_next = True
            question.paragraph_format.tab_stops.add_tab_stop(Inches(1.25))
            question.add_run(f"({item['label']})\t")
            question.add_run(item["text"])
        elif not item.get("prompt"):
            paragraph.add_run(item["text"])
        answer = answers.get(item["item_id"], {})
        _add_answer_paragraph(document, "ANSWER:", answer.get("answer"))

    if form_id == "202":
        document.add_page_break()
        production_heading = document.add_paragraph()
        production_heading.alignment = WD_ALIGN_PARAGRAPH.CENTER
        production_heading.paragraph_format.space_after = Pt(14)
        run = production_heading.add_run("REQUESTS FOR PRODUCTION")
        run.bold = True
        run.underline = True
        run.font.size = Pt(12)
        document.add_paragraph(
            "The Defendant requests that the Plaintiff provide copies of the following documents or appropriate "
            "written authorizations. Each production response remains subject to attorney review.",
            style="Pleading Introduction",
        )
        for number, request, production_item in _production_items(record):
            paragraph = document.add_paragraph(style="Production Request")
            paragraph.paragraph_format.keep_with_next = True
            paragraph.paragraph_format.tab_stops.add_tab_stop(Inches(0.5))
            paragraph.add_run(f"{number}.\t")
            paragraph.add_run(request)
            _add_answer_paragraph(document, "RESPONSE:", _production_response(production_item))

    document.add_page_break()
    verification = document.add_paragraph(style="Title")
    verification.alignment = WD_ALIGN_PARAGRAPH.CENTER
    verification.add_run("VERIFICATION PAGE")
    document.add_paragraph(
        "I hereby certify that I have reviewed the above interrogatories and responses and that they are true and "
        "accurate to the best of my knowledge and belief.", style="Pleading Introduction",
    )
    document.add_paragraph(f"{party}\n\nBy: ____________________________________    Date: __________________")
    document.add_paragraph("Subscribed and sworn before me this ______ day of __________________, 20____.")
    document.add_paragraph("Commissioner of the Superior Court: __________________________________________")
    document.add_page_break()
    certification = document.add_paragraph(style="Title")
    certification.alignment = WD_ALIGN_PARAGRAPH.CENTER
    certification.add_run("CERTIFICATION")
    document.add_paragraph(
        "I certify that a copy of this document was or will immediately be mailed or delivered electronically or "
        "non-electronically to all attorneys and self-represented parties of record.", style="Pleading Introduction",
    )
    document.add_paragraph("Recipients: _________________________________________________________________")
    document.add_paragraph("Filer signature: ____________________  Printed name: ____________________  Date: __________")
    document.add_paragraph("Mailing or email address: ______________________________  Telephone: __________")

    stream = BytesIO()
    document.save(stream)
    return stream.getvalue()


def export_traceability(record: dict) -> bytes:
    document = _setup_document()
    heading = document.add_paragraph()
    heading.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = heading.add_run("Evidence Traceability Report")
    run.bold = True
    run.font.size = Pt(14)
    document.add_paragraph(f"Matter: {_display(record.get('case_name'))}")
    document.add_paragraph(f"Form: {_display(record.get('form_id'))}")
    document.add_paragraph("ATTORNEY REVIEW WORK PRODUCT - NOT A SERVED DISCOVERY RESPONSE")

    answers = record.get("answers", {})
    for item in record.get("form", {}).get("items", []):
        answer = answers.get(item["item_id"], {})
        document.add_heading(f"{item['item_id']}: {item.get('text', '')}", level=2)
        document.add_paragraph(f"Proposed answer: {_display(answer.get('answer')) or '[Unresolved]'}")
        document.add_paragraph(
            f"Slot status: {_display(answer.get('status', 'EMPTY'))} | "
            f"Evidence outcome: {_display(answer.get('evidence_outcome', ''))}"
        )
        missing = answer.get("missing_information", [])
        document.add_paragraph("Missing information: " + (", ".join(map(_display, missing)) if missing else "None identified"))
        conflicts = answer.get("conflicts", [])
        document.add_paragraph("Conflicts: " + ("; ".join(_display(value.get("description")) for value in conflicts) if conflicts else "None identified"))
        citations = answer.get("supporting_citations", [])
        if not citations:
            document.add_paragraph("Supporting evidence: No validated citation.")
        for citation in citations:
            paragraph = document.add_paragraph()
            paragraph.add_run("Source: ").bold = True
            if citation.get("citation_kind") == "case_record":
                paragraph.add_run(f"{_display(citation.get('citation_label'))}; SHA-256 {_display(citation.get('document_sha256'))}")
            else:
                paragraph.add_run(
                    f"{_display(citation.get('filename'))}, PDF page {_display(citation.get('page'))}; "
                    f"source {_display(citation.get('source_id'))}; SHA-256 {_display(citation.get('document_sha256'))}" + (" [OCR-sourced]" if citation.get("ocr_sourced") else "")
                )
            quote = document.add_paragraph()
            quote.paragraph_format.left_indent = Inches(0.3)
            quote.add_run(f'Exact quote: "{_display(citation.get("quote"))}"')
        if answer.get("edit_history"):
            document.add_paragraph(f"Edit/review events: {len(answer['edit_history'])}")
        approval = answer.get("approval")
        document.add_paragraph("Approval: " + (_display(approval.get("approved_at")) if isinstance(approval, dict) else "Not approved"))

    if _display(record.get("form_id")) == "202":
        document.add_page_break()
        document.add_heading("Form 205 - Document Production Review", level=1)
        document.add_paragraph("Potential matches are search leads, not proof of production or attorney privilege determinations.")
        for number, request, item in _production_items(record):
            document.add_heading(f"205-{number}: {request}", level=2)
            document.add_paragraph(f"Reviewer status: {_display(item.get('status', 'REVIEW_REQUIRED'))}")
            document.add_paragraph(f"Draft response: {_production_response(item)}")
            document.add_paragraph(f"Bates claimed by reviewer: {_display(item.get('bates_range')) or '[None verified]'}")
            selected = set(item.get("selected_sources") or [])
            document.add_paragraph("Selected uploaded source IDs: " + (", ".join(sorted(selected)) or "None"))
            document.add_paragraph("Attorney notes: " + (_display(item.get("reviewer_notes")) or "None"))
            for candidate in item.get("candidates", []):
                document.add_paragraph(
                    f"Possible match only: {candidate.get('source_id')} - {candidate.get('filename')} | SHA-256 {candidate.get('sha256')}"
                )
                for passage in candidate.get("passages", []):
                    document.add_paragraph(
                        f"PDF page {passage.get('page')}; {passage.get('segment_id')}: {passage.get('quote')}"
                    )

    stream = BytesIO()
    document.save(stream)
    return stream.getvalue()


def export_case_pdf(record: dict) -> bytes:
    """Render a completed, official-form-style attorney review PDF."""
    stream = BytesIO()
    form = record["form"]
    metadata = record.get("metadata", {})
    form_id = _display(form.get("form_id", record.get("form_id", "")))
    title = _display(form.get("title", "Interrogatories"))
    sans, sans_bold = _register_pdf_fonts()
    styles = getSampleStyleSheet()
    body = ParagraphStyle(
        "LegalBody", parent=styles["BodyText"], fontName=sans, fontSize=9.5,
        leading=12.5, spaceAfter=5,
    )
    small = ParagraphStyle(
        "LegalSmall", parent=body, fontName=sans, fontSize=7.5, leading=9,
        textColor=colors.HexColor("#4a4a4a"),
    )
    question = ParagraphStyle(
        "Question", parent=body, fontName=sans, fontSize=9.5, leading=12.5,
        spaceBefore=5, spaceAfter=3,
    )
    response = ParagraphStyle(
        "Response", parent=body, fontName=sans, leftIndent=18, borderColor=colors.HexColor("#c7cbc9"),
        borderWidth=0.5, borderPadding=6, backColor=colors.HexColor("#f7f8f7"),
        spaceAfter=4,
    )
    warning_style = ParagraphStyle(
        "Warning", parent=styles["BodyText"], fontName=sans_bold, fontSize=9,
        leading=11, alignment=TA_CENTER, textColor=colors.HexColor("#8b1e1e"),
        borderColor=colors.HexColor("#8b1e1e"), borderWidth=0.75, borderPadding=6,
        spaceAfter=10,
    )

    def footer(canvas, document) -> None:
        canvas.saveState()
        canvas.setStrokeColor(colors.HexColor("#aeb3b0"))
        canvas.line(0.75 * inch, 0.52 * inch, 7.75 * inch, 0.52 * inch)
        canvas.setFont(sans, 7.5)
        canvas.setFillColor(colors.HexColor("#555555"))
        canvas.drawString(0.75 * inch, 0.34 * inch, f"Form {form_id} | Attorney Review Draft")
        canvas.drawRightString(7.75 * inch, 0.34 * inch, f"Page {document.page}")
        canvas.restoreState()

    pdf = SimpleDocTemplate(
        stream, pagesize=letter, leftMargin=0.75 * inch, rightMargin=0.75 * inch,
        topMargin=0.62 * inch, bottomMargin=0.68 * inch,
        title=f"Form {form_id} - {title}", author="Inquisitio",
    )
    story = [
        Paragraph(f"FORM {escape(form_id)}", ParagraphStyle("Form", parent=styles["Heading2"], fontName=sans, fontSize=9, alignment=TA_CENTER, spaceAfter=3)),
        Paragraph(escape(title), ParagraphStyle("Title", parent=styles["Heading1"], fontName=sans_bold, fontSize=12.5, leading=15, alignment=TA_CENTER, spaceAfter=10)),
    ]
    caption_rows = [
        [Paragraph(f"<b>No.</b> {escape(_display(metadata.get('docket_number')))}", body), Paragraph("<b>SUPERIOR COURT</b>", body)],
        [Paragraph(escape(_display(metadata.get("plaintiff"))) or "(Plaintiff)", body), Paragraph(f"<b>JUDICIAL DISTRICT OF</b> {escape(_display(metadata.get('judicial_district')))}", body)],
        [Paragraph("VS.", body), Paragraph(f"<b>AT</b> {escape(_display(metadata.get('court', form.get('court', ''))))}", body)],
        [Paragraph(escape(_display(metadata.get("defendant"))) or "(Defendant)", body), Paragraph(f"<b>DATE</b> {escape(_display(metadata.get('response_date')))}", body)],
    ]
    caption = Table(caption_rows, colWidths=[3.35 * inch, 3.65 * inch], hAlign="LEFT")
    caption.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"), ("LINEBELOW", (0, 0), (-1, -1), 0.35, colors.HexColor("#c2c6c3")),
        ("LEFTPADDING", (0, 0), (-1, -1), 5), ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.extend([
        caption, Spacer(1, 10),
        Paragraph("ATTORNEY REVIEW DRAFT - NOT FOR SERVICE", warning_style),
        Paragraph(
            f"The following responses correspond to Connecticut Practice Book Form {escape(form_id)}. "
            f"They were prepared from locally uploaded evidence for review by the responding party and counsel. "
            f"{escape(_display(form.get('deadline_text')))}", body,
        ),
        Paragraph(
            "If an interrogatory cannot be answered in full, the supported portion is stated and the unresolved information is identified. "
            "No response is final until expressly approved and verified.", body,
        ),
        Spacer(1, 5),
    ])

    answers = record.get("answers", {})
    last_number = None
    for item in form.get("items", []):
        blocks = []
        if item["number"] != last_number:
            last_number = item["number"]
            prompt = _display(item.get("prompt"))
            if prompt:
                blocks.append(Paragraph(f"<b>({item['number']})</b> {escape(prompt)}", question))
        label = _display(item.get("label"))
        if label:
            blocks.append(Paragraph(f"<b>({escape(label)})</b> {escape(_display(item.get('text')))}", question))
        elif not item.get("prompt"):
            blocks.append(Paragraph(f"<b>({item['number']})</b> {escape(_display(item.get('text')))}", question))

        answer = answers.get(item["item_id"], {})
        slot_status = _display(answer.get("status", "EMPTY"))
        marker = "" if slot_status == "APPROVED" else f"[REVIEW {slot_status}] "
        answer_text = marker + (_display(answer.get("answer")) or "[NO RESPONSE GENERATED - ATTORNEY REVIEW REQUIRED]")
        blocks.append(Paragraph(f"<b>RESPONSE:</b> {escape(answer_text)}", response))
        status = slot_status.replace("_", " ").title()
        details = f"Slot status: {status}"
        missing = answer.get("missing_information", [])
        if missing:
            details += " | Unresolved: " + ", ".join(map(_display, missing))
        blocks.append(Paragraph(escape(details), small))
        for conflict in answer.get("conflicts", []):
            blocks.append(Paragraph("<b>Conflict:</b> " + escape(_display(conflict.get("description"))), small))
        story.append(KeepTogether(blocks))
        seen_citations = set()
        for citation in answer.get("supporting_citations", []):
            key = (citation.get("filename"), citation.get("page"), citation.get("quote"))
            if key in seen_citations:
                continue
            seen_citations.add(key)
            label = _display(citation.get("citation_label")) if citation.get("citation_kind") == "case_record" else f"Source: {_display(citation.get('source_id'))} — {_display(citation.get('filename'))}, PDF page {_display(citation.get('page'))}"
            if citation.get("ocr_sourced"):
                label += " [OCR-sourced]"
            story.append(Paragraph("<b>" + escape(label) + "</b><br/>Exact source: " + escape(_display(citation.get("quote"))), small))

    if form_id == "202":
        story.append(PageBreak())
        story.append(Paragraph("Form 205 Defendant Requests for Production", ParagraphStyle("Production", parent=styles["Heading1"], fontName=sans_bold, fontSize=13, spaceAfter=8)))
        story.append(Paragraph("<b>ATTORNEY REVIEW DRAFT - NOT FOR SERVICE</b>", small))
        for number, request_text, production_item in _production_items(record):
            story.append(Paragraph(f"<b>({number})</b> {escape(request_text)}", question))
            story.append(Paragraph("<b>RESPONSE:</b> " + escape(_production_response(production_item)), body))

    story.extend([
        PageBreak(),
        Paragraph("Verification", ParagraphStyle("Verify", parent=styles["Heading1"], fontName=sans_bold, fontSize=13, spaceAfter=8)),
        Paragraph(
            "I, ______________________________, certify that I have reviewed these interrogatories and responses and that they are true and accurate to the best of my knowledge and belief.", body,
        ),
        Spacer(1, 24),
        Paragraph("Signature: ____________________________________    Date: __________________", body),
        Spacer(1, 20),
        Paragraph("Subscribed and sworn before me this ______ day of __________________, 20____.", body),
        Spacer(1, 20),
        Paragraph("Notary Public / Commissioner of the Superior Court: ____________________________________", body),
        Spacer(1, 18),
        Paragraph("Certification", ParagraphStyle("Cert", parent=styles["Heading1"], fontName=sans_bold, fontSize=13, spaceAfter=8)),
        Paragraph(
            "I certify that a copy of this document was or will immediately be mailed or delivered electronically or non-electronically to all attorneys and self-represented parties of record.", body,
        ),
        Spacer(1, 18),
        Paragraph("Recipients: __________________________________________________________________________", body),
        Spacer(1, 12),
        Paragraph("Filer signature: ______________________________    Date: __________________", body),
    ])
    pdf.build(story, onFirstPage=footer, onLaterPages=footer)
    return stream.getvalue()
