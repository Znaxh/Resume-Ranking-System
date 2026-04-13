"""
Versioned prompt templates for LLM features (JD expansion, explanations).

Bump VERSION when changing wording so responses can be traced.
"""

VERSION = "v1.0"

JD_EXPANSION_SYSTEM = (
    "Extract structured hiring requirements from the job description. "
    "Be concise; use short skill phrases. JSON-compatible fields only."
)

JD_EXPANSION_HUMAN = "{jd}"

EXPLANATION_SYSTEM = (
    "You write concise, fair hiring feedback. Exactly 3 short sentences:\n"
    "1) What the candidate is strong at for this role.\n"
    "2) The main gap lowering the match score.\n"
    "3) One concrete action to improve the application.\n"
    "Stay neutral; no protected traits; no discriminatory language."
)

EXPLANATION_HUMAN = (
    "Match score (0-100): {score}\n"
    "Position: {position}\n"
    "Resume excerpt:\n{resume}\n\nJob excerpt:\n{jd}\n\n"
    "Matched signals: {tops}\nGaps: {miss}\n"
)
