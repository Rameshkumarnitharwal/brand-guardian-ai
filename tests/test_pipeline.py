from unittest.mock import patch

from brand_guardian import graph, nodes
from brand_guardian.services.video_indexer import extract_insights
from brand_guardian.state import Severity, Violation, derive_status

SAMPLE_INDEX = {
    "name": "promo",
    "state": "Processed",
    "summarizedInsights": {"duration": {"seconds": 42.0}},
    "videos": [{
        "insights": {
            "sourceLanguage": "en-US",
            "transcript": [
                {"text": "This serum is guaranteed to remove wrinkles.", "instances": [{"start": "0:00:03.1"}]},
                {"text": "", "instances": [{"start": "0:00:05"}]},
                {"text": "Link in bio!", "instances": [{"start": "1:02:09.5"}]},
            ],
            "ocr": [
                {"text": "100% RESULTS", "instances": [{"start": "0:00:04"}]},
                {"text": "100% results", "instances": [{"start": "0:00:09"}]},
            ],
        }
    }],
}


def _violation(sev):
    return Violation(category="x", severity=sev, claim="c", source="transcript",
                     rule_reference="r", explanation="e", recommendation="f")


def test_extract_insights_timestamps_and_dedup():
    out = extract_insights(SAMPLE_INDEX)
    assert out["transcript"].splitlines() == [
        "[00:03] This serum is guaranteed to remove wrinkles.",
        "[1:02:09] Link in bio!",
    ]
    assert out["ocr_text"] == "[00:04] 100% RESULTS"
    assert out["video_metadata"]["duration_seconds"] == 42.0


def test_derive_status():
    assert derive_status([]) == "PASS"
    assert derive_status([_violation(Severity.LOW), _violation(Severity.MEDIUM)]) == "NEEDS_REVIEW"
    assert derive_status([_violation(Severity.LOW), _violation(Severity.HIGH)]) == "FAIL"


def test_graph_runs_all_nodes_on_success():
    with patch.object(nodes, "ingest_node", lambda s: {"video_name": "v", "blob_sas_url": "u"}), \
         patch.object(nodes, "index_node", lambda s: {"video_id": "id", "transcript": "t", "ocr_text": ""}), \
         patch.object(nodes, "retrieve_node", lambda s: {"rules": [{"content": "c", "source": "s", "page": 0}]}), \
         patch.object(nodes, "audit_node", lambda s: {"report": {"status": "PASS"}}):
        final = graph.run_audit("https://youtu.be/x")
    assert final["report"] == {"status": "PASS"}
    assert final["errors"] == []


def test_graph_short_circuits_on_error():
    called = []
    with patch.object(nodes, "ingest_node", lambda s: {"video_name": "v", "blob_sas_url": "u"}), \
         patch.object(nodes, "index_node", lambda s: {"errors": ["index: boom"]}), \
         patch.object(nodes, "retrieve_node", lambda s: called.append("retrieve") or {}), \
         patch.object(nodes, "audit_node", lambda s: called.append("audit") or {}):
        final = graph.run_audit("https://youtu.be/x")
    assert final["errors"] == ["index: boom"]
    assert called == []
    assert "report" not in final


def test_format_rules_uses_one_based_pages():
    text = nodes.format_rules([{"content": "No guarantees.", "source": "ftc.pdf", "page": 2}])
    assert "(source: ftc.pdf, page 3)" in text
    assert nodes.rule_labels([{"source": "a.pdf", "page": 0}, {"source": "a.pdf", "page": 0}]) == ["a.pdf p.1"]


def test_web_ui_job_flow():
    import time
    from fastapi.testclient import TestClient
    from brand_guardian.api import app

    with patch.object(nodes, "ingest_node", lambda s: {"video_name": "v", "blob_sas_url": "u"}), \
         patch.object(nodes, "index_node", lambda s: {"video_id": "id", "transcript": "t", "ocr_text": ""}), \
         patch.object(nodes, "retrieve_node", lambda s: {"rules": [{"content": "c", "source": "s", "page": 0}]}), \
         patch.object(nodes, "audit_node", lambda s: {"report": {"status": "PASS"}}):
        client = TestClient(app)
        assert "Brand Guardian" in client.get("/").text
        job_id = client.post("/jobs", json={"video_url": "https://youtu.be/x"}).json()["id"]
        for _ in range(50):
            job = client.get(f"/jobs/{job_id}").json()
            if job["status"] in ("done", "failed"):
                break
            time.sleep(0.05)
    assert job["status"] == "done"
    assert job["completed_steps"] == ["ingest", "index", "retrieve", "audit"]
    assert job["report"] == {"status": "PASS"}
