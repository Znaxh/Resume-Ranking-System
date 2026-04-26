"""Integration tests for the full resume ranking pipeline."""
import io
import pytest
from docx import Document
from werkzeug.datastructures import FileStorage, MultiDict

from app import create_app


@pytest.fixture
def app():
    import os
    os.environ["RATELIMIT_ENABLED"] = "false"
    application = create_app("testing")
    application.config["RATELIMIT_ENABLED"] = False
    yield application


@pytest.fixture
def client(app):
    return app.test_client()


def _make_resume_docx(name: str, content: str) -> FileStorage:
    buf = io.BytesIO()
    doc = Document()
    doc.add_paragraph(content)
    doc.save(buf)
    buf.seek(0)
    return FileStorage(
        stream=buf, filename=name,
        content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )


JOB_DESCRIPTION = (
    "We are looking for a Senior Software Engineer with 5+ years of experience "
    "in Python, Django, Flask, PostgreSQL, Docker, and AWS. The candidate should "
    "have strong problem-solving skills and experience leading technical teams."
)


class TestFullPipeline:
    def test_cosine_ranking(self, client):
        strong = _make_resume_docx(
            "strong.docx",
            "Senior Python engineer with 8 years experience in Django, Flask, "
            "PostgreSQL, Docker, AWS. Led teams of 10 engineers."
        )
        weak = _make_resume_docx(
            "weak.docx",
            "Recent graduate interested in learning web development. "
            "Basic HTML and CSS knowledge."
        )
        data = MultiDict([
            ("jobDescription", JOB_DESCRIPTION),
            ("position", "backend"),
            ("methods", "cosine"),
            ("resumes", strong),
            ("resumes", weak),
        ])
        resp = client.post("/api/process-resumes", data=data, content_type="multipart/form-data")
        assert resp.status_code == 200
        result = resp.get_json()
        assert result["success"] is True
        assert len(result["results"]) == 2
        ranked = sorted(result["results"], key=lambda r: r["rank"])
        assert ranked[0]["final_score"] >= ranked[1]["final_score"]

    def test_multiple_algorithms(self, client):
        resume = _make_resume_docx(
            "dev.docx",
            "Full stack developer with Python, JavaScript, React, Node.js, "
            "PostgreSQL, MongoDB, Docker, Git. 5 years experience."
        )
        data = MultiDict([
            ("jobDescription", JOB_DESCRIPTION),
            ("position", "fullstack"),
            ("methods", "cosine"),
            ("methods", "bm25"),
            ("resumes", resume),
        ])
        resp = client.post("/api/process-resumes", data=data, content_type="multipart/form-data")
        assert resp.status_code == 200
        result = resp.get_json()
        assert result["success"] is True
        scores = result["results"][0]["scores"]
        assert "cosine" in scores

    def test_no_files_returns_400(self, client):
        data = MultiDict([
            ("jobDescription", JOB_DESCRIPTION),
            ("position", "backend"),
            ("methods", "cosine"),
        ])
        resp = client.post("/api/process-resumes", data=data, content_type="multipart/form-data")
        assert resp.status_code == 400

    def test_no_jd_returns_400(self, client):
        resume = _make_resume_docx("r.docx", "Python developer with 5 years experience.")
        data = MultiDict([
            ("position", "backend"),
            ("methods", "cosine"),
            ("resumes", resume),
        ])
        resp = client.post("/api/process-resumes", data=data, content_type="multipart/form-data")
        assert resp.status_code == 400


class TestExportEndpoint:
    def test_csv_export(self, client):
        payload = {
            "format": "csv",
            "results": {
                "results": [
                    {
                        "rank": 1,
                        "filename": "best.docx",
                        "final_score": 0.85,
                        "weighted_score": 0.85,
                        "confidence": "high",
                        "explanation": "Strong match",
                        "scores": {"cosine": 0.9},
                        "extracted_skills": ["Python", "Django"]
                    }
                ]
            }
        }
        resp = client.post("/api/export-results", json=payload)
        assert resp.status_code == 200
        assert resp.content_type.startswith("text/csv")

    def test_export_empty_results(self, client):
        payload = {"format": "csv", "results": {"results": []}}
        resp = client.post("/api/export-results", json=payload)
        assert resp.status_code == 400


class TestHealthAndInfo:
    def test_health(self, client):
        resp = client.get("/api/health")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "healthy"

    def test_positions_include_qa_security(self, client):
        resp = client.get("/api/positions")
        assert resp.status_code == 200
        data = resp.get_json()
        values = [p["value"] for p in data]
        assert "qa_engineer" in values
        assert "security_engineer" in values

    def test_request_id_header(self, client):
        resp = client.get("/api/health")
        assert "X-Request-ID" in resp.headers

    def test_api_version_header(self, client):
        resp = client.get("/api/health")
        assert resp.headers.get("X-API-Version") == "legacy"

    def test_v2_version_header(self, client):
        resp = client.get("/v2/api/health")
        assert resp.headers.get("X-API-Version") == "v2"
