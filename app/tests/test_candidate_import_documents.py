"""Contracts for deterministic CV parsing and safe ZIP expansion."""

import importlib
import io
import zipfile

import fitz
import pytest
from docx import Document


MIB = 1024 * 1024
GIB = 1024 * 1024 * 1024


def _documents():
    try:
        return importlib.import_module("app.infrastructure.imports.documents")
    except ModuleNotFoundError as exc:
        pytest.fail(f"candidate import documents module is missing: {exc}")


def _pdf_bytes(text: str) -> bytes:
    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 72), text)
    payload = document.tobytes()
    document.close()
    return payload


def _docx_bytes(lines: list[str]) -> bytes:
    document = Document()
    for line in lines:
        document.add_paragraph(line)
    stream = io.BytesIO()
    document.save(stream)
    return stream.getvalue()


def _zip_bytes(entries: dict[str, bytes], *, symlinks: set[str] | None = None) -> bytes:
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, payload in entries.items():
            if symlinks and name in symlinks:
                info = zipfile.ZipInfo(name)
                info.create_system = 3
                info.external_attr = 0o120777 << 16
                archive.writestr(info, payload)
            else:
                archive.writestr(name, payload)
    return stream.getvalue()


def test_extract_pdf_reads_header_contacts_name_and_hash():
    documents = _documents()
    payload = _pdf_bytes(
        "Ana Gomez\nana@example.com\n+57 300 123 4567\nBackend Engineer\nPython AWS"
    )

    parsed = documents.extract_document(payload, "ana_gomez.pdf")

    assert parsed.filename == "ana_gomez.pdf"
    assert parsed.content_type == "application/pdf"
    assert parsed.display_name == "Ana Gomez"
    assert parsed.email == "ana@example.com"
    assert parsed.phone == "+573001234567"
    assert "Backend Engineer" in parsed.text
    assert "ana@example.com" in parsed.header_text
    assert len(parsed.sha256) == 64


def test_header_region_uses_up_to_40_non_empty_lines_not_only_name_window():
    documents = _documents()
    lines = ["Ana Gomez"] + [f"Section {index}" for index in range(1, 10)] + ["ana@example.com"]
    payload = _docx_bytes(lines)

    parsed = documents.extract_document(payload, "ana.docx")

    assert parsed.display_name == "Ana Gomez"
    assert parsed.email == "ana@example.com"
    assert "ana@example.com" in parsed.header_text


def test_header_region_is_capped_at_4000_characters():
    documents = _documents()
    payload = _docx_bytes(["Ana Gomez"] + ["X" * 500 for _ in range(20)])

    parsed = documents.extract_document(payload, "ana.docx")

    assert len(parsed.header_text) <= 4000


def test_extract_docx_reads_contact_header():
    documents = _documents()
    payload = _docx_bytes(
        [
            "Carlos Rojas",
            "carlos@example.com",
            "+57 310 555 9876",
            "Automation Engineer",
        ]
    )

    parsed = documents.extract_document(payload, "carlos.docx")

    assert parsed.content_type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    assert parsed.display_name == "Carlos Rojas"
    assert parsed.email == "carlos@example.com"
    assert parsed.phone == "+573105559876"


def test_ambiguous_header_contact_is_not_a_strong_identity():
    documents = _documents()
    payload = _docx_bytes(
        [
            "Ana Gomez",
            "ana@example.com",
            "other@example.com",
            "+57 300 123 4567",
            "+57 301 765 4321",
        ]
    )

    parsed = documents.extract_document(payload, "ana.docx")

    assert parsed.email is None
    assert parsed.phone is None


def test_display_name_falls_back_to_filename_when_header_has_no_plausible_name():
    documents = _documents()
    payload = _docx_bytes(["HOJA DE VIDA", "ana@example.com", "3001234567"])

    parsed = documents.extract_document(payload, "ana-gomez_cv.docx")

    assert parsed.display_name == "ana gomez cv"


def test_rejects_unsupported_empty_and_oversized_documents():
    documents = _documents()

    with pytest.raises(documents.UnsupportedDocument):
        documents.extract_document(b"plain text", "resume.txt")
    with pytest.raises(documents.InvalidDocument):
        documents.extract_document(b"", "empty.pdf")
    with pytest.raises(documents.DocumentTooLarge):
        documents.extract_document(b"x" * (15 * MIB + 1), "huge.pdf")


