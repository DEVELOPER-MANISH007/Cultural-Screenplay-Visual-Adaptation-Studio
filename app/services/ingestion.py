"""Screenplay ingestion: turn TXT / DOCX / PDF / pasted text into clean raw text.

No AI, no network. The public ``extract_*`` functions never raise for bad
content: extraction problems become ``extraction_status="failed"`` documents.
The only exception is ``extract_text`` raising ``UnsupportedFileTypeError`` for
unsupported uploads, because no valid ``source_type`` exists for them.
"""

from __future__ import annotations

import codecs
import io
import re
from typing import Any, Callable, NamedTuple

from app.models.screenplay import ExtractionStatus, ScreenplayDocument, SourceType
from app.services.validators import validate_file_extension

# Marker inserted before each PDF page's text so page boundaries stay visible.
PAGE_MARKER_TEMPLATE = "----- Page {number} -----"
_PAGE_MARKER_RE = re.compile(r"^----- Page \d+ -----[ \t]*(?:\n|\Z)", re.MULTILINE)

_CONTROL_RE = re.compile(r"[\x00-\x08\x0e-\x1f\x7f]")  # keeps \t \n \v \f \r for handling
# Zero-width space, word joiner, BOM, soft hyphen. ZWJ/ZWNJ (U+200D/U+200C) are
# deliberately NOT removed: they are meaningful in Devanagari and other Indic scripts.
_INVISIBLE_RE = re.compile("[\u200b\u2060\ufeff\u00ad]")
_TRAILING_SPACE_RE = re.compile(r"[ \t]+$", re.MULTILINE)
_EXCESS_BLANK_RE = re.compile(r"\n{4,}")

DOCX_LOW_TEXT_WORDS = 20


class ExtractionError(Exception):
    """Raised by readers for expected, user-explainable extraction problems."""


class _Extraction(NamedTuple):
    text: str
    warnings: list[str]
    page_count: int | None = None


