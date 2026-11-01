from __future__ import annotations

import hashlib
import re
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path

import fitz
import pdfplumber
from pypdf import PdfReader, PdfWriter


@dataclass(frozen=True)
class EvidenceSegment:
    segment_id: str
    source_id: str
    filename: str
    page: int
    text: str
    kind: str
    bbox: tuple[float, ...] = ()
    extraction_method: str = "pdfplumber"
    ocr_sourced: bool = False
    cells: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class EvidenceDocument:
    source_id: str
    filename: str
    sha256: str
    pages: int
    extraction_status: str
    segments: tuple[EvidenceSegment, ...]
    extraction_errors: tuple[dict, ...] = ()
    page_methods: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        value = asdict(self)
        value["segments"] = [segment.to_dict() for segment in self.segments]
        return value


def _fragmented(text: str) -> bool:
    lines = [x.strip() for x in text.splitlines() if x.strip()]
    return bool(len(lines) > 5 and sum(len(x) <= 3 for x in lines) / len(lines) > .35)


def _out_of_order(page) -> bool:
    words = page.extract_words(use_text_flow=True)
    return any(b["top"] + 8 < a["top"] for a, b in zip(words, words[1:]))


def _pymupdf_lines(page) -> list:
    pieces = []
    for block in page.get_text("dict")["blocks"]:
        for line in block.get("lines", []):
            text = "".join(span["text"] for span in line["spans"]).strip()
            if text:
                pieces.append((text, tuple(line["bbox"])))
    rows = []
    for text, box in sorted(pieces, key=lambda p: (round(p[1][1], 1), p[1][0])):
        if rows and abs(rows[-1][0][1][1] - box[1]) <= 3:
            rows[-1].append((text, box))
        else:
            rows.append([(text, box)])
    result = []
    for row in rows:
        row.sort(key=lambda p: p[1][0])
        cells = tuple(p[0] for p in row)
        box = (min(p[1][0] for p in row), min(p[1][1] for p in row), max(p[1][2] for p in row), max(p[1][3] for p in row))
        result.append(("\t".join(cells), box, cells if len(cells) > 1 else ()))
    return result


def _layout_lines(page) -> list[tuple[str, tuple[float, ...], tuple[str, ...]]]:
    """Retain short values, physical rows, and table cells; never split sentences."""
    tables = [t for t in page.find_tables() if len(t.rows) > 1 and len(t.rows[0].cells) > 1]
    entries = []
    for table in tables:
        for row, values in zip(table.rows, table.extract()):
            cells = tuple((v or "").strip() for v in values)
            if any(cells):
                entries.append(("\t".join(cells), tuple(row.bbox), cells))
    words = page.extract_words(x_tolerance=2, y_tolerance=3, use_text_flow=False)
    rows: list[list[dict]] = []
    for word in sorted(words, key=lambda w: (round(w["top"], 1), w["x0"])):
        if any(t.bbox[0] <= word["x0"] < t.bbox[2] and t.bbox[1] <= word["top"] < t.bbox[3] for t in tables):
            continue
        if rows and abs(rows[-1][0]["top"] - word["top"]) <= 3:
            rows[-1].append(word)
        else:
            rows.append([word])
    for row in rows:
        row.sort(key=lambda w: w["x0"])
        box = (min(w["x0"] for w in row), min(w["top"] for w in row), max(w["x1"] for w in row), max(w["bottom"] for w in row))
        entries.append((" ".join(w["text"] for w in row), box, ()))
    return sorted(entries, key=lambda x: (round(x[1][1], 1), x[1][0]))


def _ocr_page(reader: PdfReader, index: int, raster_page, errors: list[dict], force: bool = False) -> tuple[list, str]:
    """OCRmyPDF first; local pytesseract fallback. Errors remain in the matter."""
    try:
        import ocrmypdf
        with tempfile.TemporaryDirectory(prefix="inquisitio-ocr-") as directory:
            source, result = Path(directory) / "source.pdf", Path(directory) / "searchable.pdf"
            writer = PdfWriter()
            writer.add_page(reader.pages[index])
            writer.write(source)
            ocrmypdf.ocr(source, result, output_type="pdf", optimize=0, jobs=1,
                         use_threads=True, progress_bar=False, tesseract_timeout=45, force_ocr=force)
            with pdfplumber.open(result) as pdf:
                lines = _layout_lines(pdf.pages[0])
            if lines:
                return lines, "ocrmypdf"
    except Exception as exc:
        errors.append({"page": index + 1, "method": "ocrmypdf", "error": f"{type(exc).__name__}: {exc}"})
    try:
        import pytesseract
        from PIL import Image
        pix = raster_page.get_pixmap(matrix=fitz.Matrix(3, 3))
        img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
        data = pytesseract.image_to_data(img, config="--psm 6", output_type=pytesseract.Output.DICT, timeout=45)
        groups: dict[tuple, list[int]] = {}
        for i, word in enumerate(data["text"]):
            if word.strip():
                groups.setdefault(tuple(data[k][i] for k in ("block_num", "par_num", "line_num")), []).append(i)
        lines = []
        for indices in groups.values():
            x0 = min(data["left"][i] for i in indices) / 3
            y0 = min(data["top"][i] for i in indices) / 3
            x1 = max(data["left"][i] + data["width"][i] for i in indices) / 3
            y1 = max(data["top"][i] + data["height"][i] for i in indices) / 3
            lines.append((" ".join(data["text"][i] for i in indices), (x0, y0, x1, y1), ()))
        return lines, "pytesseract"
    except Exception as exc:
        errors.append({"page": index + 1, "method": "pytesseract", "error": f"{type(exc).__name__}: {exc}"})
        return [], "OCR_FAILED"


