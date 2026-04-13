"""Lightweight batch-level fairness signals (no extra ML models)."""
from __future__ import annotations

from collections import Counter
from typing import Any, List, Optional

import numpy as np

_STOP = {
    "the",
    "and",
    "for",
    "with",
    "you",
    "will",
    "our",
    "are",
    "this",
    "that",
    "from",
    "your",
    "have",
    "has",
    "all",
    "any",
    "can",
    "may",
    "not",
    "but",
    "was",
    "were",
    "been",
    "being",
    "their",
    "they",
    "them",
    "who",
    "what",
    "when",
    "where",
    "which",
    "while",
    "into",
    "about",
    "other",
    "such",
    "than",
    "then",
    "there",
    "these",
    "those",
    "via",
    "per",
    "using",
    "use",
    "used",
    "including",
    "include",
    "includes",
    "required",
    "preferred",
    "years",
    "year",
    "experience",
}


def analyze_batch_fairness(
    job_description: str, scores: List[float]
) -> dict[str, Any]:
    """
    If one non-stopword dominates the JD text (>40% of tokens), emit a warning string.
    Always returns aggregate score variance / std for transparency.
    """
    arr = np.array([float(s) for s in scores], dtype=float) if scores else np.array([])
    var = float(np.var(arr)) if arr.size else 0.0
    std = float(np.std(arr)) if arr.size else 0.0

    text = (job_description or "").lower()
    words = [w for w in "".join(c if c.isalnum() or c.isspace() else " " for c in text).split() if len(w) > 2]
    content = [w for w in words if w not in _STOP]

    warning: Optional[str] = None
    dominant: Optional[str] = None
    if content:
        top, cnt = Counter(content).most_common(1)[0]
        share = cnt / len(content)
        if share > 0.4:
            dominant = top
            warning = (
                "Warning: scores may be heavily influenced by a single term in the job description"
            )

    return {
        "fairness_warning": warning,
        "score_variance": var,
        "score_std_dev": std,
        "dominant_jd_term": dominant,
    }
