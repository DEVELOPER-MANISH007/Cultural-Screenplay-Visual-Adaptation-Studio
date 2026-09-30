"""Phase 1 tests: screenplay ingestion (no network, no LLM)."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.models.screenplay import ExtractionStatus, ScreenplayDocument, SourceType
from app.services import ingestion
from app.services.ingestion import (
    PAGE_MARKER_TEMPLATE,
    extract_docx,
    extract_pasted_text,
    extract_pdf,
    extract_text,
    extract_txt,
    normalize_text,
    strip_page_markers,
)
from app.services.validators import UnsupportedFileTypeError
from tests.factories import make_docx, make_pdf

SCENE = [
    "INT. KITCHEN - DAY",
    "",
    "ASHA stirs a pot of dal while RAVI reads the newspaper.",
    "",
    "ASHA",
    "Chai banau ya nahi?",
]
SCENE_TEXT = "\n".join(SCENE)


# ----------------------------------------------------------------- model


def test_screenplay_document_can_be_created() -> None:
    document = ScreenplayDocument(source_type="pasted_text", raw_text="hello world")
    assert document.source_type == SourceType.PASTED_TEXT
    assert document.extraction_status == ExtractionStatus.SUCCESS
    assert document.filename is None
    assert document.page_count is None
    assert document.extraction_warnings == []
    assert document.document_id


def test_screenplay_document_rejects_invalid_values() -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        ScreenplayDocument(source_type="rtf")  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        ScreenplayDocument()  # type: ignore[call-arg]
    with pytest.raises(ValidationError):
        ScreenplayDocument(source_type="txt", word_count=-1)


# ----------------------------------------------------------------- TXT


def test_txt_extraction_preserves_line_structure(tmp_path: Path) -> None:
    path = tmp_path / "scene.txt"
    path.write_bytes(SCENE_TEXT.encode("utf-8"))
    document = extract_txt(path.read_bytes(), path.name)
    assert document.source_type == SourceType.TXT
    assert document.filename == "scene.txt"
    assert document.raw_text == SCENE_TEXT
    assert document.word_count == len(SCENE_TEXT.split())
    assert document.character_count == len(SCENE_TEXT)
    assert document.page_count is None
    assert document.extraction_status == ExtractionStatus.SUCCESS
    assert document.extraction_warnings == []


def test_txt_windows_line_endings_and_bom_are_normalized() -> None:
    data = b"\xef\xbb\xbfINT. ROOM - DAY\r\nAsha waits.\r\n"
    document = extract_txt(data, "a.txt")
    assert document.raw_text == "INT. ROOM - DAY\nAsha waits."


def test_txt_latin1_style_bytes_fall_back_with_warning() -> None:
    document = extract_txt("caf\u00e9 scene begins here now".encode("cp1252"), "a.txt")
    assert "caf\u00e9" in document.raw_text
    assert document.extraction_status == ExtractionStatus.WARNING
    assert any("Windows-1252" in w for w in document.extraction_warnings)


def test_txt_undecodable_bytes_are_replaced_with_warning() -> None:
    document = extract_txt(b"hello \x81 world", "a.txt")
    assert "\ufffd" in document.raw_text
    assert document.extraction_status == ExtractionStatus.WARNING


def test_txt_utf16_with_bom_is_decoded() -> None:
    document = extract_txt("INT. ROOM - DAY".encode("utf-16"), "a.txt")
    assert document.raw_text == "INT. ROOM - DAY"


def test_empty_txt_gives_warning_not_crash() -> None:
    document = extract_txt(b"", "empty.txt")
    assert document.raw_text == ""
    assert document.word_count == 0
    assert document.extraction_status == ExtractionStatus.WARNING
    assert document.extraction_warnings


# ----------------------------------------------------------------- DOCX


def test_docx_extraction_in_paragraph_order(tmp_path: Path) -> None:
    path = tmp_path / "scene.docx"
    path.write_bytes(make_docx(SCENE))
    document = extract_docx(path.read_bytes(), path.name)
    assert document.source_type == SourceType.DOCX
    assert document.raw_text == SCENE_TEXT
    assert document.extraction_status == ExtractionStatus.SUCCESS
    assert document.word_count == len(SCENE_TEXT.split())


def test_docx_with_no_text_warns() -> None:
    document = extract_docx(make_docx([]), "blank.docx")
    assert document.raw_text == ""
    assert document.extraction_status == ExtractionStatus.WARNING
    assert any("no extractable text" in w for w in document.extraction_warnings)


def test_docx_with_very_little_text_warns() -> None:
    document = extract_docx(make_docx(["INT. ROOM - DAY"]), "tiny.docx")
    assert document.extraction_status == ExtractionStatus.WARNING
    assert any("very little text" in w for w in document.extraction_warnings)


def test_docx_tables_are_flagged_as_not_extracted() -> None:
    document = extract_docx(make_docx(SCENE, with_table=True), "t.docx")
    assert any("table" in w for w in document.extraction_warnings)


# ----------------------------------------------------------------- PDF


def test_pdf_extraction_page_by_page_with_markers(tmp_path: Path) -> None:
    path = tmp_path / "script.pdf"
    path.write_bytes(make_pdf([["INT. KITCHEN - DAY", "Asha stirs the dal."], ["EXT. STREET - NIGHT"]]))
    document = extract_pdf(path.read_bytes(), path.name)
    assert document.source_type == SourceType.PDF
    assert document.page_count == 2
    assert PAGE_MARKER_TEMPLATE.format(number=1) in document.raw_text
    assert PAGE_MARKER_TEMPLATE.format(number=2) in document.raw_text
    assert "INT. KITCHEN - DAY\nAsha stirs the dal." in document.raw_text
    assert document.raw_text.index("KITCHEN") < document.raw_text.index("STREET")
    assert document.extraction_warnings == []
    assert document.extraction_status == ExtractionStatus.SUCCESS


def test_pdf_counts_exclude_page_markers() -> None:
    document = extract_pdf(make_pdf([["one two three"], ["four five"]]), "a.pdf")
    assert document.word_count == 5
    assert document.character_count == len(strip_page_markers(document.raw_text))


def test_pdf_page_without_text_records_warning() -> None:
    document = extract_pdf(make_pdf([["INT. ROOM - DAY", "Asha waits."], [], ["EXT. ROAD - DAY"]]), "a.pdf")
    assert document.page_count == 3
    assert document.extraction_status == ExtractionStatus.WARNING
    assert any(w.startswith("Page 2 contains no extractable text") for w in document.extraction_warnings)
    assert not any(w.startswith("Page 1") or w.startswith("Page 3") for w in document.extraction_warnings)
    assert PAGE_MARKER_TEMPLATE.format(number=2) in document.raw_text  # boundary kept
    assert "EXT. ROAD - DAY" in document.raw_text


def test_pdf_with_no_text_at_all_has_empty_raw_text() -> None:
    document = extract_pdf(make_pdf([[], []]), "scan.pdf")
    assert document.raw_text == ""
    assert document.word_count == 0
    assert document.page_count == 2
    assert any("OCR" in w for w in document.extraction_warnings)


def test_strip_page_markers() -> None:
    text = f"{PAGE_MARKER_TEMPLATE.format(number=1)}\nHello\n\n{PAGE_MARKER_TEMPLATE.format(number=2)}"
    assert strip_page_markers(text).strip() == "Hello"


# ------------------------------------------------------------ pasted text


def test_pasted_text_extraction() -> None:
    document = extract_pasted_text(SCENE_TEXT)
    assert document.source_type == SourceType.PASTED_TEXT
    assert document.filename is None
    assert document.raw_text == SCENE_TEXT
    assert document.extraction_status == ExtractionStatus.SUCCESS


@pytest.mark.parametrize("text", ["", "   ", "\n\n\t\n"])
def test_empty_pasted_text_yields_empty_document(text: str) -> None:
    document = extract_pasted_text(text)
    assert document.raw_text == ""
    assert document.word_count == 0
    assert document.extraction_status == ExtractionStatus.WARNING


# ----------------------------------------------------------- normalization


def test_normalize_text_removes_noise_but_keeps_structure() -> None:
    raw = "\ufeffINT. ROOM\r\n  ASHA  \u00a0\r\n\x00Line\u200b two\r\n\r\n\r\n\r\n\r\nNext\x0cPage"
    assert normalize_text(raw) == "INT. ROOM\n  ASHA\nLine two\n\n\nNext\nPage"


def test_normalize_text_keeps_leading_indentation() -> None:
    assert normalize_text("            ASHA\n   (softly)\n") == "            ASHA\n   (softly)"


# ---------------------------------------------------------------- Unicode


DEVANAGARI = "\u0926\u0943\u0936\u094d\u092f 1: \u0930\u0938\u094b\u0908 - \u0926\u093f\u0928\n\u0906\u0936\u093e: \u091a\u093e\u092f \u092c\u0928\u093e\u090a\u0901?"
HINGLISH = "ASHA\nArre yaar, kal ka plan kya hai? Chai peene chalein?"


@pytest.mark.parametrize("text", [DEVANAGARI, HINGLISH, DEVANAGARI + "\n" + HINGLISH])
def test_unicode_survives_every_source_type(text: str) -> None:
    assert extract_pasted_text(text).raw_text == text
    assert extract_txt(text.encode("utf-8"), "u.txt").raw_text == text
    assert extract_docx(make_docx(text.split("\n")), "u.docx").raw_text == text


def test_devanagari_word_and_character_counts() -> None:
    document = extract_pasted_text(DEVANAGARI)
    assert document.word_count == len(DEVANAGARI.split())
    assert document.character_count == len(DEVANAGARI)


def test_indic_joiners_are_preserved() -> None:
    text = "\u0915\u094d\u200d\u0937 and \u0915\u094d\u200c\u0937"  # contains ZWJ and ZWNJ
    assert extract_pasted_text(text).raw_text == text


# ------------------------------------------------------------ dispatcher


def test_extract_text_dispatches_by_type() -> None:
    assert extract_text(SCENE_TEXT).source_type == SourceType.PASTED_TEXT
    assert extract_text(SCENE_TEXT.encode(), "A.TXT").source_type == SourceType.TXT
    assert extract_text(make_docx(SCENE), "a.docx").source_type == SourceType.DOCX
    assert extract_text(make_pdf([["hello world"]]), "a.pdf").source_type == SourceType.PDF


@pytest.mark.parametrize("filename", ["script.rtf", "script.odt", "script", "script.doc", None, ""])
def test_unsupported_input_is_rejected_clearly(filename: str | None) -> None:
    with pytest.raises(UnsupportedFileTypeError):
        extract_text(b"some bytes", filename)


def test_unsupported_source_object_type() -> None:
    with pytest.raises(TypeError):
        extract_text(12345)  # type: ignore[arg-type]


# -------------------------------------------------------- failure handling


def test_corrupt_docx_becomes_failed_document() -> None:
    document = extract_docx(b"this is not a zip file", "bad.docx")
    assert document.extraction_status == ExtractionStatus.FAILED
    assert document.raw_text == ""
    assert ".docx" in document.extraction_warnings[0]


def test_truncated_docx_becomes_failed_document() -> None:
    document = extract_docx(make_docx(SCENE)[:100], "cut.docx")
    assert document.extraction_status == ExtractionStatus.FAILED


def test_bad_pdf_becomes_failed_document() -> None:
    for data in (b"", b"not a pdf at all", b"%PDF-1.4\ngarbage"):
        document = extract_pdf(data, "bad.pdf")
        assert document.extraction_status == ExtractionStatus.FAILED
        assert document.raw_text == ""
        assert document.extraction_warnings


def test_binary_file_named_txt_becomes_failed_document() -> None:
    document = extract_txt(make_docx(SCENE), "actually_docx.txt")
    assert document.extraction_status == ExtractionStatus.FAILED
    assert "binary" in document.extraction_warnings[0]


def test_unexpected_exception_becomes_failed_document(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(_: bytes) -> None:
        raise RuntimeError("kaboom")

    monkeypatch.setattr(ingestion, "_read_pdf", boom)
    document = extract_pdf(make_pdf([["hello"]]), "x.pdf")
    assert document.extraction_status == ExtractionStatus.FAILED
    assert "kaboom" in document.extraction_warnings[0]
