"""Constants for the Revit human-operator prototype."""

from __future__ import annotations

import os
from pathlib import Path

APP_NAME = "revit-operator"

SAFE_PROJECT_ROOT = Path(
    r"C:\Users\zeviel.persellin\IdeaProjects\Tools\_Hermes_WorkingCopies"
    r"\24522_St_John_XXIII_Youth_Pavilion"
)
SAFE_SANDBOX_ROOT = SAFE_PROJECT_ROOT / "_AI_Hermes_Sandbox_DO_NOT_USE_FOR_PERMIT"
CURRENT_TEST_MODEL = (
    SAFE_PROJECT_ROOT
    / "Drawings"
    / "Working Drawings"
    / "24522 St John XXIII Youth Pavilion-Structural_Current Working-R25-BIM.rvt"
)

DRAFT_LABEL = "DRAFT / NOT FOR PERMIT / REQUIRES PE REVIEW"

ENV_SANDBOX = "HERMES_REVIT_OPERATOR_SANDBOX"
ENV_ALLOW_EXTERNAL_SANDBOX = "HERMES_REVIT_OPERATOR_ALLOW_EXTERNAL_SANDBOX"


def default_sandbox_root() -> Path:
    """Return the configured sandbox root, defaulting to the known safe copy."""

    configured = os.getenv(ENV_SANDBOX)
    return Path(configured) if configured else SAFE_SANDBOX_ROOT


def truthy_env(name: str) -> bool:
    value = os.getenv(name, "")
    return value.strip().lower() in {"1", "true", "yes", "on"}
