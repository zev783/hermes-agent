"""Revit version compatibility metadata for the Hermes operator layer."""

from __future__ import annotations

from pathlib import Path

SUPPORTED_REVIT_VERSIONS = ("2022", "2023", "2024", "2025", "2026", "2027")

REVIT_TARGET_FRAMEWORK_BY_VERSION = {
    "2022": "net48",
    "2023": "net48",
    "2024": "net48",
    "2025": "net8.0-windows",
    "2026": "net8.0-windows",
    "2027": "net10.0-windows",
}

REVIT_DEFINE_CONSTANT_BY_VERSION = {
    version: f"REVIT{version}" for version in SUPPORTED_REVIT_VERSIONS
}


def normalize_revit_version(version: str | int | None) -> str:
    """Normalize common Revit version tokens into a four-digit year string."""

    text = str(version or "").strip()
    if not text:
        return ""
    if text.upper().startswith("R") and len(text) == 3 and text[1:].isdigit():
        return f"20{text[1:]}"
    if len(text) == 2 and text.isdigit():
        return f"20{text}"
    return text


def is_supported_revit_version(version: str | int | None) -> bool:
    return normalize_revit_version(version) in SUPPORTED_REVIT_VERSIONS


def validate_revit_version(version: str | int | None) -> tuple[str, str | None]:
    normalized = normalize_revit_version(version)
    if normalized in SUPPORTED_REVIT_VERSIONS:
        return normalized, None
    supported = ", ".join(SUPPORTED_REVIT_VERSIONS)
    observed = normalized or "(missing)"
    return normalized, f"Unsupported Revit version {observed!r}. Supported versions: {supported}."


def target_framework_for_revit_version(version: str | int | None) -> str:
    normalized, error = validate_revit_version(version)
    if error:
        raise ValueError(error)
    return REVIT_TARGET_FRAMEWORK_BY_VERSION[normalized]


def define_constant_for_revit_version(version: str | int | None) -> str:
    normalized, error = validate_revit_version(version)
    if error:
        raise ValueError(error)
    return REVIT_DEFINE_CONSTANT_BY_VERSION[normalized]


def default_revit_install_dir(version: str | int | None) -> Path:
    normalized, error = validate_revit_version(version)
    if error:
        raise ValueError(error)
    return Path(r"C:\Program Files\Autodesk") / f"Revit {normalized}"


def assembly_subdir_for_revit_version(version: str | int | None, configuration: str = "Release") -> Path:
    normalized, error = validate_revit_version(version)
    if error:
        raise ValueError(error)
    framework = REVIT_TARGET_FRAMEWORK_BY_VERSION[normalized]
    return Path("bin") / configuration / f"{framework}-r{normalized}"


def version_support_matrix(installed_versions: dict[str, str] | None = None) -> dict:
    installs = installed_versions or {}
    rows = []
    for version in SUPPORTED_REVIT_VERSIONS:
        rows.append(
            {
                "revit_version": version,
                "target_framework": REVIT_TARGET_FRAMEWORK_BY_VERSION[version],
                "define_constant": REVIT_DEFINE_CONSTANT_BY_VERSION[version],
                "default_install_dir": str(default_revit_install_dir(version)),
                "installed_revit_exe": installs.get(version),
                "installed": version in installs,
            }
        )
    return {
        "supported_versions": list(SUPPORTED_REVIT_VERSIONS),
        "version_count": len(SUPPORTED_REVIT_VERSIONS),
        "min_version": SUPPORTED_REVIT_VERSIONS[0],
        "max_version": SUPPORTED_REVIT_VERSIONS[-1],
        "target_frameworks": dict(REVIT_TARGET_FRAMEWORK_BY_VERSION),
        "rows": rows,
    }
