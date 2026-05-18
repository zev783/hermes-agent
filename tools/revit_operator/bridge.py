"""Stub interface for a future in-process Revit add-in bridge."""

from __future__ import annotations

import json
import shutil
import time
import xml.etree.ElementTree as ET
from pathlib import Path

from .addin_installer import addin_source_dir, default_addins_root, default_assembly_path
from .constants import CURRENT_TEST_MODEL, DRAFT_LABEL
from .journal import utc_now
from .safety import validate_output_path

EXPECTED_BRIDGE_PROTOCOL_VERSION = "0.2"
EXPECTED_SOURCE_CAPABILITY_STAMP = "continuous-idling-status-file-retry-v2"


class RevitBridgeClient:
    """Read-only bridge contract used by the operator CLI.

    The first prototype does not assume a Revit add-in is installed.  Instead,
    it defines the file handoff that a future ExternalEvent-based add-in can
    satisfy without changing the CLI contract.
    """

    def __init__(self, sandbox: Path):
        self.sandbox = sandbox.resolve()
        self.bridge_dir = self.sandbox / "bridge"
        self.addin_status_path = self.bridge_dir / "addin_status.json"
        self.heartbeat_path = self.bridge_dir / "addin_heartbeat.json"
        self.active_document_path = self.bridge_dir / "active_document.json"
        self.metadata_snapshot_path = self.bridge_dir / "metadata_snapshot.json"
        self.command_results_path = self.bridge_dir / "command_results.jsonl"

    def bridge_status(self) -> dict:
        status = self._read_json_file(self.addin_status_path)
        heartbeat = self._read_json_file(self.heartbeat_path)
        connected = status.get("available") is True or heartbeat.get("available") is True
        result = {
            "available": connected,
            "status": "connected" if connected else "stub",
            "bridge_dir": str(self.bridge_dir),
            "addin_status_path": str(self.addin_status_path),
            "heartbeat_path": str(self.heartbeat_path),
            "addin_status": status,
            "heartbeat": heartbeat,
        }
        if not connected:
            result["note"] = "No add-in status or heartbeat payload is present yet."
            result["expected_contract"] = {
                "status": "started|stopped",
                "revit_version": "2025",
                "addin": {
                    "bridge_protocol_version": "string",
                    "supports_continuous_idling": True,
                    "uses_idling_set_raise_without_delay": True,
                    "assembly_path": "string",
                    "assembly_last_write_utc": "timestamp|null",
                    "session_id": "string",
                },
            }
        return result

    def verify_loaded_build(
        self,
        *,
        expected_protocol_version: str = EXPECTED_BRIDGE_PROTOCOL_VERSION,
        expected_source_capability_stamp: str = EXPECTED_SOURCE_CAPABILITY_STAMP,
    ) -> dict:
        status = self.bridge_status()
        addin = _loaded_addin_payload(status)
        checks = [
            _check_value(
                "bridge_connected",
                True,
                bool(status.get("available")),
                "Add-in status or heartbeat payload is present.",
            ),
            _check_value(
                "addin_metadata_present",
                True,
                bool(addin),
                "Loaded add-in exposes an addin metadata block.",
            ),
            _check_value(
                "bridge_protocol_version",
                expected_protocol_version,
                addin.get("bridge_protocol_version"),
                "Loaded add-in reports the expected bridge protocol version.",
            ),
            _check_value(
                "source_capability_stamp",
                expected_source_capability_stamp,
                addin.get("source_capability_stamp"),
                "Loaded add-in reports the expected source capability stamp.",
            ),
            _check_value(
                "supports_continuous_idling",
                True,
                addin.get("supports_continuous_idling"),
                "Loaded add-in reports continuous Idling support.",
            ),
            _check_value(
                "uses_idling_set_raise_without_delay",
                True,
                addin.get("uses_idling_set_raise_without_delay"),
                "Loaded add-in reports IdlingEventArgs.SetRaiseWithoutDelay usage.",
            ),
        ]
        missing = [check for check in checks if not check["passed"]]
        observed = {
            "addin": addin,
            "addin_status": status.get("addin_status"),
            "heartbeat": status.get("heartbeat"),
        }
        result = {
            "success": not missing,
            "read_only": True,
            "status": "current" if not missing else "stale_or_unverified",
            "expected": {
                "bridge_protocol_version": expected_protocol_version,
                "source_capability_stamp": expected_source_capability_stamp,
                "supports_continuous_idling": True,
                "uses_idling_set_raise_without_delay": True,
            },
            "observed": observed,
            "loaded_addin": addin,
            "checks": checks,
            "bridge_status": status,
            "recommendation": "loaded_build_verified" if not missing else (
                "Rebuild/sign/install the add-in if needed, then restart or reload Revit so "
                "the running session loads the current DLL before relying on continuous bridge polling."
            ),
        }
        return result

    def bridge_readiness(
        self,
        *,
        revit_version: str = "2025",
        addins_root: Path | None = None,
        assembly_path: Path | None = None,
    ) -> dict:
        addins_root = (addins_root or default_addins_root()).resolve()
        assembly_path = (assembly_path or default_assembly_path()).resolve()
        manifest_path = addins_root / revit_version / "HermesRevitOperator.addin"
        loaded = self.verify_loaded_build()
        manifest = _read_manifest_assembly(manifest_path)
        source_project = addin_source_dir() / "HermesRevitOperator.csproj"
        manifest_assembly = manifest.get("assembly_path")
        manifest_points_to_assembly = (
            bool(manifest_assembly)
            and _normalized_path_text(Path(str(manifest_assembly))) == _normalized_path_text(assembly_path)
        )
        checks = [
            _readiness_check(
                "source_project_present",
                source_project.exists(),
                f"Source project exists at {source_project}.",
                f"Source project is missing at {source_project}.",
            ),
            _readiness_check(
                "built_assembly_present",
                assembly_path.exists(),
                f"Built add-in assembly exists at {assembly_path}.",
                f"Built add-in assembly is missing at {assembly_path}.",
            ),
            _readiness_check(
                "manifest_present",
                manifest_path.exists(),
                f"Revit add-in manifest exists at {manifest_path}.",
                f"Revit add-in manifest is missing at {manifest_path}.",
            ),
            _readiness_check(
                "manifest_points_to_expected_assembly",
                manifest_points_to_assembly,
                "Manifest Assembly path points to the expected DLL.",
                "Manifest Assembly path is missing or points somewhere else.",
            ),
            _readiness_check(
                "bridge_connected",
                bool(loaded.get("bridge_status", {}).get("available")),
                "A loaded add-in status or heartbeat payload is present.",
                "No loaded add-in status or heartbeat payload is present.",
            ),
            _readiness_check(
                "loaded_build_current",
                bool(loaded.get("success")),
                "Loaded add-in reports the current bridge build metadata.",
                "Loaded add-in is stale or lacks current bridge build metadata.",
            ),
        ]
        passed_checks = [check["name"] for check in checks if check["passed"]]
        failed_checks = [check["name"] for check in checks if not check["passed"]]
        readiness_ok = all(check["passed"] for check in checks)
        next_steps = _bridge_readiness_next_steps(
            assembly_exists=assembly_path.exists(),
            manifest_exists=manifest_path.exists(),
            manifest_points_to_assembly=manifest_points_to_assembly,
            loaded_current=bool(loaded.get("success")),
        )
        return {
            "success": readiness_ok,
            "read_only": True,
            "status": "ready" if readiness_ok else "not_ready",
            "ready_for_continuous_bridge": readiness_ok,
            "requires_revit_restart_or_reload": (
                assembly_path.exists() and manifest_points_to_assembly and not bool(loaded.get("success"))
            ),
            "check_count": len(checks),
            "passed_check_count": len(passed_checks),
            "failed_check_count": len(failed_checks),
            "passed_checks": passed_checks,
            "failed_checks": failed_checks,
            "revit_version": revit_version,
            "paths": {
                "addins_root": str(addins_root),
                "manifest": str(manifest_path),
                "expected_assembly": str(assembly_path),
                "source_project": str(source_project),
            },
            "manifest": manifest,
            "assembly": _file_info(assembly_path),
            "loaded_build": loaded,
            "checks": checks,
            "next_steps": next_steps,
            "safety_note": (
                "This command is read-only. It does not close, restart, save, sync, reload, or modify Revit."
            ),
        }

    def active_document_status(self) -> dict:
        active_document_payload = self._read_json_file(self.active_document_path)
        if active_document_payload.get("available") is True:
            return {
                "available": True,
                "status": "connected",
                "document": active_document_payload["payload"],
                "bridge": self.bridge_status(),
            }
        if active_document_payload.get("status") != "missing":
            return {
                "available": False,
                "status": active_document_payload.get("status", "invalid_bridge_payload"),
                "error": active_document_payload.get("error"),
                "error_type": active_document_payload.get("error_type"),
                "bridge_path": str(self.active_document_path),
            }

        return {
            "available": False,
            "status": "stub",
            "bridge_path": str(self.active_document_path),
            "bridge": self.bridge_status(),
            "expected_contract": {
                "document_title": "string",
                "document_path": "string",
                "revit_version": "2025",
                "worksharing": "enabled|disabled|unknown",
                "central_path": "string|null",
                "dirty": "bool|null",
                "active_view": {"name": "string", "type": "string"},
            },
            "note": "No in-process Revit add-in bridge payload is present yet.",
        }

    def export_metadata(self, output_path: Path) -> dict:
        error = validate_output_path(output_path, self.sandbox)
        if error:
            return {"success": False, "error": error}

        output_path.parent.mkdir(parents=True, exist_ok=True)
        if self.metadata_snapshot_path.exists():
            shutil.copyfile(self.metadata_snapshot_path, output_path)
            return {
                "success": True,
                "source": str(self.metadata_snapshot_path),
                "path": str(output_path),
                "mode": "bridge_snapshot_copy",
                "read_only": True,
            }

        stub = {
            "label": DRAFT_LABEL,
            "generated_at": utc_now(),
            "mode": "stub_no_revit_addin_connected",
            "read_only": True,
            "test_model_hint": str(CURRENT_TEST_MODEL),
            "project_info": {},
            "levels": [],
            "grids": [],
            "views": [],
            "sheets": [],
            "titleblocks": [],
            "links": [],
            "warnings": [],
            "families": [],
            "types": [],
            "note": (
                "Install the future ExternalEvent-based Revit add-in to populate "
                "bridge/metadata_snapshot.json with live document metadata."
            ),
        }
        output_path.write_text(json.dumps(stub, indent=2, sort_keys=True), encoding="utf-8")
        return {
            "success": True,
            "path": str(output_path),
            "mode": "stub",
            "read_only": True,
        }

    def read_command_results(self) -> list[dict]:
        if not self.command_results_path.exists():
            return []
        text, error = self._read_text_file(self.command_results_path)
        if error is not None:
            if error.get("status") == "missing":
                return []
            return [{"success": False, **error}]
        results: list[dict] = []
        for line in text.splitlines():
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError as exc:
                payload = {"success": False, "error": str(exc), "raw": line}
            if isinstance(payload, dict):
                results.append(payload)
        return results

    def find_command_result(self, command_id: str) -> dict | None:
        for result in reversed(self.read_command_results()):
            if result.get("id") == command_id:
                return result
        return None

    def wait_for_command_result(
        self,
        command_id: str,
        *,
        timeout: float = 60.0,
        poll: float = 1.0,
    ) -> dict:
        deadline = time.monotonic() + max(0.0, timeout)
        checks = 0
        while True:
            checks += 1
            result = self.find_command_result(command_id)
            if result is not None:
                return {
                    "success": bool(result.get("success")),
                    "found": True,
                    "checks": checks,
                    "result": result,
                }
            if time.monotonic() >= deadline:
                return {
                    "success": False,
                    "found": False,
                    "checks": checks,
                    "error": f"Timed out waiting for bridge command result {command_id!r}.",
                    "command_results_path": str(self.command_results_path),
                }
            time.sleep(max(0.1, poll))

    @staticmethod
    def _read_json_file(path: Path) -> dict:
        if not path.exists():
            return {
                "available": False,
                "status": "missing",
                "path": str(path),
            }
        last_error: dict | None = None
        for attempt in range(8):
            text, error = RevitBridgeClient._read_text_file(path, attempts=1)
            if error is not None:
                last_error = error
            else:
                try:
                    data = json.loads(text)
                except json.JSONDecodeError as exc:
                    last_error = {
                        "available": False,
                        "status": "invalid_json",
                        "path": str(path),
                        "error": str(exc),
                        "error_type": type(exc).__name__,
                        "attempts": attempt + 1,
                    }
                else:
                    break
            if attempt < 7:
                time.sleep(min(0.4, 0.025 * (2**attempt)))
        else:
            return last_error or {
                "available": False,
                "status": "read_error",
                "path": str(path),
                "error": "Unknown bridge file read failure.",
            }
        if not isinstance(data, dict):
            return {
                "available": False,
                "status": "invalid_payload_type",
                "path": str(path),
                "payload_type": type(data).__name__,
            }
        return {
            "available": True,
            "status": "present",
            "path": str(path),
            "payload": data,
        }

    @staticmethod
    def _read_text_file(path: Path, *, attempts: int = 8) -> tuple[str, dict | None]:
        last_error: dict | None = None
        for attempt in range(max(1, attempts)):
            try:
                return path.read_text(encoding="utf-8"), None
            except FileNotFoundError:
                return "", {
                    "available": False,
                    "status": "missing",
                    "path": str(path),
                }
            except (OSError, UnicodeDecodeError) as exc:
                last_error = {
                    "available": False,
                    "status": "read_error",
                    "path": str(path),
                    "error": str(exc),
                    "error_type": type(exc).__name__,
                    "attempts": attempt + 1,
                }
                if attempt < attempts - 1:
                    time.sleep(min(0.4, 0.025 * (2**attempt)))
        return "", last_error


