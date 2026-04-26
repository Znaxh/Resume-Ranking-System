"""Tests for file processing utilities."""
import io
import os
import pytest
from unittest.mock import MagicMock
from werkzeug.datastructures import FileStorage
from docx import Document

from utils.file_processor import FileProcessor


@pytest.fixture
def processor():
    return FileProcessor({})


def _make_docx(text: str, name: str = "test.docx") -> FileStorage:
    buf = io.BytesIO()
    doc = Document()
    doc.add_paragraph(text)
    doc.save(buf)
    buf.seek(0)
    return FileStorage(
        stream=buf, filename=name,
        content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )


def _make_txt(text: str, name: str = "test.txt") -> FileStorage:
    buf = io.BytesIO(text.encode("utf-8"))
    return FileStorage(stream=buf, filename=name, content_type="text/plain")


class TestFileValidation:
    def test_valid_docx(self, processor):
        f = _make_docx("This is a valid resume with enough content to pass validation checks.")
        result = processor.validate_file(f)
        assert result["valid"] is True

    def test_no_file(self, processor):
        result = processor.validate_file(None)
        assert result["valid"] is False

    def test_empty_filename(self, processor):
        f = FileStorage(stream=io.BytesIO(b"data"), filename="")
        result = processor.validate_file(f)
        assert result["valid"] is False

    def test_unsupported_extension(self, processor):
        f = FileStorage(stream=io.BytesIO(b"data"), filename="resume.xyz")
        result = processor.validate_file(f)
        assert result["valid"] is False
        assert "not supported" in result["error"]

    def test_file_too_large(self, processor):
        large_data = b"x" * (processor.max_file_size + 1)
        f = FileStorage(stream=io.BytesIO(large_data), filename="big.pdf")
        result = processor.validate_file(f)
        assert result["valid"] is False


class TestTextExtraction:
    def test_docx_extraction(self, processor):
        content = "Senior Python engineer with 10 years building APIs and distributed systems."
        f = _make_docx(content)
        result = processor.process_files([f])
        assert len(result) == 1
        assert result[0]["success"] is True
        assert "Python" in result[0]["text"]

    def test_empty_docx_rejected(self, processor):
        f = _make_docx("")
        result = processor.process_files([f])
        assert result[0]["success"] is False

    def test_multiple_files(self, processor):
        files = [
            _make_docx("Engineer with Python Django Flask experience and cloud computing skills."),
            _make_docx("Data scientist with machine learning expertise in TensorFlow and PyTorch."),
        ]
        results = processor.process_files(files)
        assert len(results) == 2
        assert all(r["success"] for r in results)

    def test_mixed_valid_invalid(self, processor):
        files = [
            _make_docx("Valid resume content with enough text to pass the minimum character threshold."),
            FileStorage(stream=io.BytesIO(b"tiny"), filename="bad.xyz"),
        ]
        results = processor.process_files(files)
        assert results[0]["success"] is True
        assert results[1]["success"] is False
