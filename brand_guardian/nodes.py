"""LangGraph nodes: ingest -> index -> retrieve -> audit.

Each node returns a partial state update. Failures are recorded in `errors`
rather than raised, so the graph can short-circuit to END cleanly.
"""

import logging
from typing import Any

from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import AzureChatOpenAI

from brand_guardian.config import get_settings
from brand_guardian.services.knowledge_base import get_vector_store
from brand_guardian.services.storage import StorageService, safe_video_name
from brand_guardian.services.video_indexer import VideoIndexerService, extract_insights
from brand_guardian.state import AuditResult, AuditState, ComplianceReport, derive_status

log = logging.getLogger(__name__)

MAX_QUERY_CHARS = 4000

AUDIT_SYSTEM_PROMPT = """You are Brand Guardian, a senior advertising-compliance auditor.
You review video content against the regulatory rules provided (e.g. FTC Endorsement Guides,
FTC advertising substantiation rules, YouTube Ads policies).

Instructions:
- Examine EVERY claim in the transcript and on-screen text (OCR).
- Flag a violation only when it conflicts with one of the provided rules; cite that rule in
  `rule_reference` using its source document and page/section.
- Typical violations: absolute guarantees ("guaranteed results", "100% cure"), unsubstantiated
  health/financial claims, missing or unclear sponsorship/material-connection disclosures,
  misleading before/after or "free" claims, prohibited content for ads.
- Severity: CRITICAL = likely illegal or platform-banned; HIGH = clear rule breach;
  MEDIUM = probable breach / needs substantiation; LOW = best-practice issue.
- Use the [mm:ss] markers to fill `timestamp`.
- If nothing violates the rules, return an empty violations list. Do not invent claims."""

AUDIT_HUMAN_PROMPT = """## Compliance rules (retrieved)
{rules}

## Video transcript (speech-to-text)
{transcript}

## On-screen text (OCR)
{ocr_text}"""


def ingest_node(state: AuditState) -> dict[str, Any]:
    source = state["video_url"]
    try:
        name = safe_video_name(source)
        sas_url = StorageService(get_settings()).ingest(source, name)
        return {"video_name": name, "blob_sas_url": sas_url}
    except Exception as exc:
        log.exception("Ingestion failed")
        return {"errors": [f"ingest: {exc}"]}


def index_node(state: AuditState) -> dict[str, Any]:
    try:
        vi = VideoIndexerService(get_settings())
        video_id = vi.upload(state["blob_sas_url"], state["video_name"])
        insights = extract_insights(vi.wait_for_index(video_id))
        if not insights["transcript"] and not insights["ocr_text"]:
            return {"video_id": video_id, "errors": ["index: no speech or on-screen text was extracted"]}
        return {"video_id": video_id, **insights}
    except Exception as exc:
        log.exception("Video indexing failed")
        return {"errors": [f"index: {exc}"]}


def retrieve_node(state: AuditState) -> dict[str, Any]:
    settings = get_settings()
    content = f"{state.get('transcript', '')}\n{state.get('ocr_text', '')}"
    # Query once with the full content, plus targeted queries for common violation types.
    queries = [
        content[:MAX_QUERY_CHARS],
        "sponsorship and material connection disclosure requirements for endorsements",
        "absolute guarantees, unsubstantiated or misleading advertising claims",
    ]
    try:
        store = get_vector_store(settings)
        rules, seen = [], set()
        for q in queries:
            for doc in store.similarity_search(q, k=settings.retrieval_top_k):
                key = doc.page_content.strip()
                if key in seen:
                    continue
                seen.add(key)
                meta = doc.metadata or {}
                rules.append({
                    "content": doc.page_content,
                    "source": meta.get("source", "unknown"),
                    "page": meta.get("page"),
                })
        if not rules:
            return {"errors": ["retrieve: knowledge base returned no rules (did you run scripts/index_documents.py?)"]}
        return {"rules": rules}
    except Exception as exc:
        log.exception("Retrieval failed")
        return {"errors": [f"retrieve: {exc}"]}


def format_rules(rules: list[dict[str, Any]]) -> str:
    parts = []
    for i, r in enumerate(rules, 1):
        page = f", page {r['page'] + 1}" if isinstance(r.get("page"), int) else ""
        parts.append(f"[Rule {i}] (source: {r['source']}{page})\n{r['content']}")
    return "\n\n".join(parts)


def rule_labels(rules: list[dict[str, Any]]) -> list[str]:
    labels = []
    for r in rules:
        page = f" p.{r['page'] + 1}" if isinstance(r.get("page"), int) else ""
        label = f"{r['source']}{page}"
        if label not in labels:
            labels.append(label)
    return labels


def get_llm() -> AzureChatOpenAI:
    s = get_settings()
    return AzureChatOpenAI(
        azure_endpoint=s.openai_endpoint,
        api_key=s.openai_api_key,
        api_version=s.openai_api_version,
        azure_deployment=s.chat_deployment,
        temperature=0,
    )


def audit_node(state: AuditState) -> dict[str, Any]:
    prompt = ChatPromptTemplate.from_messages([("system", AUDIT_SYSTEM_PROMPT), ("human", AUDIT_HUMAN_PROMPT)])
    chain = prompt | get_llm().with_structured_output(AuditResult)
    try:
        result: AuditResult = chain.invoke({
            "rules": format_rules(state["rules"]),
            "transcript": state.get("transcript") or "(no speech detected)",
            "ocr_text": state.get("ocr_text") or "(no on-screen text detected)",
        })
        report = ComplianceReport(
            status=derive_status(result.violations),
            summary=result.summary,
            violations=result.violations,
            video_url=state["video_url"],
            video_id=state.get("video_id"),
            rules_consulted=rule_labels(state["rules"]),
        )
        return {"report": report.model_dump(mode="json")}
    except Exception as exc:
        log.exception("Audit failed")
        return {"errors": [f"audit: {exc}"]}
