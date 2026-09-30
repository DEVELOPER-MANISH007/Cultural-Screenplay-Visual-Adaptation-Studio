"""Phase 1 tests: screenplay validators."""

from __future__ import annotations

import pytest

from app.models.screenplay import ExtractionStatus
from app.services.ingestion import extract_docx, extract_pasted_text, extract_pdf, extract_txt
from app.services.validators import (
    MIN_WORDS_ERROR,
    SHORT_WORDS_WARNING,
    UnsupportedFileTypeError,
    validate_file_extension,
    validate_screenplay,
)
from app.models.screenplay import SourceType
from tests.factories import make_docx, make_pdf

LONG_TEXT = " ".join(["word"] * 120)


def test_valid_screenplay_passes_cleanly() -> None:
    result = validate_screenplay(extract_pasted_text(LONG_TEXT))
    assert result.is_valid
    assert result.errors == []
    assert result.warnings == []


@pytest.mark.parametrize("text", ["", "   ", "\n\n"])
def test_empty_screenplay_is_an_error(text: str) -> None:
    result = validate_screenplay(extract_pasted_text(text))
    assert not result.is_valid
    assert any("empty" in e for e in result.errors)


def test_empty_txt_file_is_an_error() -> None:
    result = validate_screenplay(extract_txt(b"", "empty.txt"))
    assert not result.is_valid
    assert any("empty" in e for e in result.errors)


def test_extremely_short_screenplay_is_an_error() -> None:
    result = validate_screenplay(extract_pasted_text("INT. ROOM"))
    assert not result.is_valid
    assert any("too short" in e for e in result.errors)


def test_short_development_screenplay_only_warns() -> None:
    text = " ".join(["word"] * (SHORT_WORDS_WARNING - 1))
    result = validate_screenplay(extract_pasted_text(text))
    assert result.is_valid
    assert any("very short" in w for w in result.warnings)


def test_boundaries_between_error_warning_and_ok() -> None:
    just_enough = validate_screenplay(extract_pasted_text(" ".join(["w"] * MIN_WORDS_ERROR)))
    assert just_enough.is_valid and just_enough.warnings
    long_enough = validate_screenplay(extract_pasted_text(" ".join(["w"] * SHORT_WORDS_WARNING)))
    assert long_enough.is_valid and not long_enough.warnings


def test_pdf_pages_without_text_surface_as_warnings() -> None:
    lines = [f"Line {i} of the scene with some words" for i in range(12)]
    document = extract_pdf(make_pdf([lines, [], lines]), "a.pdf")
    result = validate_screenplay(document)
    assert result.is_valid
    assert any("Page 2 contains no extractable text" in w for w in result.warnings)
    assert len(result.warnings) == len(set(result.warnings))


def test_scanned_pdf_with_no_text_is_an_error() -> None:
    result = validate_screenplay(extract_pdf(make_pdf([[], []]), "scan.pdf"))
    assert not result.is_valid
    assert any("OCR" in w for w in result.warnings)


def test_suspiciously_low_text_per_pdf_page_warns() -> None:
    pages = [["one two three four five six seven eight nine ten eleven twelve"]] + [[]] * 9
    result = validate_screenplay(extract_pdf(make_pdf(pages), "a.pdf"))
    assert any("Very little text" in w for w in result.warnings)


def test_failed_extraction_is_reported_as_error() -> None:
    document = extract_docx(b"garbage", "bad.docx")
    assert document.extraction_status == ExtractionStatus.FAILED
    result = validate_screenplay(document)
    assert not result.is_valid
    assert result.errors[0].startswith("Extraction failed:")


def test_extraction_warnings_are_carried_into_validation() -> None:
    document = extract_docx(make_docx(["INT. ROOM - DAY"]), "tiny.docx")
    result = validate_screenplay(document)
    assert any("very little text" in w for w in result.warnings)


def test_replacement_characters_warn() -> None:
    result = validate_screenplay(extract_txt(b"hello \x81 world " * 10, "a.txt"))
    assert any("replacement characters" in w for w in result.warnings)


@pytest.mark.parametrize(
    ("filename", "expected"),
    [
        ("a.txt", SourceType.TXT),
        ("A.DOCX", SourceType.DOCX),
        ("dir/My Script.PDF", SourceType.PDF),
        ("v1.final.txt", SourceType.TXT),
    ],
)
def test_supported_extensions(filename: str, expected: SourceType) -> None:
    assert validate_file_extension(filename) == expected


@pytest.mark.parametrize("filename", ["a.rtf", "a.png", "noext", "", None, "a.doc"])
def test_unsupported_extensions_raise_clear_message(filename: str | None) -> None:
    with pytest.raises(UnsupportedFileTypeError, match="[Ss]upported|\\.docx|filename"):
        validate_file_extension(filename)
