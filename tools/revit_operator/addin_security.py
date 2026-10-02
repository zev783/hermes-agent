"""Read-only preflight for Revit unsigned add-in startup prompts."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Callable

from .addin_installer import default_addins_root, default_assembly_path
from .addin_trust import CERT_SUBJECT
from .bridge import _file_info, _normalized_path_text, _read_manifest_assembly
from .journal import TaskJournal
from .safety import classify_action
from .version_support import target_framework_for_revit_version, validate_revit_version

EXPECTED_ASSEMBLY_NAME = "HermesRevitOperator.dll"

SignatureProbe = Callable[[Path], dict]


def addin_security_preflight(
    journal: TaskJournal,
    *,
    revit_version: str = "2025",
    addins_root: Path | None = None,
    assembly_path: Path | None = None,
    signature_probe: SignatureProbe | None = None,
) -> dict:
    """Verify local Hermes add-in paths before an unsigned-add-in prompt is answered."""

    normalized_version, version_error = validate_revit_version(revit_version)
    addins_root = (addins_root or default_addins_root()).resolve()
    expected_assembly = (assembly_path or default_assembly_path(normalized_version)).resolve()
    manifest_path = addins_root / (normalized_version or revit_version) / "HermesRevitOperator.addin"
    manifest = _read_manifest_assembly(manifest_path)
    manifest_assembly_text = manifest.get("assembly_path")
    manifest_assembly = Path(str(manifest_assembly_text)).resolve() if manifest_assembly_text else None
    manifest_points_to_expected = bool(
        manifest_assembly
        and _normalized_path_text(manifest_assembly) == _normalized_path_text(expected_assembly)
    )
    assembly_info = _file_info(expected_assembly)
    signature = (signature_probe or _authenticode_signature)(expected_assembly)
    signature_status = str(signature.get("status") or "").casefold()
    signer_subject = str(signature.get("signer_subject") or "")
    expected_subject = CERT_SUBJECT.removeprefix("CN=")
    signature_valid = signature_status == "valid"
    signer_expected = expected_subject.casefold() in signer_subject.casefold() if signer_subject else False

    checks = [
        _check(
            "revit_version_supported",
            version_error is None,
            f"Revit {normalized_version} is in the supported 2022-2027 range.",
            version_error or "Unsupported Revit version.",
        ),
        _check(
            "manifest_present",
            manifest_path.exists(),
            f"Revit add-in manifest exists at {manifest_path}.",
            f"Revit add-in manifest is missing at {manifest_path}.",
        ),
        _check(
            "manifest_points_to_expected_assembly",
            manifest_points_to_expected,
            "Manifest Assembly path points to the expected Hermes operator DLL.",
            "Manifest Assembly path is missing or points somewhere other than the expected Hermes operator DLL.",
        ),
        _check(
            "assembly_present",
            expected_assembly.exists(),
            f"Hermes operator DLL exists at {expected_assembly}.",
            f"Hermes operator DLL is missing at {expected_assembly}.",
        ),
        _check(
            "assembly_name_expected",
            expected_assembly.name.casefold() == EXPECTED_ASSEMBLY_NAME.casefold(),
            f"Expected assembly name is {EXPECTED_ASSEMBLY_NAME}.",
            f"Assembly name is not {EXPECTED_ASSEMBLY_NAME}.",
        ),
        _check(
            "authenticode_valid",
            signature_valid,
            "DLL Authenticode signature is valid.",
            "DLL Authenticode signature is not valid or could not be verified.",
        ),
        _check(
            "signer_subject_expected",
            signer_expected,
            "DLL signer subject matches the Hermes local code-signing certificate.",
            "DLL signer subject is missing or does not match the Hermes local code-signing certificate.",
        ),
    ]
    expected_local_addin = version_error is None and all(
        check["passed"]
        for check in checks
        if check["name"]
        in {
            "manifest_present",
            "manifest_points_to_expected_assembly",
            "assembly_present",
            "assembly_name_expected",
        }
    )
    needs_trust_addin = expected_local_addin and not (signature_valid and signer_expected)
    can_consider_always_load = expected_local_addin
    payload = {
        "revit_version": normalized_version or revit_version,
        "manifest": str(manifest_path),
        "expected_assembly": str(expected_assembly),
    }
    decision = classify_action("addin-security-preflight", payload)
    result = {
        "success": True,
        "read_only": True,
        "status": "verified" if expected_local_addin and signature_valid and signer_expected else "needs_attention",
        "policy": decision.to_dict(),
        "revit_version": normalized_version or revit_version,
        "target_framework": target_framework_for_revit_version(normalized_version) if version_error is None else None,
        "paths": {
            "addins_root": str(addins_root),
            "manifest": str(manifest_path),
            "expected_assembly": str(expected_assembly),
            "manifest_assembly": str(manifest_assembly) if manifest_assembly else None,
        },
        "manifest": manifest,
        "assembly": assembly_info,
        "signature": signature,
        "checks": checks,
        "expected_local_hermes_addin": expected_local_addin,
        "needs_trust_addin": needs_trust_addin,
        "can_consider_always_load_after_human_approval": can_consider_always_load,
        "allowed_dialog_button": "Always Load" if can_consider_always_load else None,
        "blocked_dialog_buttons": ["Load Once", "Do Not Load"] if can_consider_always_load else ["Load Once", "Always Load", "Do Not Load"],
        "recommended_action": _recommendation(
            expected_local_addin=expected_local_addin,
            signature_valid=signature_valid,
            signer_expected=signer_expected,
        ),
        "safety_note": (
            "This preflight is read-only. It does not click the startup prompt, sign the DLL, "
            "trust a certificate, restart Revit, save, sync, or modify the model."
        ),
    }
    journal.write_entry(
        {
            "command": "addin-security-preflight",
            "requested_action": payload,
            "risk_classification": decision.to_dict(),
            "approval_status": {"allowed": True, "reason": "Read-only add-in prompt preflight."},
            "result": {
                "status": result["status"],
                "expected_local_hermes_addin": expected_local_addin,
                "needs_trust_addin": needs_trust_addin,
            },
            "output_files": [],
        }
    )
    return result


def _authenticode_signature(path: Path) -> dict:
    if not path.exists():
        return {"available": False, "status": "missing_assembly", "path": str(path)}
    if sys.platform != "win32":
        return {
            "available": False,
            "status": "unsupported_platform",
            "path": str(path),
            "reason": "Get-AuthenticodeSignature is only available on Windows PowerShell.",
        }

    literal_path = str(path).replace("'", "''")
    script = (
        f"$sig=Get-AuthenticodeSignature -LiteralPath '{literal_path}';"
        "[pscustomobject]@{"
        "Status=$sig.Status.ToString();"
        "StatusMessage=$sig.StatusMessage;"
        "SignerSubject=if($sig.SignerCertificate){$sig.SignerCertificate.Subject}else{$null};"
        "SignerThumbprint=if($sig.SignerCertificate){$sig.SignerCertificate.Thumbprint}else{$null}"
        "} | ConvertTo-Json -Compress"
    )
    completed = subprocess.run(
        ["powershell", "-NoProfile", "-Command", script],
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        return {
            "available": False,
            "status": "probe_failed",
            "path": str(path),
            "returncode": completed.returncode,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
        }
    try:
        payload = json.loads(completed.stdout or "{}")
    except json.JSONDecodeError as exc:
        return {
            "available": False,
            "status": "invalid_probe_output",
            "path": str(path),
            "error": str(exc),
            "stdout": completed.stdout,
        }
    return {
        "available": True,
        "path": str(path),
        "status": payload.get("Status"),
        "status_message": payload.get("StatusMessage"),
        "signer_subject": payload.get("SignerSubject"),
        "signer_thumbprint": payload.get("SignerThumbprint"),
    }


def _check(name: str, passed: bool, pass_reason: str, fail_reason: str) -> dict:
    return {
        "name": name,
        "passed": bool(passed),
        "reason": pass_reason if passed else fail_reason,
    }


def _recommendation(*, expected_local_addin: bool, signature_valid: bool, signer_expected: bool) -> str:
    if not expected_local_addin:
        return (
            "Do not click Load or Always Load. The visible unsigned-add-in prompt is not verified "
            "as the expected local Hermes operator add-in."
        )
    if signature_valid and signer_expected:
        return (
            "The local Hermes operator add-in paths and signature are verified. If Revit still shows "
            "the prompt, click Always Load only with an exact human approval token."
        )
    return (
        "Prefer running trust-addin with explicit approval and restarting Revit. If the human needs "
        "to unblock this startup now, click Always Load only after approving the exact verified Hermes prompt."
    )
