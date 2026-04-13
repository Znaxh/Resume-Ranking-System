"""Groq-based match explanations with template fallback."""
from __future__ import annotations

import os
from typing import Any, List

from langchain_core.prompts import ChatPromptTemplate

import app_config
from core.observability import get_logger
from prompts import EXPLANATION_HUMAN, EXPLANATION_SYSTEM

log = get_logger(__name__)

_llm = None


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
            temperature=0.2,
            max_tokens=300,
        )
    return _llm


def template_explanation(
    combined_result: dict[str, Any],
    job_description: str,
    position: str,
) -> str:
    """Same style as legacy app._generate_explanation (deterministic)."""
    try:
        score = float(combined_result["combined_score"])
        algorithm_scores = combined_result["algorithm_scores"]

        if score >= 0.8:
            rating = "Excellent match"
        elif score >= 0.6:
            rating = "Good match"
        elif score >= 0.4:
            rating = "Fair match"
        else:
            rating = "Poor match"

        best_alg = max(
            algorithm_scores.keys(),
            key=lambda k: float(algorithm_scores[k]["score"]),
            default="unknown",
        )
        best_score = float(algorithm_scores.get(best_alg, {}).get("score", 0))

        explanation = (
            f"{rating} for {position} position (Overall: {score:.1%}). "
            f"Strongest performance in {best_alg.upper()} analysis ({best_score:.1%}). "
        )
        if any(
            "academic_trained" in alg_data.get("details", {}).get("model_type", "")
            for alg_data in algorithm_scores.values()
        ):
            explanation += "Prediction based on trained ML models. "
        if "ner" in algorithm_scores:
            ner_details = algorithm_scores["ner"].get("details", {})
            skill_categories = len(ner_details.get("extracted_skills", {}))
            if skill_categories > 0:
                explanation += f"Identified skills across {skill_categories} categories. "
        if "cosine" in algorithm_scores:
            cosine_details = algorithm_scores["cosine"].get("details", {})
            matching_terms = len(cosine_details.get("top_matching_terms", []))
            if matching_terms > 0:
                explanation += f"Found {matching_terms} key matching terms. "
        return explanation
    except Exception as exc:
        log.warning("template_explanation_failed", error=str(exc))
        return f"Analysis completed with combined score of {float(combined_result.get('combined_score', 0)):.1%}"


def explain_match(
    resume_text: str,
    job_description: str,
    match_score: float,
    top_matched_skills: List[str],
    missing_skills: List[str],
    combined_result: dict[str, Any],
    position: str,
) -> str:
    """
    Three-sentence LLM explanation when USE_LLM_EXPLANATIONS and GROQ_API_KEY are set;
    otherwise template_explanation from combined_result.
    """
    if not app_config.USE_LLM_EXPLANATIONS:
        return template_explanation(combined_result, job_description, position)

    llm = _get_llm()
    if llm is None:
        return template_explanation(combined_result, job_description, position)

    r = (resume_text or "")[:500]
    j = (job_description or "")[:500]
    tops = ", ".join(top_matched_skills[:12]) or "(none listed)"
    miss = ", ".join(missing_skills[:12]) or "(none listed)"
    pct = min(100.0, max(0.0, float(match_score)))

    prompt = ChatPromptTemplate.from_messages(
        [
            ("system", EXPLANATION_SYSTEM),
            ("human", EXPLANATION_HUMAN),
        ]
    )

    try:
        chain = prompt | llm
        msg = chain.invoke(
            {
                "score": round(pct, 1),
                "position": position,
                "resume": r,
                "jd": j,
                "tops": tops,
                "miss": miss,
            }
        )
        text = getattr(msg, "content", str(msg)).strip()
        if text:
            return text
    except Exception as exc:
        log.warning("llm_explain_failed", error=str(exc))

    return template_explanation(combined_result, job_description, position)
