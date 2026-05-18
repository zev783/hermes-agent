"""Locate installed Autodesk Revit executables."""

from __future__ import annotations

import re
from pathlib import Path

from .constants import CURRENT_TEST_MODEL


DEFAULT_AUTODESK_ROOT = Path(r"C:\Program Files\Autodesk")


def infer_revit_version_from_model(path: Path) -> str | None:
    """Infer the expected Revit major year from common filename markers."""

    name = path.name
    match = re.search(r"(?:^|[-_\s])R(\d{2})(?:[-_\s.]|$)", name, re.IGNORECASE)
    if match:
        return f"20{match.group(1)}"
    match = re.search(r"(?:^|[-_\s])(20\d{2})(?:[-_\s.]|$)", name)
    return match.group(1) if match else None


def installed_revit_versions(root: Path = DEFAULT_AUTODESK_ROOT) -> dict[str, str]:
    """Return detected Revit versions mapped to Revit.exe paths."""

    versions: dict[str, str] = {}
    if not root.exists():
        return versions
    for child in root.glob("Revit 20??"):
        exe = child / "Revit.exe"
        if exe.exists():
            version = child.name.rsplit(" ", 1)[-1]
            versions[version] = str(exe)
    return dict(sorted(versions.items()))


def resolve_revit_exe(version: str | None = None, explicit: str | None = None) -> Path | None:
    if explicit:
        path = Path(explicit)
        return path if path.exists() else None
    versions = installed_revit_versions()
    if version and version in versions:
        return Path(versions[version])
    if versions:
        latest = sorted(versions)[-1]
        return Path(versions[latest])
    return None


def default_test_model_info() -> dict:
    return {
        "path": str(CURRENT_TEST_MODEL),
        "exists": CURRENT_TEST_MODEL.exists(),
        "inferred_revit_version": infer_revit_version_from_model(CURRENT_TEST_MODEL),
    }
