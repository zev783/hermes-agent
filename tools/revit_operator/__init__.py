"""Safe local Revit human-operator prototype.

The package is intentionally a standalone command surface.  It is packaged
with Hermes, but it does not register a built-in agent tool at import time.
"""

from .constants import DRAFT_LABEL, SAFE_PROJECT_ROOT, SAFE_SANDBOX_ROOT
from .safety import classify_action, classify_dialog

__all__ = [
    "DRAFT_LABEL",
    "SAFE_PROJECT_ROOT",
    "SAFE_SANDBOX_ROOT",
    "classify_action",
    "classify_dialog",
]