def _loaded_addin_payload(status: dict) -> dict:
    for outer_key in ("addin_status", "heartbeat"):
        outer = status.get(outer_key)
        if not isinstance(outer, dict):
            continue
        payload = outer.get("payload")
        if not isinstance(payload, dict):
            continue
        addin = payload.get("addin")
        if isinstance(addin, dict):
            return addin
    return {}


def _check_value(name: str, expected, actual, passed_reason: str) -> dict:
    passed = actual == expected
    return {
        "name": name,
        "expected": expected,
        "actual": actual,
        "passed": passed,
        "reason": passed_reason if passed else f"Expected {expected!r}, observed {actual!r}.",
    }


def _readiness_check(name: str, passed: bool, passed_reason: str, failed_reason: str) -> dict:
    return {
        "name": name,
        "passed": bool(passed),
        "reason": passed_reason if passed else failed_reason,
    }


def _read_manifest_assembly(path: Path) -> dict:
    if not path.exists():
        return {
            "available": False,
            "status": "missing",
            "path": str(path),
            "assembly_path": None,
        }
    try:
        root = ET.fromstring(path.read_text(encoding="utf-8"))
    except ET.ParseError as exc:
        return {
            "available": False,
            "status": "invalid_xml",
            "path": str(path),
            "assembly_path": None,
            "error": str(exc),
        }
    assembly = root.find(".//Assembly")
    assembly_text = assembly.text.strip() if assembly is not None and assembly.text else ""
    return {
        "available": True,
        "status": "present",
        "path": str(path),
        "assembly_path": assembly_text or None,
    }


