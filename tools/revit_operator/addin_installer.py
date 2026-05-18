"""Install/check helper for the Hermes Revit in-process add-in."""

from __future__ import annotations

from pathlib import Path

from .journal import TaskJournal
from .safety import authorize, classify_action

ADDIN_GUID = "9B9E5F15-C0B3-4D2A-8E4D-5F7D07F81A11"
ADDIN_NAME = "Hermes Revit Operator"


def addin_source_dir() -> Path:
    return Path(__file__).resolve().parent / "addin"


def default_assembly_candidates() -> list[Path]:
    source_dir = addin_source_dir()
    return [
        source_dir / "bin" / "Release" / "net8.0-windows-current" / "HermesRevitOperator.dll",
        source_dir / "bin" / "Release" / "net8.0-windows" / "HermesRevitOperator.dll",
    ]


def default_assembly_path() -> Path:
    existing = [path for path in default_assembly_candidates() if path.exists()]
    if existing:
        return max(existing, key=lambda path: path.stat().st_mtime)
    return default_assembly_candidates()[-1]


def is_default_local_assembly_path(path: Path) -> bool:
    normalized = path.resolve()
    return any(
        normalized == candidate.resolve()
        for candidate in default_assembly_candidates()
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
    addins_root = addins_root or default_addins_root()
    assembly_path = (assembly_path or default_assembly_path()).resolve()
    target_dir = addins_root / revit_version
    target_manifest = target_dir / "HermesRevitOperator.addin"
    payload = {
        "revit_version": revit_version,
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
        "build_prerequisite": "Install a .NET SDK and ensure RevitAPI.dll/RevitAPIUI.dll are present.",
    }
    if dry_run:
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
