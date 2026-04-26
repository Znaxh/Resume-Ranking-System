"""Tests for request validation."""
import io
import pytest
from unittest.mock import MagicMock
from werkzeug.datastructures import FileStorage

from utils.validators import RequestValidator


@pytest.fixture
def validator():
    return RequestValidator({})


class TestAlgorithmValidation:
    def test_valid_algorithms(self, validator):
        result = validator._validate_algorithms(["bert", "cosine"])
        assert result["valid"] is True

    def test_bm25_accepted(self, validator):
        result = validator._validate_algorithms(["bm25"])
        assert result["valid"] is True

    def test_jaccard_still_accepted(self, validator):
        result = validator._validate_algorithms(["jaccard"])
        assert result["valid"] is True

    def test_invalid_algorithm(self, validator):
        result = validator._validate_algorithms(["nonexistent"])
        assert result["valid"] is False

    def test_empty_algorithms(self, validator):
        result = validator._validate_algorithms([])
        assert result["valid"] is False

    def test_duplicate_algorithms(self, validator):
        result = validator._validate_algorithms(["bert", "bert"])
        assert result["valid"] is False


class TestPositionValidation:
    def test_valid_position(self, validator):
        result = validator._validate_position("sde")
        assert result["valid"] is True

    def test_qa_engineer_valid(self, validator):
        result = validator._validate_position("qa_engineer")
        assert result["valid"] is True

    def test_security_engineer_valid(self, validator):
        result = validator._validate_position("security_engineer")
        assert result["valid"] is True

    def test_invalid_position(self, validator):
        result = validator._validate_position("astronaut")
        assert result["valid"] is False


class TestJobDescriptionValidation:
    def test_valid_jd(self, validator):
        jd = "We need a senior Python developer with 5 years of experience in Django."
        result = validator._validate_job_description(jd)
        assert result["valid"] is True

    def test_empty_jd(self, validator):
        result = validator._validate_job_description("")
        assert result["valid"] is False

    def test_too_short_jd(self, validator):
        result = validator._validate_job_description("short")
        assert result["valid"] is False

    def test_script_injection(self, validator):
        jd = '<script>alert("xss")</script> We need a developer'
        result = validator._validate_job_description(jd)
        assert result["valid"] is False
