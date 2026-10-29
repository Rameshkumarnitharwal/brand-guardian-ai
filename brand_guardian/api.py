"""FastAPI service exposing the audit pipeline, plus a small web UI at /.

Run: uvicorn brand_guardian.api:app --port 8010 --reload
"""

import logging
import threading
import uuid
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from brand_guardian.graph import build_graph, run_audit
from brand_guardian.state import ComplianceReport

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static"
STEPS = ["ingest", "index", "retrieve", "audit"]

app = FastAPI(title="Brand Guardian AI", description="Video content compliance auditor", version="0.1.0")

# In-memory job store: fine for a single local process; use a queue/DB for production.
jobs: dict[str, dict[str, Any]] = {}
jobs_lock = threading.Lock()


class AuditRequest(BaseModel):
    video_url: str


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


# Sync handler: FastAPI runs it in a threadpool, so the long-running pipeline won't block the event loop.
@app.post("/audit", response_model=ComplianceReport)
def audit(req: AuditRequest) -> ComplianceReport:
    final = run_audit(req.video_url)
    if final.get("errors") or not final.get("report"):
        raise HTTPException(status_code=502, detail={"errors": final.get("errors", ["unknown failure"])})
    return ComplianceReport(**final["report"])


def _run_job(job_id: str, video_url: str) -> None:
    def update(**fields: Any) -> None:
        with jobs_lock:
            jobs[job_id].update(fields)

    try:
        update(status="running", current_step=STEPS[0])
        for chunk in build_graph().stream({"video_url": video_url, "errors": []}, stream_mode="updates"):
            for node, out in chunk.items():
                out = out or {}
                with jobs_lock:
                    job = jobs[job_id]
                    job["completed_steps"].append(node)
                    if out.get("errors"):
                        job["errors"].extend(out["errors"])
                    if out.get("report"):
                        job["report"] = out["report"]
                    nxt = STEPS.index(node) + 1
                    job["current_step"] = STEPS[nxt] if nxt < len(STEPS) and not job["errors"] else None
        with jobs_lock:
            job = jobs[job_id]
            job["status"] = "failed" if job["errors"] or not job["report"] else "done"
            job["current_step"] = None
    except Exception as exc:  # pragma: no cover - safety net
        log.exception("Job %s crashed", job_id)
        update(status="failed", current_step=None, errors=[f"pipeline: {exc}"])


@app.post("/jobs", status_code=202)
def create_job(req: AuditRequest) -> dict[str, str]:
    """Start an audit in the background; poll GET /jobs/{id} for progress."""
    job_id = uuid.uuid4().hex[:12]
    with jobs_lock:
        jobs[job_id] = {
            "id": job_id, "video_url": req.video_url, "status": "queued",
            "current_step": None, "completed_steps": [], "errors": [], "report": None,
        }
    threading.Thread(target=_run_job, args=(job_id, req.video_url), daemon=True).start()
    return {"id": job_id}


@app.get("/jobs/{job_id}")
def get_job(job_id: str) -> dict[str, Any]:
    with jobs_lock:
        job = jobs.get(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="job not found")
        return {**job, "completed_steps": list(job["completed_steps"]), "errors": list(job["errors"])}
