"""Risk scan domain model.

Represents the result of a Range Risk API screening call for a Solana
wallet, normalized into the shape consumed by the BagsVault frontend.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

Verdict = Literal["APPROVE", "REVIEW", "BLOCK"]
CheckStatus = Literal["clean", "flagged"]


class CheckResult(BaseModel):
    """Single category screening result, e.g. OFAC sanctions match."""

    model_config = ConfigDict(extra="ignore")

    category: str
    label: str
    status: CheckStatus


# Detection matrix shown in the frontend Compliance page. Matches the
# categories used by Range Risk's Solana screening offering. Used as a
# default scaffold when the upstream response doesn't itemize categories.
DEFAULT_CHECKS: list[dict[str, str]] = [
    {"category": "Regulatory", "label": "OFAC / SDN sanctions list"},
    {"category": "Threat Intel", "label": "Known hacker addresses"},
    {"category": "Threat Intel", "label": "Ransomware clusters"},
    {"category": "Threat Intel", "label": "Darknet market exposure"},
    {"category": "Mixer", "label": "Tornado Cash interaction"},
    {"category": "DeFi", "label": "Bridge exploit proceeds"},
    {"category": "Fraud", "label": "Pig-butchering fund flows"},
    {"category": "NFT", "label": "Stolen NFT proceeds"},
]


def _verdict_from_score(score: int) -> Verdict:
    if score < 20:
        return "APPROVE"
    if score < 50:
        return "REVIEW"
    return "BLOCK"


def _coerce_score(raw: Any) -> int:
    """Pull a 0-100 integer score out of a heterogeneous Range payload."""

    if raw is None:
        return 0
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return 0
    # Range sometimes returns a 0-1 normalized risk score.
    if 0 <= value <= 1:
        value *= 100
    return max(0, min(100, int(round(value))))


class RiskScan(BaseModel):
    """Normalized risk-scan result, persisted to ``db.risk_scans`` and
    returned from the ``/api/compliance/scan`` endpoints.
    """

    model_config = ConfigDict(extra="ignore")

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    address: str
    score: int = Field(ge=0, le=100)
    verdict: Verdict
    flags: list[str] = Field(default_factory=list)
    checks: list[CheckResult] = Field(default_factory=list)
    scanned_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @classmethod
    def from_range_response(cls, address: str, raw: dict[str, Any]) -> "RiskScan":
        """Normalize a raw Range Risk response into a ``RiskScan``.

        The Range API exposes several risk-score endpoints whose response shape
        varies. We defensively pull from a handful of likely keys so this code
        keeps working when the upstream contract drifts. Unknown fields are
        ignored.

        Score thresholds:
            * < 20  -> APPROVE
            * 20-49 -> REVIEW
            * >= 50 -> BLOCK
        """

        # Many Range responses wrap the body in {"data": {...}}.
        body_candidate = raw.get("data")
        body: dict[str, Any] = body_candidate if isinstance(body_candidate, dict) else raw

        score = _coerce_score(
            body.get("score") or body.get("risk_score") or body.get("riskScore") or body.get("risk")
        )

        # Verdict can be supplied directly; otherwise derive from score.
        upstream_verdict = body.get("verdict") or body.get("decision") or body.get("recommendation")
        verdict: Verdict = _verdict_from_score(score)
        if isinstance(upstream_verdict, str):
            upper = upstream_verdict.upper()
            if upper in ("APPROVE", "REVIEW", "BLOCK"):
                verdict = upper  # type: ignore[assignment]

        raw_flags = body.get("flags") or body.get("tags") or body.get("categories") or []
        flags: list[str] = []
        if isinstance(raw_flags, list):
            for flag in raw_flags:
                if isinstance(flag, str):
                    flags.append(flag)
                elif isinstance(flag, dict):
                    label = flag.get("label") or flag.get("name") or flag.get("category")
                    if isinstance(label, str):
                        flags.append(label)

        # Build the detection matrix. If the upstream provides itemized checks,
        # use them; else fall back to the default scaffold and mark categories
        # whose label matches a flag as flagged.
        checks: list[CheckResult] = []
        raw_checks = body.get("checks")
        if isinstance(raw_checks, list) and raw_checks:
            for c in raw_checks:
                if not isinstance(c, dict):
                    continue
                label = c.get("label") or c.get("name") or ""
                category = c.get("category") or "General"
                status_raw = c.get("status") or ("flagged" if c.get("hit") else "clean")
                status: CheckStatus = "flagged" if str(status_raw).lower() == "flagged" else "clean"
                checks.append(CheckResult(category=str(category), label=str(label), status=status))
        else:
            lower_flags = [f.lower() for f in flags]
            for entry in DEFAULT_CHECKS:
                hit = any(
                    f in entry["label"].lower() or entry["label"].lower() in f for f in lower_flags
                )
                checks.append(
                    CheckResult(
                        category=entry["category"],
                        label=entry["label"],
                        status="flagged" if hit else "clean",
                    )
                )

        return cls(
            address=address,
            score=score,
            verdict=verdict,
            flags=flags,
            checks=checks,
        )
