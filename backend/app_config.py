"""Single source of truth for app-wide limits and feature flags (env-overridable)."""
import os

MAX_FILE_SIZE_MB = int(os.getenv("MAX_FILE_SIZE_MB", "10"))
MAX_FILES_PER_REQUEST = int(os.getenv("MAX_FILES_PER_REQUEST", "10"))
MAX_JD_LENGTH = int(os.getenv("MAX_JD_LENGTH", "10000"))
ALLOWED_EXTENSIONS = frozenset(
    ext.strip().lower().lstrip(".")
    for ext in os.getenv("ALLOWED_EXTENSIONS", "pdf,docx,doc,txt").split(",")
    if ext.strip()
)

USE_LLM_JD_EXPANSION = os.getenv("USE_LLM_JD_EXPANSION", "false").lower() in (
    "1",
    "true",
    "yes",
)
USE_LLM_EXPLANATIONS = os.getenv("USE_LLM_EXPLANATIONS", "false").lower() in (
    "1",
    "true",
    "yes",
)

MAX_CONTENT_LENGTH_BYTES = MAX_FILE_SIZE_MB * MAX_FILES_PER_REQUEST * 1024 * 1024
