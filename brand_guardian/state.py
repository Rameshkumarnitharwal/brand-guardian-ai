"""Graph state and the structured compliance-report schema."""

import operator
from enum import Enum
from typing import Annotated, Any, TypedDict

from pydantic import BaseModel, Field


class Severity(str, Enum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class Violation(BaseModel):
    category: str = Field(description="Violation type, e.g. 'Absolute Guarantee', 'Missing Disclosure', 'Misleading Claim'.")
    severity: Severity
    claim: str = Field(description="The exact or near-exact claim from the video that violates the rule.")
    timestamp: str | None = Field(default=None, description="Timestamp in the video where the claim appears, if known.")
    source: str = Field(description="'transcript' or 'on-screen text'.")
    rule_reference: str = Field(description="The rulebook and section/page the claim violates.")
    explanation: str = Field(description="Why this claim violates the rule.")
    recommendation: str = Field(description="How to fix or rephrase the claim to be compliant.")


class AuditResult(BaseModel):
    """What the LLM returns. Overall status is derived deterministically from severities."""

    summary: str = Field(description="2-4 sentence overview of the video's compliance posture.")
    violations: list[Violation] = Field(default_factory=list)


class ComplianceReport(AuditResult):
    status: str = Field(description="PASS, NEEDS_REVIEW, or FAIL.")
    video_url: str
    video_id: str | None = None
    rules_consulted: list[str] = Field(default_factory=list)


def derive_status(violations: list[Violation]) -> str:
    """FAIL on any CRITICAL/HIGH, NEEDS_REVIEW on only MEDIUM/LOW, PASS if clean."""
    if any(v.severity in (Severity.CRITICAL, Severity.HIGH) for v in violations):
        return "FAIL"
    if violations:
        return "NEEDS_REVIEW"
    return "PASS"


class AuditState(TypedDict, total=False):
    # Input
    video_url: str
    # Ingestion
    video_name: str
    blob_sas_url: str
    # Indexing & extraction
    video_id: str
    transcript: str
    ocr_text: str
    video_metadata: dict[str, Any]
    # Retrieval
    rules: list[dict[str, Any]]
    # Reasoning
    report: dict[str, Any]
    # Errors accumulate across nodes
    errors: Annotated[list[str], operator.add]