def extract_pdf(path: Path, source_id: str, display_name: str | None = None) -> EvidenceDocument:
    path = Path(path)
    reader = PdfReader(path)
    segments: list[EvidenceSegment] = []
    errors: list[dict] = []
    methods: list[str] = []
    failed = False
    with pdfplumber.open(path) as pdf, fitz.open(path) as layout_pdf:
        for index, page in enumerate(pdf.pages):
            method = "pdfplumber"
            ocr = False
            extra_entries = []
            raw = page.extract_text(layout=False) or ""
            try:
                lines = _layout_lines(page)
            except Exception as exc:
                errors.append({"page": index + 1, "method": method, "error": f"{type(exc).__name__}: {exc}"})
                lines = []
            if _fragmented(raw) or not lines or _out_of_order(page):
                fallback = _pymupdf_lines(layout_pdf[index])
                if fallback:
                    lines, method = fallback, "pymupdf_layout"
            fields = []
            for ref in reader.pages[index].get("/Annots", []):
                obj = ref.get_object()
                if obj.get("/Subtype") != "/Widget":
                    continue
                parent = obj.get("/Parent")
                parent = parent.get_object() if parent else obj
                name = obj.get("/TU") or parent.get("/TU") or obj.get("/T") or parent.get("/T", "")
                val = obj.get("/V", parent.get("/V", ""))
                if name and val and str(val) != "/Off":
                    rect = tuple(float(x) for x in obj.get("/Rect", ()))
                    box = (rect[0], page.height - rect[3], rect[2], page.height - rect[1]) if rect else ()
                    fields.append((f"{name}: {val}", box, "pypdf_form"))
            if not lines and not fields and page.images:
                lines, method = _ocr_page(reader, index, layout_pdf[index], errors)
                ocr = True
                failed |= not bool(lines)
            elif not lines and not fields:
                failed = True
            elif page.images:
                # A printed label plus a scanned entry is not an image-only
                # page. OCR that page too, but add only the missing field's
                # nearby image text, retaining the reliable native text.
                label_pattern = r'(Patient(?: Name)?|Full Name|Name|DOB|Date of Birth|Address|Residence|(?:Operator )?License(?: No\.)?)'
                blanks = [(re.match(r'^' + label_pattern + r'\s*[:_]+\s*$', t, re.I), box) for t,box,_ in lines]
                blanks = [(m,box) for m,box in blanks if m and box]
                if blanks:
                    ocr_lines, ocr_method = _ocr_page(reader, index, layout_pdf[index], errors, force=True)
                    for text, box, cells in ocr_lines:
                        detected_label = re.match(r'^' + label_pattern + r'\s*:', text, re.I)
                        nearby = next(((m,b) for m,b in blanks if abs(box[1]-b[1]) <= 24 and
                            (not detected_label or detected_label[1].casefold() == m[1].casefold())
                            ), None)
                        if nearby:
                            # Trust the readable native label, not its OCR
                            # spelling. Preserve the OCR transcription in text.
                            value = text.split(":", 1)[-1].strip()
                            extra_entries.append((text, box, (nearby[0][1], value), ocr_method, True))
                    failed |= ocr_method == "OCR_FAILED"
            methods.append(method + ("+" + extra_entries[0][3] if extra_entries else ""))
            entries = [(text, box, cells, method, ocr) for text, box, cells in lines]
            entries += [(text, box, (), field_method, False) for text, box, field_method in fields]
            entries += extra_entries
            entries.sort(key=lambda e: (e[1][1], e[1][0]) if e[1] else (0,0))
            for ordinal, (text, box, cells, segment_method, from_ocr) in enumerate(entries, 1):
                if not text.strip():
                    continue
                segments.append(EvidenceSegment(
                    f"{source_id}:p{index + 1}:s{ordinal}", source_id,
                    display_name or path.name, index + 1, text.strip(),
                    "form_field" if segment_method == "pypdf_form" else "table" if cells else "text",
                    box, segment_method, from_ocr, cells,
                ))
    status = "NO_TEXT_OCR_REQUIRED" if not segments else "PARTIAL_EXTRACTION" if failed else "TEXT_EXTRACTED"
    return EvidenceDocument(source_id, display_name or path.name, hashlib.sha256(path.read_bytes()).hexdigest(),
                            len(reader.pages), status, tuple(segments), tuple(errors), tuple(methods))
