"""Trust/sign helper for the local Hermes Revit add-in."""

from __future__ import annotations

import subprocess
from pathlib import Path

from .addin_installer import default_assembly_path
from .journal import TaskJournal
from .safety import authorize, classify_action

CERT_SUBJECT = "CN=Hermes Revit Operator Local Code Signing"


def trust_addin(
    journal: TaskJournal,
    *,
    assembly_path: Path | None = None,
    dry_run: bool = True,
    approval_token: str | None = None,
) -> dict:
    assembly_path = (assembly_path or default_assembly_path()).resolve()
    payload = {
        "assembly_path": str(assembly_path),
        "certificate_subject": CERT_SUBJECT,
        "stores": [
            r"Cert:\CurrentUser\My",
            r"Cert:\CurrentUser\Root",
            r"Cert:\CurrentUser\TrustedPublisher",
        ],
    }
    decision = classify_action("trust-addin", payload)
    allowed, reason = authorize(decision, approval_token)
    result = {
        "success": False,
        "dry_run": dry_run,
        "policy": decision.to_dict(),
        "authorization": {"allowed": allowed, "reason": reason},
        "assembly_path": str(assembly_path),
        "assembly_exists": assembly_path.exists(),
        "certificate_subject": CERT_SUBJECT,
        "impact": (
            "Creates/reuses a CurrentUser code-signing certificate, imports it "
            "to CurrentUser Root and TrustedPublisher, and signs the add-in DLL."
        ),
    }
    if dry_run:
        result["success"] = True
        result["next_step"] = f"Re-run with --execute --approval-token {decision.approval_token}"
    elif not allowed:
        result["error"] = reason
    elif not assembly_path.exists():
        result["error"] = "Add-in assembly does not exist; build it before signing."
    else:
        completed = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(Path(__file__).resolve().parent / "addin" / "trust_addin.ps1"),
                "-AssemblyPath",
                str(assembly_path),
                "-Subject",
                CERT_SUBJECT,
            ],
            text=True,
            capture_output=True,
            check=False,
        )
        result["stdout"] = completed.stdout
        result["stderr"] = completed.stderr
        result["returncode"] = completed.returncode
        result["success"] = completed.returncode == 0
        if completed.returncode != 0:
            result["error"] = "trust_addin.ps1 failed."

    journal.write_entry(
        {
            "command": "trust-addin",
            "requested_action": payload,
            "risk_classification": decision.to_dict(),
            "approval_status": result["authorization"],
            "result": {
                "status": "dry_run" if dry_run else ("trusted" if result["success"] else "failed"),
                "success": result["success"],
            },
            "output_files": [str(assembly_path)],
        }
    )
    return result
