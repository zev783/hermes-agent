"""Install/check helper for the Hermes Revit in-process add-in."""

from __future__ import annotations

from pathlib import Path

from .journal import TaskJournal
from .safety import authorize, classify_action
from .version_support import (
    assembly_subdir_for_revit_version,
    target_framework_for_revit_version,
    validate_revit_version,
)

ADDIN_GUID = "9B9E5F15-C0B3-4D2A-8E4D-5F7D07F81A11"
ADDIN_NAME = "Hermes Revit Operator"


def addin_source_dir() -> Path:
    return Path(__file__).resolve().parent / "addin"


def default_assembly_candidates(revit_version: str | None = None) -> list[Path]:
    source_dir = addin_source_dir()
    candidates: list[Path] = []
    if revit_version:
        normalized, error = validate_revit_version(revit_version)
        if error is None:
            candidates.append(source_dir / assembly_subdir_for_revit_version(normalized) / "HermesRevitOperator.dll")
    return [
        *candidates,
        source_dir / "bin" / "Release" / "net8.0-windows-current" / "HermesRevitOperator.dll",
        source_dir / "bin" / "Release" / "net8.0-windows" / "HermesRevitOperator.dll",
    ]


def default_assembly_path(revit_version: str | None = None) -> Path:
    candidates = default_assembly_candidates(revit_version)
    if revit_version:
        return candidates[0]
    existing = [path for path in candidates if path.exists()]
    if existing:
        return max(existing, key=lambda path: path.stat().st_mtime)
    return candidates[0] if revit_version else candidates[-1]


def is_default_local_assembly_path(path: Path, revit_version: str | None = None) -> bool:
    normalized = path.resolve()
    return any(
        normalized == candidate.resolve()
        for candidate in default_assembly_candidates(revit_version)
    )


def default_addins_root() -> Path:
    import os

    return Path(os.environ.get("APPDATA", "")) / "Autodesk" / "Revit" / "Addins"


def addin_manifest_text(assembly_path: Path) -> str:
    return f"""<?xml version="1.0" encoding="utf-8" standalone="no"?>
<RevitAddIns>
  <AddIn Type="Application">
    <Name>{ADDIN_NAME}</Name>
    <Assembly>{assembly_path}</Assembly>
    <AddInId>{ADDIN_GUID}</AddInId>
    <FullClassName>Hermes.RevitOperator.HermesRevitOperatorApp</FullClassName>
    <VendorId>HERM</VendorId>
    <VendorDescription>Hermes local Revit human-operator bridge</VendorDescription>
  </AddIn>
</RevitAddIns>
"""


def install_addin(
    journal: TaskJournal,
    *,
    revit_version: str = "2025",
    addins_root: Path | None = None,
    assembly_path: Path | None = None,
    dry_run: bool = True,
    approval_token: str | None = None,
) -> dict:
    normalized_version, version_error = validate_revit_version(revit_version)
    addins_root = addins_root or default_addins_root()
    assembly_path = (assembly_path or default_assembly_path(normalized_version)).resolve()
    target_dir = addins_root / normalized_version
    target_manifest = target_dir / "HermesRevitOperator.addin"
    payload = {
        "revit_version": normalized_version or revit_version,
        "target_manifest": str(target_manifest),
        "assembly_path": str(assembly_path),
    }
    decision = classify_action("install-addin", payload)
    allowed, reason = authorize(decision, approval_token)

    result = {
        "success": False,
        "dry_run": dry_run,
        "policy": decision.to_dict(),
        "authorization": {"allowed": allowed, "reason": reason},
        "target_manifest": str(target_manifest),
        "assembly_path": str(assembly_path),
        "assembly_exists": assembly_path.exists(),
        "source_project": str(addin_source_dir() / "HermesRevitOperator.csproj"),
        "target_framework": (
            target_framework_for_revit_version(normalized_version) if not version_error else None
        ),
        "build_prerequisite": (
            "Install the matching .NET SDK/reference assemblies and ensure "
            "RevitAPI.dll/RevitAPIUI.dll are present for the requested Revit version."
        ),
    }
    if version_error:
        result["error"] = version_error
    elif dry_run:
        result["success"] = True
        result["next_step"] = f"Build the add-in DLL, then re-run with --execute --approval-token {decision.approval_token}"
    elif not allowed:
        result["error"] = reason
    elif not assembly_path.exists():
        result["error"] = "Add-in assembly does not exist; build HermesRevitOperator.csproj first."
    else:
        target_dir.mkdir(parents=True, exist_ok=True)
        target_manifest.write_text(addin_manifest_text(assembly_path), encoding="utf-8")
        result["success"] = True
        result["installed"] = True

    journal.write_entry(
        {
            "command": "install-addin",
            "requested_action": payload,
            "risk_classification": decision.to_dict(),
            "approval_status": result["authorization"],
            "result": {
                "status": "dry_run" if dry_run else ("installed" if result["success"] else "failed"),
                "success": result["success"],
            },
            "output_files": [str(target_manifest)],
        }
    )
    return result
