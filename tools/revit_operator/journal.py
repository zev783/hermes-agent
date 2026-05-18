"""Task journal support for the Revit operator prototype."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from .constants import DRAFT_LABEL
from .safety import validate_output_path


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def make_task_id(prefix: str = "task") -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{prefix}-{stamp}-{uuid4().hex[:8]}"


class TaskJournal:
    """Append-only task journal rooted inside the selected sandbox."""

    def __init__(self, sandbox: Path, task_id: str | None = None):
        self.sandbox = sandbox.resolve()
        self.task_id = task_id or make_task_id("revit")
        self.run_dir = self.sandbox / "revit_operator_runs" / self.task_id
        self.screenshots_dir = self.run_dir / "screenshots"
        self.metadata_dir = self.run_dir / "metadata"
        self.journal_path = self.run_dir / "journal.jsonl"
        self.summary_path = self.run_dir / "summary.md"

        for path in [
            self.run_dir,
            self.screenshots_dir,
            self.metadata_dir,
        ]:
            error = validate_output_path(path, self.sandbox)
            if error:
                raise ValueError(error)
            path.mkdir(parents=True, exist_ok=True)

        if not self.summary_path.exists():
            self.summary_path.write_text(
                "\n".join(
                    [
                        "# Revit Operator Task Journal",
                        "",
                        f"Label: {DRAFT_LABEL}",
                        f"Task ID: {self.task_id}",
                        f"Started: {utc_now()}",
                        "",
                        "## Events",
                        "",
                    ]
                ),
                encoding="utf-8",
            )

    def path_in_sandbox(self, relative: str | Path) -> Path:
        target = self.sandbox / relative
        error = validate_output_path(target, self.sandbox)
        if error:
            raise ValueError(error)
        return target

    def default_screenshot_path(self, suffix: str = "bmp") -> Path:
        name = f"screenshot-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.{suffix}"
        return self.screenshots_dir / name

    def default_metadata_path(self, suffix: str = "json") -> Path:
        name = f"metadata-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.{suffix}"
        return self.metadata_dir / name

    def write_entry(self, entry: dict) -> dict:
        record = {
            "timestamp": utc_now(),
            "task_id": self.task_id,
            **entry,
        }
        with self.journal_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, sort_keys=True) + "\n")

        summary_line = (
            f"- {record['timestamp']} `{record.get('command', 'unknown')}` "
            f"{record.get('result', {}).get('status', record.get('status', 'recorded'))}"
        )
        with self.summary_path.open("a", encoding="utf-8") as handle:
            handle.write(summary_line + "\n")
        return record

    def describe(self) -> dict:
        return {
            "task_id": self.task_id,
            "sandbox": str(self.sandbox),
            "run_dir": str(self.run_dir),
            "journal": str(self.journal_path),
            "summary": str(self.summary_path),
            "screenshots_dir": str(self.screenshots_dir),
            "metadata_dir": str(self.metadata_dir),
        }
