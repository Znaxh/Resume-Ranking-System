"""Optional Groq-powered job description expansion (lazy LLM, in-memory cache)."""
from __future__ import annotations

import hashlib
import os
from typing import Any, Dict, List, Literal, Optional

from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field

import app_config
from core.observability import get_logger, llm_expansion_calls_total
from prompts import JD_EXPANSION_HUMAN, JD_EXPANSION_SYSTEM

log = get_logger(__name__)

_JD_CACHE: dict[str, dict] = {}
_llm = None


class JDExpansion(BaseModel):
    required_skills: List[str] = Field(default_factory=list)
    preferred_skills: List[str] = Field(default_factory=list)
    experience_level: Literal["junior", "mid", "senior"] = "mid"
    key_responsibilities: List[str] = Field(default_factory=list)
    implicit_requirements: List[str] = Field(default_factory=list)


def _get_llm():
    global _llm
    if _llm is None:
        api_key = os.getenv("GROQ_API_KEY")
        if not api_key:
            return None
        from langchain_groq import ChatGroq

        _llm = ChatGroq(
            model="llama3-8b-8192",
            api_key=api_key,
            temperature=0.1,
            max_tokens=1024,
        )
    return _llm


def expand_jd(raw_jd: str) -> Optional[dict[str, Any]]:
    """
    Return structured expansion dict or None (missing key, disabled, or failure).
    Respects USE_LLM_JD_EXPANSION and caches by SHA-256 of input text.
    """
    if not app_config.USE_LLM_JD_EXPANSION:
        llm_expansion_calls_total.labels(status="disabled").inc()
        return None

    if not (raw_jd or "").strip():
        llm_expansion_calls_total.labels(status="fallback").inc()
        return None

    key = hashlib.sha256(raw_jd.strip().encode("utf-8")).hexdigest()
    if key in _JD_CACHE:
        return _JD_CACHE[key]

    llm = _get_llm()
    if llm is None:
        log.warning("jd_expand_skipped", reason="no_groq_key")
        llm_expansion_calls_total.labels(status="fallback").inc()
        return None

    try:
        structured = llm.with_structured_output(JDExpansion)
        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", JD_EXPANSION_SYSTEM),
                ("human", JD_EXPANSION_HUMAN),
            ]
        )
        chain = prompt | structured
        out: JDExpansion = chain.invoke({"jd": raw_jd[: app_config.MAX_JD_LENGTH]})
        data = out.model_dump()
        _JD_CACHE[key] = data
        llm_expansion_calls_total.labels(status="success").inc()
        return data
    except Exception as exc:
        log.warning("jd_expand_failed", error=str(exc))
        llm_expansion_calls_total.labels(status="fallback").inc()
        return None


def jd_expansion_to_context_block(expanded: dict[str, Any]) -> str:
    """Append-friendly text for algorithm scoring."""
    lines = []
    if expanded.get("required_skills"):
        lines.append("Required skills: " + ", ".join(expanded["required_skills"][:40]))
    if expanded.get("preferred_skills"):
        lines.append("Preferred skills: " + ", ".join(expanded["preferred_skills"][:40]))
    lines.append(f"Experience level: {expanded.get('experience_level', 'mid')}")
    if expanded.get("key_responsibilities"):
        lines.append(
            "Key responsibilities: " + "; ".join(expanded["key_responsibilities"][:12])
        )
    if expanded.get("implicit_requirements"):
        lines.append(
            "Implicit requirements: " + "; ".join(expanded["implicit_requirements"][:12])
        )
    return "\n".join(lines)


def clear_jd_cache_for_tests():
    _JD_CACHE.clear()
