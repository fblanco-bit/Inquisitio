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


def _load_firm_profile(form_id: str) -> dict | None:
    """Load the firm's house-format profile for a form, if one is installed.

    The profile is plain data (data/firm_profile_<form_id>.json): intro wording,
    per-question fallback answers (Filevine merge fields and the firm's stock
    answers), signature block, and verification/certification text. Fallbacks
    are template text supplied by the firm, never evidence claims, and every
    judgment-call fallback is tagged [ATTORNEY REVIEW: ...]. Deleting the file
    restores the generic export. The engine never reads this file.
    """
    import json
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    path = root / "data" / f"firm_profile_{form_id}.json"
    if not path.exists():
        return None
    try:
        with open(path, encoding="utf-8") as handle:
            profile = json.load(handle)
    except (OSError, ValueError):
        return None
    return profile if isinstance(profile, dict) else None


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


def _legal_answer(value: object, fallback: str | None = None) -> str:
    text = _display(value).strip()
    if not text:
        return fallback if fallback else "[No response entered - attorney review required.]"
    normalized = text.rstrip(". ").lower()
    if normalized == "yes":
        return "Yes."
    if normalized == "no":
        return "No."
    if normalized in {"n/a", "not applicable"}:
        return "N/A."
    return text


def _add_answer_paragraph(document: Document, label: str, answer: object, fallback: str | None = None) -> None:
    paragraph = document.add_paragraph(style="Interrogatory Answer")
    paragraph.paragraph_format.tab_stops.add_tab_stop(Inches(1.25))
    paragraph.add_run(label).bold = True
    paragraph.add_run("\t" + _legal_answer(answer, fallback)).bold = True


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
    profile = _load_firm_profile(form_id)
    if profile:
        for key in ("intro", "definition", "instruction"):
            text = _display(profile.get(key)).strip()
            if text:
                paragraph = document.add_paragraph(style="Pleading Introduction")
                paragraph.add_run(text)
    else:
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
        fallback = profile.get("fallback_answers", {}).get(item["item_id"]) if profile else None
        _add_answer_paragraph(document, "ANSWER:", answer.get("answer"), fallback)

    if form_id == "202":
        document.add_page_break()
        production_heading = document.add_paragraph()
        production_heading.alignment = WD_ALIGN_PARAGRAPH.CENTER
        production_heading.paragraph_format.space_after = Pt(14)
        run = production_heading.add_run("REQUESTS FOR PRODUCTION")
        run.bold = True
        run.underline = True
        run.font.size = Pt(12)
        if profile:
            for key in ("production_intro", "production_instruction"):
                text = _display(profile.get(key)).strip()
                if text:
                    document.add_paragraph(text, style="Pleading Introduction")
        else:
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
            human_response = _display(production_item.get("response", "")).strip()
            production_fallback = profile.get("production_fallbacks", {}).get(f"205-{number}") if profile else None
            _add_answer_paragraph(
                document, "RESPONSE:",
                human_response or None,
                production_fallback or "[Production response not verified - attorney review required.]",
            )

    if profile and profile.get("signature_block"):
        document.add_paragraph()
        for line in profile["signature_block"]:
            document.add_paragraph(_display(line))

    document.add_page_break()
    verification = document.add_paragraph(style="Title")
    verification.alignment = WD_ALIGN_PARAGRAPH.CENTER
    verification.add_run(_display(profile.get("verification_title")) if profile else "VERIFICATION PAGE")
    document.add_paragraph(
        (_display(profile.get("verification_text")) if profile else
         "I hereby certify that I have reviewed the above interrogatories and responses and that they are true and "
         "accurate to the best of my knowledge and belief."), style="Pleading Introduction",
    )
    if profile:
        document.add_paragraph("____________________________________")
        document.add_paragraph(_display(profile.get("verification_signatory")) or party)
        document.add_paragraph()
        document.add_paragraph(_display(profile.get("verification_sworn_line")))
        document.add_paragraph()
        document.add_paragraph("____________________________________")
        document.add_paragraph(_display(profile.get("verification_officer_line")))
    else:
        document.add_paragraph(f"{party}\n\nBy: ____________________________________    Date: __________________")
        document.add_paragraph("Subscribed and sworn before me this ______ day of __________________, 20____.")
        document.add_paragraph("Commissioner of the Superior Court: __________________________________________")
    document.add_page_break()
    certification = document.add_paragraph(style="Title")
    certification.alignment = WD_ALIGN_PARAGRAPH.CENTER
    certification.add_run(_display(profile.get("certification_title")) if profile else "CERTIFICATION")
    document.add_paragraph(
        (_display(profile.get("certification_text")) if profile else
         "I certify that a copy of this document was or will immediately be mailed or delivered electronically or "
         "non-electronically to all attorneys and self-represented parties of record."), style="Pleading Introduction",
    )
    if profile:
        document.add_paragraph()
        document.add_paragraph("____________________________________")
        document.add_paragraph(_display(profile.get("certification_signatory")))
    else:
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
    """Render the Completed-form PDF as a final, filing-style document.

    WR-012 (Freddy, 1 Nov 2026): this output alone is the finished paper and
    follows Connecticut filing conventions - Times Roman, a colon caption,
    centered underlined title, numbered questions with plain ANSWER text, a
    signature block, and a STATE OF CONNECTICUT notary block. It carries no
    review apparatus: no status tags, no brackets, no citations, no internal
    notes. An unanswered question shows a blank answer line. While any answer
    is still unapproved, a draft banner and footer note remain; a fully
    approved matter renders clean. Formatting conventions only were taken
    from the sample filing Freddy supplied; none of its content.
    """
    stream = BytesIO()
    form = record["form"]
    metadata = record.get("metadata", {})
    form_id = _display(form.get("form_id", record.get("form_id", "")))
    profile = _load_firm_profile(form_id)
    answers = record.get("answers", {})
    items = form.get("items", [])
    fully_approved = bool(items) and all(
        answers.get(item["item_id"], {}).get("status") == "APPROVED" for item in items
    )

    styles = getSampleStyleSheet()
    body = ParagraphStyle("FilingBody", parent=styles["BodyText"], fontName="Times-Roman",
                          fontSize=12, leading=16, spaceAfter=10)
    intro = ParagraphStyle("FilingIntro", parent=body, firstLineIndent=30)
    question = ParagraphStyle("FilingQuestion", parent=body, spaceBefore=8, spaceAfter=4)
    subpart = ParagraphStyle("FilingSubpart", parent=question, leftIndent=24)
    answer_style = ParagraphStyle("FilingAnswer", parent=body, leftIndent=48, spaceAfter=12)
    title_style = ParagraphStyle("FilingTitle", parent=styles["Heading1"], fontName="Times-Bold",
                                 fontSize=12, leading=15, alignment=TA_CENTER, spaceBefore=16, spaceAfter=14)
    warning_style = ParagraphStyle("FilingWarning", parent=body, fontName="Times-Bold",
                                   alignment=TA_CENTER, textColor=colors.HexColor("#8b1e1e"), spaceAfter=12)

    def footer(canvas, document) -> None:
        canvas.saveState()
        canvas.setFont("Times-Roman", 11)
        canvas.setFillColor(colors.black)
        canvas.drawCentredString(4.25 * inch, 0.5 * inch, str(document.page))
        if not fully_approved:
            canvas.setFont("Times-Roman", 8)
            canvas.setFillColor(colors.HexColor("#8b1e1e"))
            canvas.drawString(1.0 * inch, 0.5 * inch, "DRAFT - ATTORNEY REVIEW PENDING")
        canvas.restoreState()

    pdf = SimpleDocTemplate(
        stream, pagesize=letter, leftMargin=1.0 * inch, rightMargin=1.0 * inch,
        topMargin=1.0 * inch, bottomMargin=0.9 * inch,
        title=f"Form {form_id} Responses", author="Inquisitio",
    )

    def caps(value: object) -> str:
        return escape(_display(value).upper())

    caption_rows = [
        [Paragraph(f"DOCKET NO. {caps(metadata.get('docket_number'))}", body), Paragraph(":", body), Paragraph("SUPERIOR COURT", body)],
        [Paragraph(caps(metadata.get("plaintiff")) or "PLAINTIFF", body), Paragraph(":", body), Paragraph(f"J.D. OF {caps(metadata.get('judicial_district'))}", body)],
        [Paragraph("VS.", body), Paragraph(":", body), Paragraph(f"AT {caps(metadata.get('court', form.get('court', '')))}", body)],
        [Paragraph(caps(metadata.get("defendant")) or "DEFENDANT", body), Paragraph(":", body), Paragraph(caps(metadata.get("response_date")), body)],
    ]
    caption = Table(caption_rows, colWidths=[3.3 * inch, 0.5 * inch, 2.7 * inch], hAlign="LEFT")
    caption.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ALIGN", (1, 0), (1, -1), "CENTER"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story = [caption, Spacer(1, 6)]
    if not fully_approved:
        story.append(Paragraph("ATTORNEY REVIEW DRAFT - NOT FOR SERVICE", warning_style))
    story.append(Paragraph("<u>" + escape(_response_title(record).replace("\n", " ")) + "</u>", title_style))

    intro_texts = []
    if profile:
        intro_texts = [profile.get("intro", ""), profile.get("definition", ""), profile.get("instruction", "")]
    else:
        intro_texts = [
            f"The undersigned submits the following responses of {_display(_responding_party(record))} to "
            f"Connecticut Practice Book Form {form_id}, {form.get('title', 'Interrogatories')}.",
        ]
    for text in intro_texts:
        if _display(text).strip():
            story.append(Paragraph(escape(_display(text)), intro))

    def answer_text(item_id: str) -> str:
        return _display(answers.get(item_id, {}).get("answer", "")).strip()

    last_number = None
    for item in items:
        if item["number"] != last_number:
            last_number = item["number"]
            prompt = _display(item.get("prompt"))
            if prompt:
                story.append(Paragraph(f"{item['number']}. {escape(prompt)}", question))
        label = _display(item.get("label"))
        if label:
            story.append(Paragraph(f"({escape(label)}) {escape(_display(item.get('text')))}", subpart))
        elif not item.get("prompt"):
            story.append(Paragraph(f"{item['number']}. {escape(_display(item.get('text')))}", question))
        text = answer_text(item["item_id"])
        rendered = escape(text) if text else "_" * 60
        story.append(Paragraph(f"<b>ANSWER:</b> {rendered}", answer_style))

    if form_id == "202":
        story.append(Spacer(1, 10))
        story.append(Paragraph("<u>REQUESTS FOR PRODUCTION</u>", title_style))
        if profile:
            for key in ("production_intro", "production_instruction"):
                if _display(profile.get(key)).strip():
                    story.append(Paragraph(escape(_display(profile.get(key))), intro))
        for number, request, production_item in _production_items(record):
            story.append(Paragraph(f"{number}. {escape(request)}", question))
            response = _display(production_item.get("response", "")).strip()
            story.append(Paragraph("<b>RESPONSE:</b> " + (escape(response) if response else "_" * 58), answer_style))

    if profile and profile.get("signature_block"):
        story.append(Spacer(1, 18))
        for line in profile["signature_block"]:
            story.append(Paragraph(escape(_display(line)), ParagraphStyle("Sig", parent=body, leftIndent=3.2 * inch, spaceAfter=2)))

    party = _responding_party(record)
    story.extend([
        PageBreak(),
        Paragraph("<u>VERIFICATION</u>", title_style),
        Paragraph(escape(_display(profile.get("verification_text")) if profile else
                         "I hereby certify that I have reviewed the above interrogatories and responses and that "
                         "they are true and accurate to the best of my knowledge and belief."), intro),
        Spacer(1, 30),
        Paragraph("____________________________________", ParagraphStyle("VSig", parent=body, leftIndent=3.2 * inch)),
        Paragraph(escape(_display(profile.get("verification_signatory")) if profile else party) or escape(party),
                  ParagraphStyle("VName", parent=body, leftIndent=3.2 * inch)),
        Spacer(1, 18),
        Paragraph("STATE OF CONNECTICUT&nbsp;&nbsp;&nbsp;&nbsp;)", ParagraphStyle("Notary1", parent=body, spaceAfter=0)),
        Paragraph("&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;"
                  "&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;)"
                  "&nbsp;&nbsp;&nbsp;&nbsp;ss.:", ParagraphStyle("Notary2", parent=body, spaceAfter=0)),
        Paragraph("COUNTY OF ____________&nbsp;&nbsp;)", body),
        Spacer(1, 12),
        Paragraph(escape(_display(profile.get("verification_sworn_line")) if profile else
                         "SUBSCRIBED AND SWORN TO before me this ____ day of ______________, 20____."), body),
        Spacer(1, 30),
        Paragraph("____________________________________", ParagraphStyle("NSig", parent=body, leftIndent=3.2 * inch)),
        Paragraph(escape(_display(profile.get("verification_officer_line")) if profile else
                         "Notary Public / Commissioner of the Superior Court"),
                  ParagraphStyle("NName", parent=body, leftIndent=3.2 * inch)),
        Spacer(1, 26),
        Paragraph("<u>CERTIFICATION</u>", title_style),
        Paragraph(escape(_display(profile.get("certification_text")) if profile else
                         "I certify that a copy of this document was or will immediately be mailed or delivered "
                         "electronically or non-electronically to all attorneys and self-represented parties of record."), intro),
        Spacer(1, 30),
        Paragraph("____________________________________", ParagraphStyle("CSig", parent=body, leftIndent=3.2 * inch)),
        Paragraph(escape(_display(profile.get("certification_signatory")) if profile else "") or "&nbsp;",
                  ParagraphStyle("CName", parent=body, leftIndent=3.2 * inch)),
    ])
    pdf.build(story, onFirstPage=footer, onLaterPages=footer)
    return stream.getvalue()
