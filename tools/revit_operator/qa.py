"""Draft QA workflow scaffolding from Revit metadata snapshots."""

from __future__ import annotations

import json
from pathlib import Path

from .constants import DRAFT_LABEL
from .journal import TaskJournal, utc_now
from .safety import validate_output_path


def generate_qa_report(journal: TaskJournal, output: Path | None = None) -> dict:
    metadata_path = journal.sandbox / "bridge" / "metadata_snapshot.json"
    if not metadata_path.exists():
        metadata_path = _latest_metadata_file(journal)

    metadata = {}
    source = None
    if metadata_path and metadata_path.exists():
        source = str(metadata_path)
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))

    output_path = output or (journal.run_dir / "qa_report.md")
    error = validate_output_path(output_path, journal.sandbox)
    if error:
        return {"success": False, "error": error}
    output_path.parent.mkdir(parents=True, exist_ok=True)

    findings = _findings(metadata)
    lines = [
        "# Revit QA Draft Report",
        "",
        f"Label: {DRAFT_LABEL}",
        f"Generated: {utc_now()}",
        f"Metadata source: {source or 'none'}",
        "",
        "## Document",
        "",
        f"- Title: {metadata.get('document', {}).get('title', 'unknown')}",
        f"- Path: {metadata.get('document', {}).get('path', 'unknown')}",
        f"- Revit version: {metadata.get('document', {}).get('revit_version', 'unknown')}",
        "",
        "## Counts",
        "",
    ]
    for key in ["levels", "grids", "views", "sheets", "titleblocks", "links", "warnings", "families", "types"]:
        value = metadata.get(key, [])
        lines.append(f"- {key}: {len(value) if isinstance(value, list) else 'unknown'}")
    lines.extend(["", "## Findings", ""])
    if findings:
        lines.extend(f"- {item}" for item in findings)
    else:
        lines.append("- No automated findings. Metadata may be missing or incomplete.")
    lines.extend(
        [
            "",
            "## Review Requirement",
            "",
            "This is a draft automation report and requires PE review before use.",
        ]
    )
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    journal.write_entry(
        {
            "command": "qa-report",
            "requested_action": {"metadata_source": source},
            "risk_classification": {
                "action": "qa-report",
                "risk": "low",
                "decision": "allow",
                "reason": "Draft report generation from sandbox metadata.",
                "approval_token": None,
            },
            "approval_status": {"allowed": True, "reason": "Read-only QA report."},
            "result": {"status": "written", "success": True},
            "output_files": [str(output_path)],
        }
    )
    return {
        "success": True,
        "path": str(output_path),
        "metadata_source": source,
        "findings": findings,
    }


def _latest_metadata_file(journal: TaskJournal) -> Path | None:
    candidates = sorted(journal.metadata_dir.glob("*.json"))
    return candidates[-1] if candidates else None


def _findings(metadata: dict) -> list[str]:
    findings: list[str] = []
    if not metadata:
        return ["No metadata snapshot was available; run export-metadata from the add-in bridge."]
    if not metadata.get("sheets"):
        findings.append("No sheets were present in the metadata snapshot.")
    if not metadata.get("grids"):
        findings.append("No grids were present in the metadata snapshot.")
    warnings = metadata.get("warnings") or []
    if warnings:
        findings.append(f"{len(warnings)} Revit warnings require review.")
    links = metadata.get("links") or []
    unloaded = [link for link in links if str(link.get("status", "")).lower() not in {"loaded", "unknown"}]
    if unloaded:
        findings.append(f"{len(unloaded)} links appear unloaded or unresolved.")
    return findings