def _file_info(path: Path) -> dict:
    if not path.exists():
        return {
            "available": False,
            "path": str(path),
        }
    stat = path.stat()
    return {
        "available": True,
        "path": str(path),
        "last_write_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(stat.st_mtime)),
        "length": stat.st_size,
    }


def _normalized_path_text(path: Path) -> str:
    try:
        return str(path.resolve()).casefold()
    except OSError:
        return str(path).casefold()


def _bridge_readiness_next_steps(
    *,
    assembly_exists: bool,
    manifest_exists: bool,
    manifest_points_to_assembly: bool,
    loaded_current: bool,
) -> list[str]:
    steps: list[str] = []
    if not assembly_exists:
        steps.append(
            "Build tools/revit_operator/addin/HermesRevitOperator.csproj for Revit 2025 before installing."
        )
    if not manifest_exists:
        steps.append("Run install-addin with explicit approval so Revit can find the DLL on next startup.")
    elif not manifest_points_to_assembly:
        steps.append("Reinstall the add-in manifest so its Assembly path points to the expected DLL.")
    if assembly_exists and manifest_points_to_assembly and not loaded_current:
        steps.append(
            "Ask the human to restart or reload Revit when safe; do not save, sync, close, or restart through Hermes."
        )
    if loaded_current:
        steps.append("Loaded bridge build is current; continuous bridge polling can be trusted for this session.")
    return steps