def normalize_text(text: str) -> str:
    """Remove obvious formatting noise while preserving screenplay line structure."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    for char in ("\x0b", "\x0c", "\u2028", "\u2029"):  # vertical tab, form feed, line/para sep
        text = text.replace(char, "\n")
    text = text.replace("\u00a0", " ")
    text = _CONTROL_RE.sub("", text)
    text = _INVISIBLE_RE.sub("", text)
    text = _TRAILING_SPACE_RE.sub("", text)
    text = _EXCESS_BLANK_RE.sub("\n\n\n", text)  # at most two blank lines in a row
    return text.strip("\n")


def strip_page_markers(text: str) -> str:
    """Remove the page-boundary markers added by PDF extraction."""
    return _PAGE_MARKER_RE.sub("", text)


def _build_document(
    source_type: SourceType,
    filename: str | None,
    extraction: _Extraction,
) -> ScreenplayDocument:
    warnings = list(extraction.warnings)
    body = strip_page_markers(extraction.text)
    if not body.strip() and not warnings:
        warnings.append("No text could be extracted.")
    return ScreenplayDocument(
        filename=filename,
        source_type=source_type,
        raw_text=extraction.text,
        character_count=len(body),
        word_count=len(body.split()),
        page_count=extraction.page_count,
        extraction_warnings=warnings,
        extraction_status=ExtractionStatus.WARNING if warnings else ExtractionStatus.SUCCESS,
    )


def _failed_document(
    source_type: SourceType, filename: str | None, message: str
) -> ScreenplayDocument:
    return ScreenplayDocument(
        filename=filename,
        source_type=source_type,
        raw_text="",
        extraction_warnings=[message],
        extraction_status=ExtractionStatus.FAILED,
    )


def _safe_extract(
    source_type: SourceType,
    filename: str | None,
    reader: Callable[[Any], _Extraction],
    content: bytes | str,
) -> ScreenplayDocument:
    """Run a reader and convert any failure into a ``failed`` document."""
    try:
        extraction = reader(content)
    except ExtractionError as exc:
        return _failed_document(source_type, filename, str(exc))
    except Exception as exc:  # noqa: BLE001 - extraction must never crash the app
        return _failed_document(
            source_type,
            filename,
            f"Unexpected error while reading the {source_type.value} input: "
            f"{type(exc).__name__}: {exc}",
        )
    return _build_document(source_type, filename, extraction)


# --------------------------------------------------------------------------- TXT


def _decode_bytes(data: bytes) -> tuple[str, list[str]]:
    if data.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        try:
            return data.decode("utf-16"), []
        except UnicodeDecodeError:
            pass
    if b"\x00" in data:
        raise ExtractionError(
            "The file appears to be binary, not plain text. Check that it really is a .txt file."
        )
    try:
        return data.decode("utf-8-sig"), []
    except UnicodeDecodeError:
        pass
    try:
        text = data.decode("cp1252")
        warning = "The file was not valid UTF-8; it was decoded as Windows-1252. Please check special characters."
    except UnicodeDecodeError:
        text = data.decode("utf-8", errors="replace")
        warning = (
            "The file was not valid UTF-8 and some bytes could not be decoded; "
            "they were replaced with \ufffd. Please check the text."
        )
    return text, [warning]


def _read_txt(content: bytes) -> _Extraction:
    text, warnings = _decode_bytes(content)
    return _Extraction(normalize_text(text), warnings)


def extract_txt(content: bytes, filename: str | None = None) -> ScreenplayDocument:
    """Extract text from the bytes of a .txt file."""
    return _safe_extract(SourceType.TXT, filename, _read_txt, content)


# -------------------------------------------------------------------------- DOCX


def _read_docx(content: bytes) -> _Extraction:
    from docx import Document  # imported lazily so TXT/paste work without it

    try:
        document = Document(io.BytesIO(content))
    except Exception as exc:  # noqa: BLE001 - corrupt zip, missing parts, etc.
        raise ExtractionError(
            "Could not open the file as a .docx document. It may be corrupt, empty, "
            f"or not a real .docx (for example an old .doc renamed). Details: {type(exc).__name__}."
        ) from exc

    text = normalize_text("\n".join(paragraph.text for paragraph in document.paragraphs))
    words = len(text.split())

    warnings: list[str] = []
    if words == 0:
        warnings.append("The document contains no extractable text.")
    elif words < DOCX_LOW_TEXT_WORDS:
        warnings.append(f"The document contains very little text ({words} words).")
    if document.tables:
        warnings.append(
            f"The document contains {len(document.tables)} table(s); table content is not extracted."
        )
    if document.inline_shapes:
        warnings.append(
            f"The document contains {len(document.inline_shapes)} embedded image(s); images are ignored."
        )
    return _Extraction(text, warnings)


def extract_docx(content: bytes, filename: str | None = None) -> ScreenplayDocument:
    """Extract paragraph text, in order, from the bytes of a .docx file."""
    return _safe_extract(SourceType.DOCX, filename, _read_docx, content)


# --------------------------------------------------------------------------- PDF


def _read_pdf(content: bytes) -> _Extraction:
    from pypdf import PdfReader  # imported lazily so TXT/paste work without it

    try:
        reader = PdfReader(io.BytesIO(content))
        if reader.is_encrypted and not reader.decrypt(""):
            raise ExtractionError("The PDF is password-protected and cannot be read.")
        pages = list(reader.pages)
    except ExtractionError:
        raise
    except Exception as exc:  # noqa: BLE001 - invalid/corrupt PDF structure
        raise ExtractionError(
            f"Could not open the file as a PDF. It may be corrupt or not a real PDF. "
            f"Details: {type(exc).__name__}."
        ) from exc

    warnings: list[str] = []
    parts: list[str] = []
    has_text = False
    for number, page in enumerate(pages, start=1):
        marker = PAGE_MARKER_TEMPLATE.format(number=number)
        try:
            page_text = normalize_text(page.extract_text() or "")
        except Exception as exc:  # noqa: BLE001 - one bad page should not lose the rest
            warnings.append(f"Page {number} could not be read ({type(exc).__name__}).")
            parts.append(marker)
            continue
        if page_text.strip():
            has_text = True
            parts.append(f"{marker}\n{page_text}")
        else:
            warnings.append(
                f"Page {number} contains no extractable text (it may be scanned or image-only)."
            )
            parts.append(marker)

    if not has_text:
        warnings.append(
            "No extractable text was found in this PDF. It may be scanned; OCR is not supported."
        )
        return _Extraction("", warnings, len(pages))
    return _Extraction("\n\n".join(parts), warnings, len(pages))


def extract_pdf(content: bytes, filename: str | None = None) -> ScreenplayDocument:
    """Extract text page by page from the bytes of a .pdf file."""
    return _safe_extract(SourceType.PDF, filename, _read_pdf, content)


# ------------------------------------------------------------------- pasted text


def extract_pasted_text(text: str, filename: str | None = None) -> ScreenplayDocument:
    """Build a ScreenplayDocument from text pasted directly by the user."""
    return _safe_extract(
        SourceType.PASTED_TEXT,
        filename,
        lambda value: _Extraction(normalize_text(value), []),
        text,
    )


# ---------------------------------------------------------------------- dispatch


def extract_text(source: str | bytes, filename: str | None = None) -> ScreenplayDocument:
    """Extract a screenplay from pasted text (``str``) or an uploaded file (``bytes``).

    For ``bytes`` the file type is chosen from the extension of ``filename``.

    Raises:
        UnsupportedFileTypeError: unsupported or missing file extension.
        TypeError: ``source`` is neither ``str`` nor ``bytes``.
    """
    if isinstance(source, str):
        return extract_pasted_text(source, filename)
    if isinstance(source, (bytes, bytearray)):
        source_type = validate_file_extension(filename)
        data = bytes(source)
        if source_type == SourceType.TXT:
            return extract_txt(data, filename)
        if source_type == SourceType.DOCX:
            return extract_docx(data, filename)
        return extract_pdf(data, filename)
    raise TypeError(f"source must be str or bytes, not {type(source).__name__}")
