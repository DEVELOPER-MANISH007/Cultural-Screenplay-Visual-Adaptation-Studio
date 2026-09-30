"""Screenplay validators.

Pure functions with no I/O. Validation never rejects a screenplay just for
being short: only truly empty / near-empty / failed extractions are errors.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import PurePath

from app.models.screenplay import ExtractionStatus, ScreenplayDocument, SourceType

SUPPORTED_EXTENSIONS: dict[str, SourceType] = {
    ".txt": SourceType.TXT,
    ".docx": SourceType.DOCX,
    ".pdf": SourceType.PDF,
}

MIN_WORDS_ERROR = 5  # below this it cannot be a screenplay
SHORT_WORDS_WARNING = 50  # below this: warn, but allow (development scripts)
LOW_CHARS_PER_PAGE = 100  # PDF average below this suggests a scanned document


class UnsupportedFileTypeError(ValueError):
    """Raised when a file extension is not one of .txt, .docx, .pdf."""


@dataclass
class ValidationResult:
    """Outcome of validating a ScreenplayDocument."""

    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        return not self.errors


def validate_file_extension(filename: str | None) -> SourceType:
    """Map a filename to a SourceType or raise UnsupportedFileTypeError."""
    supported = ", ".join(SUPPORTED_EXTENSIONS)
    if not filename:
        raise UnsupportedFileTypeError(
            f"A filename with an extension is required. Supported types: {supported}."
        )
    extension = PurePath(filename).suffix.lower()
    if extension == ".doc":
        raise UnsupportedFileTypeError(
            "Legacy .doc files are not supported. Please save the file as .docx and try again."
        )
    try:
        return SUPPORTED_EXTENSIONS[extension]
    except KeyError:
        shown = extension or "(no extension)"
        raise UnsupportedFileTypeError(
            f"Unsupported file type {shown}. Supported types: {supported}."
        ) from None


def _dedupe(items: list[str]) -> list[str]:
    return list(dict.fromkeys(items))


def validate_screenplay(document: ScreenplayDocument) -> ValidationResult:
    """Validate an extracted screenplay and return errors and warnings."""
    result = ValidationResult()

    if document.extraction_status == ExtractionStatus.FAILED:
        messages = document.extraction_warnings or ["Unknown extraction error."]
        result.errors.extend(f"Extraction failed: {message}" for message in messages)
        return result

    # Extraction-time warnings (e.g. PDF pages without text) carry through.
    result.warnings.extend(document.extraction_warnings)

    if not document.raw_text.strip() or document.word_count == 0:
        result.errors.append(
            "The screenplay is empty. Provide a screenplay with some text before continuing."
        )
        result.warnings = _dedupe(result.warnings)
        return result

    words = document.word_count
    if words < MIN_WORDS_ERROR:
        result.errors.append(
            f"The screenplay is too short to process ({words} word(s)). "
            "Please provide at least a short scene."
        )
    elif words < SHORT_WORDS_WARNING:
        result.warnings.append(
            f"The screenplay is very short ({words} words). Short development scripts "
            "are fine, but later steps will have little material to work with."
        )

    if document.source_type == SourceType.PDF and document.page_count:
        average = document.character_count / document.page_count
        if average < LOW_CHARS_PER_PAGE:
            result.warnings.append(
                f"Very little text was extracted per page (about {average:.0f} characters). "
                "The PDF may be scanned or image-based; OCR is not supported."
            )

    if "\ufffd" in document.raw_text:
        result.warnings.append(
            "The text contains replacement characters (\ufffd), which usually means some "
            "characters were not decoded correctly. Please check the extracted text."
        )

    result.warnings = _dedupe(result.warnings)
    return result
