"""Pytest suite for production upgrade (evaluate, rank, config, LLM fallbacks, fairness)."""
from __future__ import annotations

import io
import os
from unittest.mock import MagicMock

import numpy as np
import pandas as pd
import pytest
from docx import Document
from werkzeug.datastructures import FileStorage, MultiDict

from app import create_app
from core.explainer import explain_match
from evaluation.accuracy_evaluator import AccuracyEvaluator
from utils.file_processor import FileProcessor
from utils.validators import RequestValidator


@pytest.fixture
def app():
    os.environ.setdefault("RATELIMIT_ENABLED", "false")
    application = create_app("testing")
    application.config["RATELIMIT_ENABLED"] = False
    yield application


@pytest.fixture
def client(app):
    return app.test_client()


def _sample_docx(name: str = "r1.docx") -> FileStorage:
    buf = io.BytesIO()
    doc = Document()
    doc.add_paragraph(
        "Senior Python engineer with ten years building APIs, Django, Flask, "
        "PostgreSQL, Docker, and AWS experience in production systems."
    )
    doc.save(buf)
    buf.seek(0)
    return FileStorage(stream=buf, filename=name, content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document")


def test_evaluate_endpoint_not_broken(client, monkeypatch):
    def fake_eval(self, algorithm_name, ground_truth_scores, predicted_scores, df=None):
        return {
            "algorithm": algorithm_name,
            "timestamp": "t",
            "test_samples": len(ground_truth_scores),
            "successful_predictions": len(predicted_scores),
            "failed_predictions": 0,
            "regression_metrics": {"r2_score": 0.5, "mean_absolute_error": 0.1},
            "ranking_metrics": {"spearman_correlation": 0.5, "ndcg_score": 0.5},
            "classification_metrics": {"classification_accuracy": 0.5},
            "tertile_bucket_metrics": {"tertile_classification_accuracy": 0.5},
            "performance_metrics": {"avg_processing_time": 0.0},
            "statistical_analysis": {},
            "error_analysis": {"error_distribution": {}, "bias_analysis": {}},
        }

    monkeypatch.setattr(
        AccuracyEvaluator,
        "evaluate_algorithm_predictions",
        fake_eval,
    )

    def _fake_extract_features(self, df, fit_transform=True):
        return np.zeros((len(df), 8), dtype=np.float64)

    def _fake_load_training_dataset(self, position=None):
        df = pd.DataFrame(
            [
                {
                    "resume_text": "python developer",
                    "job_description": "need python",
                    "quality_category": "good",
                    "position": position or "fullstack",
                    "quality_label": 2,
                    "filename": "stub.txt",
                }
            ]
        )
        return df, np.array([0.7], dtype=np.float64)

    monkeypatch.setattr(
        "data.dataset_manager.DatasetManager.extract_features",
        _fake_extract_features,
    )
    monkeypatch.setattr(
        "data.dataset_manager.DatasetManager.load_training_dataset",
        _fake_load_training_dataset,
    )

    resp = client.post(
        "/api/academic/evaluate-models",
        data={"position": "fullstack", "algorithms": "random_forest"},
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data.get("success") is True


def test_rank_endpoint_returns_scores(client):
    jd = (
        "We need a senior backend engineer with strong Python, APIs, and databases. "
        "Minimum five years experience in distributed systems and teamwork."
    )
    f1 = _sample_docx("a.docx")
    f2 = _sample_docx("b.docx")
    data = MultiDict(
        [
            ("jobDescription", jd),
            ("position", "backend"),
            ("methods", "cosine"),
            ("resumes", f1),
            ("resumes", f2),
        ]
    )
    resp = client.post(
        "/api/rank",
        data=data,
        content_type="multipart/form-data",
    )
    assert resp.status_code == 200, resp.get_data(as_text=True)
    data = resp.get_json()
    assert data["success"] is True
    assert len(data["results"]) == 2
    scores = sorted([r["final_score"] for r in data["results"]], reverse=True)
    assert scores[0] >= scores[1]


def test_file_size_limit_consistent():
    fp = FileProcessor({})
    rv = RequestValidator({})
    assert fp.max_file_size == rv._per_file_max_bytes


def test_explainer_fallback(monkeypatch):
    import app_config

    monkeypatch.setattr(app_config, "USE_LLM_EXPLANATIONS", False)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)

    cr = {
        "combined_score": 0.85,
        "algorithm_scores": {"cosine": {"score": 0.85, "details": {}}},
    }
    text = explain_match("resume text", "job text", 85.0, [], [], cr, "backend")
    assert "Excellent match" in text or "match" in text.lower()


def test_jd_expander_cache(monkeypatch):
    import app_config

    monkeypatch.setattr(app_config, "USE_LLM_JD_EXPANSION", True)
    monkeypatch.setenv("GROQ_API_KEY", "test-key")

    import core.jd_expander as je

    je.clear_jd_cache_for_tests()
    je._llm = None

    invocations = {"n": 0}

    class _Out:
        def model_dump(self):
            return {
                "required_skills": ["x"],
                "preferred_skills": [],
                "experience_level": "mid",
                "key_responsibilities": [],
                "implicit_requirements": [],
            }

    final = MagicMock()

    def _invoke(*_a, **_kw):
        invocations["n"] += 1
        return _Out()

    final.invoke.side_effect = _invoke

    class _Prompt:
        def __or__(self, _other):
            return final

    monkeypatch.setattr(
        je,
        "ChatPromptTemplate",
        MagicMock(from_messages=lambda *a, **k: _Prompt()),
    )

    fake_llm = MagicMock()
    fake_llm.with_structured_output.return_value = object()
    monkeypatch.setattr(je, "_get_llm", lambda: fake_llm)

    jd = "Senior engineer role with Python and cloud. " * 2
    je.expand_jd(jd)
    je.expand_jd(jd)
    assert invocations["n"] == 1


def test_fairness_warning_triggered():
    from core.fairness_monitor import analyze_batch_fairness

    jd = "python " * 30 + "team player with communication skills"
    out = analyze_batch_fairness(jd, [0.5, 0.52, 0.51])
    assert out["fairness_warning"] is not None


def test_request_id_in_response(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert "X-Request-ID" in r.headers
