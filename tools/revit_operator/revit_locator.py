"""Locate installed Autodesk Revit executables."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

from .constants import CURRENT_TEST_MODEL, SAFE_PROJECT_ROOT, SAFE_SANDBOX_ROOT
from .version_support import (
    SUPPORTED_REVIT_VERSIONS,
    default_revit_install_dir,
    normalize_revit_version,
    validate_revit_version,
)


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
            version = normalize_revit_version(child.name.rsplit(" ", 1)[-1])
            if version in SUPPORTED_REVIT_VERSIONS:
                versions[version] = str(exe)
    return dict(sorted(versions.items()))


def resolve_revit_exe(version: str | None = None, explicit: str | None = None) -> Path | None:
    if explicit:
        path = Path(explicit)
        return path if path.exists() else None
    if version:
        normalized, error = validate_revit_version(version)
        if error:
            return None
        default_exe = default_revit_install_dir(normalized) / "Revit.exe"
        if default_exe.exists():
            return default_exe
        versions = installed_revit_versions()
        if normalized in versions:
            return Path(versions[normalized])
        return None
    versions = installed_revit_versions()
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


def list_safe_project_models(
    root: Path | None = None,
    *,
    current_model: Path | None = None,
    include_sandbox: bool = False,
    limit: int = 100,
) -> dict:
    """List local RVT models under the known copied-project area without opening them."""

    project_root = root or SAFE_PROJECT_ROOT
    marker_model = current_model or CURRENT_TEST_MODEL
    root_exists = project_root.exists()
    models: list[dict] = []
    if root_exists:
        sandbox_root = (
            SAFE_SANDBOX_ROOT
            if project_root == SAFE_PROJECT_ROOT
            else project_root / SAFE_SANDBOX_ROOT.name
        )
        sandbox_key = _path_key(sandbox_root)
        for path in project_root.rglob("*.rvt"):
            if not include_sandbox and _path_key(path).startswith(sandbox_key):
                continue
            models.append(_safe_model_record(path, project_root=project_root, current_model=marker_model))
    models.sort(
        key=lambda item: (
            not item["is_current_test_model"],
            -(item["bytes"] or 0),
            item["relative_path"].casefold(),
        )
    )
    if limit >= 0:
        models = models[:limit]
    current_record = next((item for item in models if item["is_current_test_model"]), None)
    return {
        "success": True,
        "read_only": True,
        "project_root": str(project_root),
        "project_root_exists": root_exists,
        "sandbox_skipped_by_default": not include_sandbox,
        "include_sandbox": bool(include_sandbox),
        "current_test_model": {
            "path": str(marker_model),
            "exists": marker_model.exists(),
            "listed": bool(current_record),
            "inferred_revit_version": infer_revit_version_from_model(marker_model),
        },
        "model_count": len(models),
        "models": models,
        "note": "Inventory only. No Revit process, model file, UI state, save, sync, or metadata export was changed.",
    }


def _safe_model_record(path: Path, *, project_root: Path, current_model: Path) -> dict:
    stat = path.stat()
    version = infer_revit_version_from_model(path)
    relative = _safe_relative(path, project_root)
    is_current = _path_key(path) == _path_key(current_model)
    command = f'agent-model-open-choreography --model "{path}"'
    if version:
        command += f" --revit-version {version}"
    return {
        "path": str(path),
        "relative_path": relative,
        "name": path.name,
        "bytes": stat.st_size,
        "size_mb": round(stat.st_size / (1024 * 1024), 2),
        "last_write_time_utc": datetime.fromtimestamp(
            stat.st_mtime,
            timezone.utc,
        ).isoformat().replace("+00:00", "Z"),
        "inferred_revit_version": version,
        "is_current_test_model": is_current,
        "example_role": "current_structural_r25_test_model" if is_current else None,
        "safe_dry_run_command": command,
        "safe_dry_run_argv": [
            "agent-model-open-choreography",
            "--model",
            str(path),
            *(["--revit-version", version] if version else []),
        ],
    }


def _safe_relative(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def _path_key(path: Path) -> str:
    return str(path.resolve(strict=False)).casefold()