def test_expand_zip_accepts_pdf_docx_and_ignores_metadata_files():
    documents = _documents()
    payload = _zip_bytes(
        {
            "cv/ana.pdf": _pdf_bytes("Ana Gomez"),
            "cv/beto.docx": _docx_bytes(["Beto Ruiz"]),
            "__MACOSX/._ana.pdf": b"metadata",
            ".DS_Store": b"metadata",
            "notes.txt": b"ignore me",
        }
    )

    expanded = documents.expand_zip(
        payload,
        remaining_documents=500,
        remaining_bytes=GIB,
    )

    assert [item.filename for item in expanded] == ["ana.pdf", "beto.docx"]
    assert {item.content_type for item in expanded} == {
        "application/pdf",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    }


def test_expand_zip_rejects_path_traversal():
    documents = _documents()
    payload = _zip_bytes({"../evil.pdf": _pdf_bytes("Evil")})

    with pytest.raises(documents.UnsafeArchive, match="UNSAFE_ARCHIVE_PATH"):
        documents.expand_zip(payload, remaining_documents=500, remaining_bytes=GIB)


def test_expand_zip_rejects_absolute_path():
    documents = _documents()
    payload = _zip_bytes({"/evil.pdf": _pdf_bytes("Evil")})

    with pytest.raises(documents.UnsafeArchive, match="UNSAFE_ARCHIVE_PATH"):
        documents.expand_zip(payload, remaining_documents=500, remaining_bytes=GIB)


def test_expand_zip_rejects_symlink():
    documents = _documents()
    payload = _zip_bytes(
        {"cv-link.pdf": b"target"},
        symlinks={"cv-link.pdf"},
    )

    with pytest.raises(documents.UnsafeArchive, match="ARCHIVE_SYMLINK"):
        documents.expand_zip(payload, remaining_documents=500, remaining_bytes=GIB)


def test_expand_zip_rejects_nested_archives():
    documents = _documents()
    nested = _zip_bytes({"cv.pdf": _pdf_bytes("Ana")})
    payload = _zip_bytes({"nested.zip": nested})

    with pytest.raises(documents.UnsafeArchive, match="NESTED_ARCHIVE"):
        documents.expand_zip(payload, remaining_documents=500, remaining_bytes=GIB)


@pytest.mark.parametrize("nested_name", ["nested.tar", "nested.gz", "nested.rar", "nested.7z"])
def test_expand_zip_rejects_other_nested_archive_suffixes(nested_name):
    documents = _documents()
    payload = _zip_bytes({nested_name: b"archive payload"})

    with pytest.raises(documents.UnsafeArchive, match="NESTED_ARCHIVE"):
        documents.expand_zip(payload, remaining_documents=500, remaining_bytes=GIB)


def test_expand_zip_rejects_malformed_archive():
    documents = _documents()

    with pytest.raises(documents.InvalidArchive):
        documents.expand_zip(b"not-a-zip", remaining_documents=500, remaining_bytes=GIB)


def test_expand_zip_enforces_compressed_size_limit(monkeypatch):
    documents = _documents()
    payload = _zip_bytes({"a.pdf": _pdf_bytes("A")})
    monkeypatch.setattr(documents, "MAX_ARCHIVE_BYTES", len(payload) - 1)

    with pytest.raises(documents.ArchiveTooLarge):
        documents.expand_zip(payload, remaining_documents=500, remaining_bytes=GIB)


def test_expand_zip_enforces_remaining_document_limit():
    documents = _documents()
    payload = _zip_bytes(
        {
            "a.pdf": _pdf_bytes("A"),
            "b.pdf": _pdf_bytes("B"),
        }
    )

    with pytest.raises(documents.DocumentLimitExceeded):
        documents.expand_zip(payload, remaining_documents=1, remaining_bytes=GIB)


def test_expand_zip_enforces_remaining_expanded_bytes():
    documents = _documents()
    first = _pdf_bytes("A")
    second = _pdf_bytes("B")
    payload = _zip_bytes({"a.pdf": first, "b.pdf": second})

    with pytest.raises(documents.ExpandedArchiveTooLarge):
        documents.expand_zip(
            payload,
            remaining_documents=500,
            remaining_bytes=len(first) + len(second) - 1,
        )
