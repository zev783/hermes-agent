"""Revit operator add-in and bridge: versions, install and trust, status, restart validation."""

import json
import os
from pathlib import Path

import pytest

from tools.revit_operator import cli
import tools.revit_operator.addin_installer as addin_installer
from tools.revit_operator.addin_installer import addin_manifest_text
from tools.revit_operator.addin_security import addin_security_preflight
import tools.revit_operator.bridge as bridge_module
from tools.revit_operator.bridge import RevitBridgeClient
from tools.revit_operator.bridge_validation import bridge_post_restart_validation, bridge_restart_validation_plan
from tools.revit_operator.journal import TaskJournal
import tools.revit_operator.revit_locator as revit_locator
from tools.revit_operator.revit_locator import infer_revit_version_from_model
from tools.revit_operator.safety import APPROVAL_REQUIRED
from tools.revit_operator.version_support import (
    REVIT_TARGET_FRAMEWORK_BY_VERSION,
    SUPPORTED_REVIT_VERSIONS,
    assembly_subdir_for_revit_version,
    version_support_matrix,
)


def test_revit_addin_bridge_writes_are_retrying_and_reader_tolerant():
    source = (
        Path(__file__).resolve().parents[2]
        / "tools"
        / "revit_operator"
        / "addin"
        / "HermesRevitOperatorApp.cs"
    ).read_text(encoding="utf-8")

    assert "RetryFileOperation" in source
    assert "FileShare.ReadWrite | FileShare.Delete" in source
    assert "AppendLineWithRetry(CommandResultsPath" in source
    # File.Replace left "<name>~RF<hex>.TMP" backups whenever another process held the target, and
    # per-write GUID temp names piled up whenever a write failed.
    assert "File.Replace(" not in source
    assert 'path + "." + ProcessId + ".tmp"' in source


def test_revit_addin_process_file_names_match_bridge_client():
    source = (
        Path(__file__).resolve().parents[2]
        / "tools"
        / "revit_operator"
        / "addin"
        / "HermesRevitOperatorApp.cs"
    ).read_text(encoding="utf-8")
    stems_block = source.split("ProcessFileStems =", 1)[1].split("{", 1)[1].split("}", 1)[0]
    stems = [stem.strip().strip('"') for stem in stems_block.split(",")]

    bridge = RevitBridgeClient(Path("sandbox"))
    paths = [*bridge.process_status_paths(42).values(), bridge.process_metadata_snapshot_path(42)]

    assert sorted(path.name for path in paths) == sorted(f"{stem}.42.json" for stem in stems)
    assert 'Path.GetFileNameWithoutExtension(sharedPath) + "." + ProcessId + ".json"' in source
    # The sweep deletes these per-process files once their process has exited.
    assert "foreach (var stem in ProcessFileStems)" in source
    # The client compares these to reject files that an earlier process with a reused PID left behind.
    assert '["process_id"] = ProcessId' in source
    assert '["process_start_utc"] = ProcessStartUtc' in source


def test_revit_addin_metadata_export_writes_process_snapshot_first_and_reports_it():
    source = (
        Path(__file__).resolve().parents[2]
        / "tools"
        / "revit_operator"
        / "addin"
        / "HermesRevitOperatorApp.cs"
    ).read_text(encoding="utf-8")
    write_metadata = source.split("private Dictionary<string, object?> WriteMetadata(", 1)[1]
    write_metadata = write_metadata.split("\n    private ", 1)[0]

    assert "return WriteMetadata(uiapp);" in source
    # The client reads the writer's process_id and process_start_utc from the snapshot's addin block.
    assert '["addin"] = AddinInfo()' in write_metadata
    assert write_metadata.index("WriteTextAtomic(processPath, json)") < write_metadata.index(
        "WriteTextAtomic(MetadataPath, json)"
    )
    assert "var processPath = ProcessFilePath(MetadataPath);" in write_metadata
    assert 'Success("Metadata snapshot written.", processPath)' in write_metadata
    assert 'result["shared_path"] = MetadataPath;' in write_metadata


def test_r25_filename_infers_revit_2025():
    assert infer_revit_version_from_model(Path("Example-Structural_Current-R25-BIM.rvt")) == "2025"


@pytest.mark.parametrize(
    ("marker", "version"),
    [("R22", "2022"), ("R23", "2023"), ("R24", "2024"), ("R25", "2025"), ("R26", "2026"), ("R27", "2027")],
)
def test_revit_filename_markers_infer_supported_versions(marker, version):
    assert infer_revit_version_from_model(Path(f"Example-Structural_Current-{marker}-BIM.rvt")) == version


def test_resolve_revit_exe_specific_version_does_not_fallback(monkeypatch, tmp_path):
    latest_exe = tmp_path / "Revit 2027" / "Revit.exe"
    latest_exe.parent.mkdir(parents=True)
    latest_exe.write_text("fake exe", encoding="utf-8")

    monkeypatch.setattr(revit_locator, "default_revit_install_dir", lambda version: tmp_path / f"Revit {version}")
    monkeypatch.setattr(revit_locator, "installed_revit_versions", lambda root=revit_locator.DEFAULT_AUTODESK_ROOT: {"2027": str(latest_exe)})

    assert revit_locator.resolve_revit_exe("2026") is None
    assert revit_locator.resolve_revit_exe(None) == latest_exe


def test_revit_version_support_matrix_covers_2022_to_2027():
    matrix = version_support_matrix({"2025": r"C:\Program Files\Autodesk\Revit 2025\Revit.exe"})

    assert matrix["supported_versions"] == ["2022", "2023", "2024", "2025", "2026", "2027"]
    assert matrix["min_version"] == "2022"
    assert matrix["max_version"] == "2027"
    assert matrix["version_count"] == 6
    assert matrix["target_frameworks"] == {
        "2022": "net48",
        "2023": "net48",
        "2024": "net48",
        "2025": "net8.0-windows",
        "2026": "net8.0-windows",
        "2027": "net10.0-windows",
    }
    assert next(row for row in matrix["rows"] if row["revit_version"] == "2025")["installed"] is True


def test_revit_addin_project_declares_all_supported_version_targets():
    project = (
        Path(__file__).resolve().parents[2]
        / "tools"
        / "revit_operator"
        / "addin"
        / "HermesRevitOperator.csproj"
    ).read_text(encoding="utf-8")
    source = (
        Path(__file__).resolve().parents[2]
        / "tools"
        / "revit_operator"
        / "addin"
        / "HermesRevitOperatorApp.cs"
    ).read_text(encoding="utf-8")

    assert "REVIT$(RevitVersion)" in project
    for version in SUPPORTED_REVIT_VERSIONS:
        assert version in project
        assert f"REVIT{version}" in source
    for framework in set(REVIT_TARGET_FRAMEWORK_BY_VERSION.values()):
        assert framework in project
    assert "System.Text.Json" in project
    assert "ElementIdValue(ElementId id)" in source
    assert "IntegerValue" in source
    assert "supported_revit_versions" in source


def test_cli_version_support_reports_all_supported_versions(tmp_path, capsys):
    code = cli.main(
        [
            "--sandbox",
            str(tmp_path),
            "--allow-sandbox-outside-safe-root",
            "--task-id",
            "version-support-cli-test",
            "version-support",
        ]
    )

    assert code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["success"] is True
    assert output["read_only"] is True
    assert output["support"]["supported_versions"] == list(SUPPORTED_REVIT_VERSIONS)
    assert output["support"]["target_frameworks"]["2027"] == "net10.0-windows"


def test_install_addin_dry_run_reports_build_prerequisite(tmp_path, capsys):
    code = cli.main(
        [
            "--sandbox",
            str(tmp_path / "sandbox"),
            "--allow-sandbox-outside-safe-root",
            "--task-id",
            "addin-test",
            "install-addin",
            "--addins-root",
            str(tmp_path / "Addins"),
        ]
    )

    assert code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["success"] is True
    assert output["dry_run"] is True
    assert output["source_project"].endswith("HermesRevitOperator.csproj")
    assert "NET SDK" in output["build_prerequisite"]


@pytest.mark.parametrize("version", SUPPORTED_REVIT_VERSIONS)
def test_install_addin_dry_run_supports_revit_2022_to_2027(tmp_path, capsys, version):
    code = cli.main(
        [
            "--sandbox",
            str(tmp_path / "sandbox"),
            "--allow-sandbox-outside-safe-root",
            "--task-id",
            f"addin-test-{version}",
            "install-addin",
            "--revit-version",
            version,
            "--addins-root",
            str(tmp_path / "Addins"),
        ]
    )

    assert code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["success"] is True
    assert output["dry_run"] is True
    assert output["target_framework"] == REVIT_TARGET_FRAMEWORK_BY_VERSION[version]
    assert f"Addins\\{version}\\HermesRevitOperator.addin" in output["target_manifest"]
    assert str(assembly_subdir_for_revit_version(version)) in output["assembly_path"]


def test_install_addin_rejects_unsupported_revit_version(tmp_path, capsys):
    code = cli.main(
        [
            "--sandbox",
            str(tmp_path / "sandbox"),
            "--allow-sandbox-outside-safe-root",
            "--task-id",
            "addin-unsupported-version-test",
            "install-addin",
            "--revit-version",
            "2021",
            "--addins-root",
            str(tmp_path / "Addins"),
        ]
    )

    assert code == 2
    output = json.loads(capsys.readouterr().out)
    assert output["success"] is False
    assert "Unsupported Revit version" in output["error"]


def test_default_assembly_path_prefers_newest_local_hermes_build(tmp_path, monkeypatch):
    monkeypatch.setattr(addin_installer, "addin_source_dir", lambda: tmp_path)
    legacy = tmp_path / "bin" / "Release" / "net8.0-windows" / "HermesRevitOperator.dll"
    current = (
        tmp_path
        / "bin"
        / "Release"
        / "net8.0-windows-current"
        / "HermesRevitOperator.dll"
    )
    legacy.parent.mkdir(parents=True)
    current.parent.mkdir(parents=True)
    legacy.write_bytes(b"legacy")
    current.write_bytes(b"current")
    os.utime(legacy, (1_770_000_000, 1_770_000_000))
    os.utime(current, (1_770_000_100, 1_770_000_100))

    assert addin_installer.default_assembly_path() == current
    assert addin_installer.is_default_local_assembly_path(current) is True
    assert addin_installer.is_default_local_assembly_path(tmp_path / "other.dll") is False


def test_default_assembly_path_prefers_version_specific_build(tmp_path, monkeypatch):
    monkeypatch.setattr(addin_installer, "addin_source_dir", lambda: tmp_path)
    versioned = tmp_path / assembly_subdir_for_revit_version("2024") / "HermesRevitOperator.dll"
    legacy = tmp_path / "bin" / "Release" / "net8.0-windows-current" / "HermesRevitOperator.dll"
    versioned.parent.mkdir(parents=True)
    legacy.parent.mkdir(parents=True)
    versioned.write_bytes(b"versioned")
    legacy.write_bytes(b"legacy")
    os.utime(versioned, (1_770_000_000, 1_770_000_000))
    os.utime(legacy, (1_770_000_100, 1_770_000_100))

    assert addin_installer.default_assembly_path("2024") == versioned
    assert versioned in addin_installer.default_assembly_candidates("2024")
    assert addin_installer.is_default_local_assembly_path(versioned, "2024") is True


def test_trust_addin_dry_run_reports_cert_store_impact(tmp_path, capsys):
    dll = tmp_path / "HermesRevitOperator.dll"
    dll.write_bytes(b"not a real dll")

    code = cli.main(
        [
            "--sandbox",
            str(tmp_path / "sandbox"),
            "--allow-sandbox-outside-safe-root",
            "--task-id",
            "trust-test",
            "trust-addin",
            "--assembly",
            str(dll),
        ]
    )

    assert code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["success"] is True
    assert output["dry_run"] is True
    assert output["policy"]["decision"] == APPROVAL_REQUIRED
    assert "TrustedPublisher" in output["impact"]


def test_addin_security_preflight_verifies_expected_manifest_before_load(tmp_path):
    addins_root = tmp_path / "Addins"
    assembly = tmp_path / "build" / "HermesRevitOperator.dll"
    assembly.parent.mkdir()
    assembly.write_bytes(b"test dll")
    manifest = addins_root / "2025" / "HermesRevitOperator.addin"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(addin_manifest_text(assembly), encoding="utf-8")

    result = addin_security_preflight(
        TaskJournal(tmp_path / "sandbox", "addin-security-test"),
        revit_version="2025",
        addins_root=addins_root,
        assembly_path=assembly,
        signature_probe=lambda path: {
            "available": True,
            "path": str(path),
            "status": "NotSigned",
            "status_message": "The file is not signed.",
            "signer_subject": None,
            "signer_thumbprint": None,
        },
    )

    assert result["success"] is True
    assert result["read_only"] is True
    assert result["policy"]["decision"] == "allow"
    assert result["expected_local_hermes_addin"] is True
    assert result["needs_trust_addin"] is True
    assert result["can_consider_always_load_after_human_approval"] is True
    assert result["allowed_dialog_button"] == "Always Load"
    assert "trust-addin" in result["recommended_action"]


@pytest.mark.parametrize("version", SUPPORTED_REVIT_VERSIONS)
def test_addin_security_preflight_accepts_supported_revit_versions(tmp_path, version):
    addins_root = tmp_path / "Addins"
    assembly = tmp_path / assembly_subdir_for_revit_version(version) / "HermesRevitOperator.dll"
    assembly.parent.mkdir(parents=True)
    assembly.write_bytes(b"test dll")
    manifest = addins_root / version / "HermesRevitOperator.addin"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(addin_manifest_text(assembly), encoding="utf-8")

    result = addin_security_preflight(
        TaskJournal(tmp_path / "sandbox", f"addin-security-test-{version}"),
        revit_version=version,
        addins_root=addins_root,
        assembly_path=assembly,
        signature_probe=lambda path: {
            "available": True,
            "path": str(path),
            "status": "NotSigned",
            "status_message": "The file is not signed.",
            "signer_subject": None,
            "signer_thumbprint": None,
        },
    )

    checks = {check["name"]: check["passed"] for check in result["checks"]}
    assert checks["revit_version_supported"] is True
    assert result["revit_version"] == version
    assert result["target_framework"] == REVIT_TARGET_FRAMEWORK_BY_VERSION[version]
    assert result["expected_local_hermes_addin"] is True


def test_addin_source_reports_loaded_build_and_continuous_idling_capabilities():
    repo_root = Path(__file__).resolve().parents[2]
    source = (
        repo_root
        / "tools"
        / "revit_operator"
        / "addin"
        / "HermesRevitOperatorApp.cs"
    ).read_text(encoding="utf-8")

    for marker in [
        "SetRaiseWithoutDelay()",
        "bridge_protocol_version",
        "source_capability_stamp",
        "supports_continuous_idling",
        "uses_idling_set_raise_without_delay",
        "assembly_last_write_utc",
    ]:
        assert marker in source


def test_bridge_wait_for_command_result_reads_jsonl(tmp_path):
    bridge = RevitBridgeClient(tmp_path)
    bridge.bridge_dir.mkdir()
    bridge.command_results_path.write_text(
        json.dumps({"id": "cmd-1", "success": True, "message": "ok"}) + "\n",
        encoding="utf-8",
    )

    result = bridge.wait_for_command_result("cmd-1", timeout=0, poll=0.1)

    assert result["success"] is True
    assert result["found"] is True
    assert result["result"]["message"] == "ok"


def test_bridge_status_reads_addin_build_metadata(tmp_path):
    bridge = RevitBridgeClient(tmp_path)
    bridge.bridge_dir.mkdir()
    bridge.addin_status_path.write_text(
        json.dumps(
            {
                "status": "started",
                "revit_version": "2025",
                "addin": {
                    "bridge_protocol_version": "0.2",
                    "supports_continuous_idling": True,
                    "uses_idling_set_raise_without_delay": True,
                    "assembly_path": "C:/temp/HermesRevitOperator.dll",
                    "assembly_last_write_utc": "2026-05-12T00:00:00Z",
                    "session_id": "abc",
                },
            }
        ),
        encoding="utf-8",
    )
    bridge.heartbeat_path.write_text(
        json.dumps({"status": "idling", "addin": {"session_id": "abc"}}),
        encoding="utf-8",
    )

    result = bridge.bridge_status()

    assert result["available"] is True
    assert result["status"] == "connected"
    addin = result["addin_status"]["payload"]["addin"]
    assert addin["supports_continuous_idling"] is True
    assert addin["uses_idling_set_raise_without_delay"] is True
    assert addin["assembly_last_write_utc"] == "2026-05-12T00:00:00Z"


def test_bridge_status_retries_temporarily_locked_json_payload(tmp_path, monkeypatch):
    bridge = RevitBridgeClient(tmp_path)
    bridge.bridge_dir.mkdir()
    bridge.addin_status_path.write_text(
        json.dumps({"status": "started", "addin": {"source_capability_stamp": "current"}}),
        encoding="utf-8",
    )
    bridge.heartbeat_path.write_text(
        json.dumps({"status": "idling", "addin": {"session_id": "abc"}}),
        encoding="utf-8",
    )
    original_read_text = Path.read_text
    calls = {"heartbeat": 0}

    def flaky_read_text(path, *args, **kwargs):
        if Path(path) == bridge.heartbeat_path and calls["heartbeat"] < 2:
            calls["heartbeat"] += 1
            raise PermissionError("simulated writer lock")
        return original_read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", flaky_read_text)

    result = bridge.bridge_status()

    assert calls["heartbeat"] == 2
    assert result["available"] is True
    assert result["heartbeat"]["available"] is True
    assert result["heartbeat"]["payload"]["addin"]["session_id"] == "abc"


def test_verify_bridge_build_passes_for_expected_metadata(tmp_path):
    bridge = RevitBridgeClient(tmp_path)
    bridge.bridge_dir.mkdir()
    bridge.addin_status_path.write_text(
        json.dumps(
            {
                "status": "started",
                "revit_version": "2025",
                "addin": {
                    "bridge_protocol_version": "0.2",
                    "source_capability_stamp": "continuous-idling-status-file-retry-v2",
                    "supports_continuous_idling": True,
                    "uses_idling_set_raise_without_delay": True,
                    "assembly_path": "C:/temp/HermesRevitOperator.dll",
                    "assembly_last_write_utc": "2026-05-12T00:00:00Z",
                    "session_id": "abc",
                },
            }
        ),
        encoding="utf-8",
    )

    result = bridge.verify_loaded_build()

    assert result["success"] is True
    assert result["read_only"] is True
    assert result["status"] == "current"
    assert result["recommendation"] == "loaded_build_verified"
    assert all(check["passed"] for check in result["checks"])


def test_verify_bridge_build_flags_stale_loaded_payload(tmp_path):
    bridge = RevitBridgeClient(tmp_path)
    bridge.bridge_dir.mkdir()
    bridge.addin_status_path.write_text(
        json.dumps(
            {
                "status": "started",
                "revit_version": "2025",
                "addin": {
                    "session_id": "old-session",
                },
            }
        ),
        encoding="utf-8",
    )

    result = bridge.verify_loaded_build()

    assert result["success"] is False
    assert result["read_only"] is True
    assert result["status"] == "stale_or_unverified"
    assert "restart or reload Revit" in result["recommendation"]
    failed = {check["name"] for check in result["checks"] if not check["passed"]}
    assert "bridge_protocol_version" in failed
    assert "source_capability_stamp" in failed
    assert "supports_continuous_idling" in failed


def test_bridge_readiness_requires_restart_when_installed_but_loaded_stale(tmp_path):
    bridge = RevitBridgeClient(tmp_path)
    bridge.bridge_dir.mkdir()
    bridge.addin_status_path.write_text(
        json.dumps(
            {
                "status": "started",
                "revit_version": "2025",
                "addin": {"session_id": "old-session"},
            }
        ),
        encoding="utf-8",
    )
    assembly = tmp_path / "HermesRevitOperator.dll"
    assembly.write_bytes(b"fake-dll")
    addins_root = tmp_path / "Addins"
    manifest = addins_root / "2025" / "HermesRevitOperator.addin"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(addin_manifest_text(assembly), encoding="utf-8")

    result = bridge.bridge_readiness(
        revit_version="2025",
        addins_root=addins_root,
        assembly_path=assembly,
    )

    assert result["success"] is False
    assert result["read_only"] is True
    assert result["status"] == "not_ready"
    assert result["ready_for_continuous_bridge"] is False
    assert result["requires_revit_restart_or_reload"] is True
    checks = {check["name"]: check["passed"] for check in result["checks"]}
    assert checks["built_assembly_present"] is True
    assert checks["manifest_present"] is True
    assert checks["manifest_points_to_expected_assembly"] is True
    assert checks["loaded_build_current"] is False
    assert result["check_count"] == len(result["checks"])
    assert result["failed_check_count"] == 1
    assert result["failed_checks"] == ["loaded_build_current"]
    assert "loaded_build_current" not in result["passed_checks"]
    assert any("restart or reload Revit" in step for step in result["next_steps"])


@pytest.mark.parametrize("version", SUPPORTED_REVIT_VERSIONS)
def test_bridge_readiness_uses_revit_version_specific_manifest_and_framework(tmp_path, version):
    bridge = RevitBridgeClient(tmp_path)
    assembly = tmp_path / assembly_subdir_for_revit_version(version) / "HermesRevitOperator.dll"
    assembly.parent.mkdir(parents=True)
    assembly.write_bytes(b"fake-dll")
    addins_root = tmp_path / "Addins"
    manifest = addins_root / version / "HermesRevitOperator.addin"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(addin_manifest_text(assembly), encoding="utf-8")

    result = bridge.bridge_readiness(
        revit_version=version,
        addins_root=addins_root,
        assembly_path=assembly,
    )

    checks = {check["name"]: check["passed"] for check in result["checks"]}
    assert checks["revit_version_supported"] is True
    assert result["revit_version"] == version
    assert result["target_framework"] == REVIT_TARGET_FRAMEWORK_BY_VERSION[version]
    assert result["paths"]["manifest"].endswith(f"Addins\\{version}\\HermesRevitOperator.addin")
    assert result["supported_revit_versions"] == list(SUPPORTED_REVIT_VERSIONS)


def test_bridge_readiness_rejects_unsupported_revit_version(tmp_path):
    bridge = RevitBridgeClient(tmp_path)

    result = bridge.bridge_readiness(revit_version="2021", addins_root=tmp_path / "Addins")

    assert result["success"] is False
    assert result["target_framework"] is None
    checks = {check["name"]: check for check in result["checks"]}
    assert checks["revit_version_supported"]["passed"] is False
    assert "Unsupported Revit version" in checks["revit_version_supported"]["reason"]


def test_bridge_readiness_default_accepts_current_unlocked_build_path(tmp_path, monkeypatch):
    bridge = RevitBridgeClient(tmp_path)
    bridge.bridge_dir.mkdir()
    bridge.addin_status_path.write_text(
        json.dumps(
            {
                "status": "started",
                "revit_version": "2025",
                "addin": {"session_id": "old-session"},
            }
        ),
        encoding="utf-8",
    )
    assembly = (
        tmp_path
        / "source"
        / "bin"
        / "Release"
        / "net8.0-windows-current"
        / "HermesRevitOperator.dll"
    )
    assembly.parent.mkdir(parents=True)
    assembly.write_bytes(b"fake-dll")
    addins_root = tmp_path / "Addins"
    manifest = addins_root / "2025" / "HermesRevitOperator.addin"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(addin_manifest_text(assembly), encoding="utf-8")
    monkeypatch.setattr(bridge_module, "default_assembly_path", lambda *_args: assembly)

    result = bridge.bridge_readiness(
        revit_version="2025",
        addins_root=addins_root,
    )

    checks = {check["name"]: check["passed"] for check in result["checks"]}
    assert checks["manifest_points_to_expected_assembly"] is True
    assert checks["built_assembly_present"] is True
    assert result["failed_checks"] == ["loaded_build_current"]
    assert result["requires_revit_restart_or_reload"] is True


def test_bridge_readiness_passes_when_installed_and_loaded_current(tmp_path):
    bridge = RevitBridgeClient(tmp_path)
    bridge.bridge_dir.mkdir()
    bridge.addin_status_path.write_text(
        json.dumps(
            {
                "status": "started",
                "revit_version": "2025",
                "addin": {
                    "bridge_protocol_version": "0.2",
                    "source_capability_stamp": "continuous-idling-status-file-retry-v2",
                    "supports_continuous_idling": True,
                    "uses_idling_set_raise_without_delay": True,
                    "session_id": "current-session",
                },
            }
        ),
        encoding="utf-8",
    )
    assembly = tmp_path / "HermesRevitOperator.dll"
    assembly.write_bytes(b"fake-dll")
    addins_root = tmp_path / "Addins"
    manifest = addins_root / "2025" / "HermesRevitOperator.addin"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(addin_manifest_text(assembly), encoding="utf-8")

    result = bridge.bridge_readiness(
        revit_version="2025",
        addins_root=addins_root,
        assembly_path=assembly,
    )

    assert result["success"] is True
    assert result["status"] == "ready"
    assert result["ready_for_continuous_bridge"] is True
    assert result["requires_revit_restart_or_reload"] is False
    assert all(check["passed"] for check in result["checks"])
    assert result["failed_check_count"] == 0
    assert result["failed_checks"] == []
    assert set(result["passed_checks"]) == {check["name"] for check in result["checks"]}


def test_cli_bridge_readiness_reports_restart_gate(tmp_path, capsys):
    bridge_dir = tmp_path / "bridge"
    bridge_dir.mkdir()
    (bridge_dir / "addin_status.json").write_text(
        json.dumps(
            {
                "status": "started",
                "revit_version": "2025",
                "addin": {"session_id": "old-session"},
            }
        ),
        encoding="utf-8",
    )
    assembly = tmp_path / "HermesRevitOperator.dll"
    assembly.write_bytes(b"fake-dll")
    addins_root = tmp_path / "Addins"
    manifest = addins_root / "2025" / "HermesRevitOperator.addin"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(addin_manifest_text(assembly), encoding="utf-8")

    code = cli.main(
        [
            "--sandbox",
            str(tmp_path),
            "--allow-sandbox-outside-safe-root",
            "--task-id",
            "bridge-readiness-test",
            "bridge-readiness",
            "--addins-root",
            str(addins_root),
            "--assembly",
            str(assembly),
        ]
    )

    assert code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["success"] is False
    assert output["read_only"] is True
    assert output["requires_revit_restart_or_reload"] is True
    assert output["failed_checks"] == ["loaded_build_current"]


def test_bridge_restart_validation_plan_requires_human_for_stale_loaded_bridge(tmp_path):
    bridge = RevitBridgeClient(tmp_path)
    bridge.bridge_dir.mkdir()
    bridge.addin_status_path.write_text(
        json.dumps(
            {
                "status": "started",
                "revit_version": "2025",
                "addin": {"session_id": "old-session"},
            }
        ),
        encoding="utf-8",
    )
    assembly = tmp_path / "HermesRevitOperator.dll"
    assembly.write_bytes(b"fake-dll")
    addins_root = tmp_path / "Addins"
    manifest = addins_root / "2025" / "HermesRevitOperator.addin"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(addin_manifest_text(assembly), encoding="utf-8")
    bridge.active_document_path.write_text(
        json.dumps(
            {
                "title": "24522 detached",
                "path": "24522 detached.rvt",
                "revit_version": "2025",
                "dirty": True,
                "active_view": {"name": "STARTING VIEW", "type": "DrawingSheet"},
            }
        ),
        encoding="utf-8",
    )

    def security_stub(*_args, **_kwargs):
        return {
            "status": "verified",
            "expected_local_hermes_addin": True,
            "needs_trust_addin": False,
            "can_consider_always_load_after_human_approval": True,
            "allowed_dialog_button": "Always Load",
            "blocked_dialog_buttons": ["Load Once", "Do Not Load"],
            "paths": {
                "manifest": str(manifest),
                "expected_assembly": str(assembly),
            },
            "signature": {
                "status": "Valid",
                "signer_subject": "CN=Hermes Revit Operator Local Code Signing",
            },
            "recommended_action": "Click Always Load only with exact human approval.",
        }

    result = bridge_restart_validation_plan(
        TaskJournal(tmp_path, "bridge-restart-validation-plan-test"),
        bridge,
        revit_version="2025",
        addins_root=addins_root,
        assembly_path=assembly,
        expected_title_contains="24522",
        expected_view_name="STARTING VIEW",
        expected_view_type="DrawingSheet",
        security_preflight_fn=security_stub,
    )

    assert result["success"] is True
    assert result["read_only"] is True
    assert result["status"] == "human_restart_required"
    assert result["pre_restart_files_ready"] is True
    assert result["restart_or_reload_required"] is True
    assert result["human_handoff_required"] is True
    assert any("must not close or restart Revit" in item for item in result["blocked_automation"])
    assert any("verify-bridge-build" in command for command in result["post_restart_validation_commands"])
    assert any("wait-model-ready" in command for command in result["post_restart_validation_commands"])
    assert Path(result["path"]).exists()
    checklist = Path(result["no_save_checklist_path"])
    assert checklist.exists()
    checklist_text = checklist.read_text(encoding="utf-8")
    assert "dirty: `True`" in checklist_text
    assert "Save/discard decisions are human-only" in checklist_text
    assert "Hermes must not answer" in checklist_text
    assert "Bridge Reload Cause" in checklist_text
    assert "Loaded Revit add-in is stale or lacks current bridge build metadata" in checklist_text
    assert "failed_readiness_checks: `loaded_build_current`" in checklist_text
    assert "bridge_protocol_version=`0.2`" in checklist_text
    assert "source_capability_stamp=`continuous-idling-status-file-retry-v2`" in checklist_text
    assert "supports_continuous_idling=`True`" in checklist_text
    assert "uses_idling_set_raise_without_delay=`True`" in checklist_text
    assert result["addin_security_preflight"]["status"] == "verified"
    assert "Add-In Startup Prompt Preflight" in checklist_text
    assert "addin_security_status: `verified`" in checklist_text
    assert "allowed_dialog_button_after_human_approval: `Always Load`" in checklist_text
    assert "blocked_dialog_buttons: `Load Once`, `Do Not Load`" in checklist_text
    assert "signature_status: `Valid`" in checklist_text
    assert "Hermes must not click it from this checklist" in checklist_text
    assert "`north-star-completion-gate`" in checklist_text
    assert "`north-star-resume-check.completion_gate`" in checklist_text
    assert "`completion_allowed: true`" in checklist_text
    assert "`may_call_update_goal: true`" in checklist_text
    assert "`audit_completion_authorized: true`" in checklist_text
    assert "Status and audit summaries are diagnostic only." in checklist_text
    assert "fresh status or audit artifact reports" not in checklist_text
    assert result["active_document"]["document"]["dirty"] is True


def test_bridge_restart_validation_plan_checklist_handles_nested_document_status(tmp_path):
    bridge = RevitBridgeClient(tmp_path)
    bridge.bridge_dir.mkdir()
    bridge.addin_status_path.write_text(
        json.dumps(
            {
                "status": "started",
                "revit_version": "2025",
                "addin": {"session_id": "old-session"},
            }
        ),
        encoding="utf-8",
    )
    assembly = tmp_path / "HermesRevitOperator.dll"
    assembly.write_bytes(b"fake-dll")
    addins_root = tmp_path / "Addins"
    manifest = addins_root / "2025" / "HermesRevitOperator.addin"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(addin_manifest_text(assembly), encoding="utf-8")
    bridge.active_document_path.write_text(
        json.dumps(
            {
                "available": True,
                "status": "connected",
                "document": {
                    "title": "24522 nested detached",
                    "path": "24522 nested detached.rvt",
                    "revit_version": "2025",
                    "dirty": True,
                    "active_view": {"name": "STARTING VIEW", "type": "DrawingSheet"},
                },
            }
        ),
        encoding="utf-8",
    )

    def security_stub(*_args, **_kwargs):
        return {
            "status": "needs_attention",
            "expected_local_hermes_addin": True,
            "needs_trust_addin": True,
            "can_consider_always_load_after_human_approval": True,
            "allowed_dialog_button": "Always Load",
            "blocked_dialog_buttons": ["Load Once", "Do Not Load"],
            "paths": {
                "manifest": str(manifest),
                "expected_assembly": str(assembly),
            },
            "signature": {"status": "NotSigned", "signer_subject": None},
            "recommended_action": "Sign/trust the local add-in before restarting.",
        }

    result = bridge_restart_validation_plan(
        TaskJournal(tmp_path, "bridge-restart-validation-plan-nested-doc-test"),
        bridge,
        revit_version="2025",
        addins_root=addins_root,
        assembly_path=assembly,
        expected_title_contains="24522",
        expected_view_name="STARTING VIEW",
        expected_view_type="DrawingSheet",
        security_preflight_fn=security_stub,
    )

    checklist_text = Path(result["no_save_checklist_path"]).read_text(encoding="utf-8")
    assert "title: `24522 nested detached`" in checklist_text
    assert "path: `24522 nested detached.rvt`" in checklist_text
    assert "active_view: `STARTING VIEW`" in checklist_text
    assert "dirty: `True`" in checklist_text
    assert "Save/discard decisions are human-only" in checklist_text
    assert "failed_readiness_checks: `loaded_build_current`" in checklist_text
    assert "addin_security_status: `needs_attention`" in checklist_text
    assert "needs_trust_addin: `True`" in checklist_text


def test_cli_bridge_restart_validation_plan_writes_readonly_artifact(tmp_path, capsys):
    bridge_dir = tmp_path / "bridge"
    bridge_dir.mkdir()
    (bridge_dir / "addin_status.json").write_text(
        json.dumps(
            {
                "status": "started",
                "revit_version": "2025",
                "addin": {"session_id": "old-session"},
            }
        ),
        encoding="utf-8",
    )
    assembly = tmp_path / "HermesRevitOperator.dll"
    assembly.write_bytes(b"fake-dll")
    addins_root = tmp_path / "Addins"
    manifest = addins_root / "2025" / "HermesRevitOperator.addin"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(addin_manifest_text(assembly), encoding="utf-8")

    code = cli.main(
        [
            "--sandbox",
            str(tmp_path),
            "--allow-sandbox-outside-safe-root",
            "--task-id",
            "bridge-restart-validation-plan-cli-test",
            "bridge-restart-validation-plan",
            "--addins-root",
            str(addins_root),
            "--assembly",
            str(assembly),
            "--expected-title-contains",
            "24522",
        ]
    )

    assert code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["success"] is True
    assert output["read_only"] is True
    assert output["status"] == "human_restart_required"
    assert output["restart_or_reload_required"] is True
    assert Path(output["path"]).exists()
    assert Path(output["no_save_checklist_path"]).exists()


def test_bridge_post_restart_validation_passes_for_current_loaded_bridge(tmp_path):
    bridge = RevitBridgeClient(tmp_path)
    bridge.bridge_dir.mkdir()
    bridge.addin_status_path.write_text(
        json.dumps(
            {
                "status": "started",
                "revit_version": "2025",
                "addin": {
                    "bridge_protocol_version": "0.2",
                    "source_capability_stamp": "continuous-idling-status-file-retry-v2",
                    "supports_continuous_idling": True,
                    "uses_idling_set_raise_without_delay": True,
                    "session_id": "current-session",
                },
            }
        ),
        encoding="utf-8",
    )
    assembly = tmp_path / "HermesRevitOperator.dll"
    assembly.write_bytes(b"fake-dll")
    addins_root = tmp_path / "Addins"
    manifest = addins_root / "2025" / "HermesRevitOperator.addin"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(addin_manifest_text(assembly), encoding="utf-8")

    class Observer:
        def status(self):
            return {
                "supported": True,
                "revit_running": True,
                "state": "idle",
                "active_dialogs": [],
                "main_window": {"hwnd": 1, "title": "Autodesk Revit 2025", "is_hung": False},
            }

    def security_stub(*_args, **_kwargs):
        return {"success": True, "read_only": True, "status": "verified"}

    def ready_stub(*_args, **_kwargs):
        return {"success": True, "read_only": True, "ready": True, "path": str(tmp_path / "ready.json")}

    def audit_stub(*_args, **_kwargs):
        return {
            "success": True,
            "status": "not_complete",
            "north_star_complete": False,
            "implementation_package_complete": True,
            "blocker_summary": {"blocked_gap_count": 3},
            "remaining_gaps": [],
            "path": str(tmp_path / "audit.json"),
        }

    result = bridge_post_restart_validation(
        TaskJournal(tmp_path, "bridge-post-restart-validation-test"),
        Observer(),
        bridge,
        repo_root=Path.cwd(),
        command_names=cli._available_commands(),
        addins_root=addins_root,
        assembly_path=assembly,
        security_preflight_fn=security_stub,
        wait_model_ready_fn=ready_stub,
        north_star_audit_fn=audit_stub,
    )

    assert result["success"] is True
    assert result["read_only"] is True
    assert result["status"] == "passed"
    assert result["validation_passed"] is True
    assert result["failed_checks"] == []
    assert result["failed_check_count"] == 0
    assert all(check["passed"] for check in result["checks"])
    assert result["verify_bridge_build"]["status"] == "current"
    assert result["verify_bridge_build_status"] == "current"
    assert result["verify_bridge_build_success"] is True
    assert result["verify_bridge_build_failed_checks"] == []
    assert result["bridge_readiness"]["ready_for_continuous_bridge"] is True
    assert result["ready_for_continuous_bridge"] is True
    assert result["requires_revit_restart_or_reload"] is False
    assert result["bridge_readiness_failed_checks"] == []
    assert result["model_ready_ready"] is True
    assert "does not close, restart" in result["safety_note"]
    assert Path(result["path"]).is_relative_to(tmp_path)


def test_bridge_post_restart_validation_fails_for_stale_loaded_bridge(tmp_path):
    bridge = RevitBridgeClient(tmp_path)
    bridge.bridge_dir.mkdir()
    bridge.addin_status_path.write_text(
        json.dumps(
            {
                "status": "started",
                "revit_version": "2025",
                "addin": {"session_id": "old-session"},
            }
        ),
        encoding="utf-8",
    )
    assembly = tmp_path / "HermesRevitOperator.dll"
    assembly.write_bytes(b"fake-dll")
    addins_root = tmp_path / "Addins"
    manifest = addins_root / "2025" / "HermesRevitOperator.addin"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(addin_manifest_text(assembly), encoding="utf-8")

    class Observer:
        def status(self):
            return {
                "supported": True,
                "revit_running": True,
                "state": "idle",
                "active_dialogs": [],
                "main_window": {"hwnd": 1, "title": "Autodesk Revit 2025", "is_hung": False},
            }

    result = bridge_post_restart_validation(
        TaskJournal(tmp_path, "bridge-post-restart-validation-stale-test"),
        Observer(),
        bridge,
        repo_root=Path.cwd(),
        command_names=cli._available_commands(),
        addins_root=addins_root,
        assembly_path=assembly,
        security_preflight_fn=lambda *_args, **_kwargs: {"status": "verified"},
        wait_model_ready_fn=lambda *_args, **_kwargs: {"ready": True, "path": str(tmp_path / "ready.json")},
        north_star_audit_fn=lambda *_args, **_kwargs: {"success": True, "path": str(tmp_path / "audit.json")},
    )

    failed = {check["name"] for check in result["checks"] if not check["passed"]}
    assert result["success"] is False
    assert result["status"] == "failed"
    assert result["failed_check_count"] == len(result["failed_checks"])
    assert "loaded_build_current" in failed
    assert "bridge_readiness_ready" in failed
    assert result["failed_checks"] == [
        check["name"] for check in result["checks"] if not check["passed"]
    ]
    assert result["bridge_readiness"]["requires_revit_restart_or_reload"] is True
    assert result["requires_revit_restart_or_reload"] is True
    assert result["ready_for_continuous_bridge"] is False
    assert result["verify_bridge_build_status"] == "stale_or_unverified"
    assert "bridge_protocol_version" in result["verify_bridge_build_failed_checks"]
    assert "loaded_build_current" in result["bridge_readiness_failed_checks"]
    assert result["model_ready_ready"] is True


def test_active_document_status_includes_bridge_status_metadata(tmp_path):
    bridge = RevitBridgeClient(tmp_path)
    bridge.bridge_dir.mkdir()
    bridge.active_document_path.write_text(
        json.dumps({"available": True, "document": {"title": "Sample"}}),
        encoding="utf-8",
    )
    bridge.addin_status_path.write_text(
        json.dumps(
            {
                "status": "started",
                "addin": {
                    "bridge_protocol_version": "0.2",
                    "source_capability_stamp": "continuous-idling-status-file-retry-v2",
                },
            }
        ),
        encoding="utf-8",
    )

    result = bridge.active_document_status()

    assert result["available"] is True
    assert result["bridge"]["available"] is True
    addin = result["bridge"]["addin_status"]["payload"]["addin"]
    assert addin["source_capability_stamp"] == "continuous-idling-status-file-retry-v2"


def test_cli_bridge_status_reads_addin_status(tmp_path, capsys):
    bridge = tmp_path / "bridge"
    bridge.mkdir()
    (bridge / "addin_status.json").write_text(
        json.dumps(
            {
                "status": "started",
                "revit_version": "2025",
                "addin": {
                    "supports_continuous_idling": True,
                    "assembly_path": "C:/temp/HermesRevitOperator.dll",
                },
            }
        ),
        encoding="utf-8",
    )

    code = cli.main(
        [
            "--sandbox",
            str(tmp_path),
            "--allow-sandbox-outside-safe-root",
            "--task-id",
            "bridge-status-test",
            "bridge-status",
        ]
    )

    assert code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["available"] is True
    assert output["addin_status"]["payload"]["addin"]["supports_continuous_idling"] is True


def test_cli_verify_bridge_build_reports_stale_payload(tmp_path, capsys):
    bridge = tmp_path / "bridge"
    bridge.mkdir()
    (bridge / "addin_status.json").write_text(
        json.dumps(
            {
                "status": "started",
                "revit_version": "2025",
                "addin": {"session_id": "old-session"},
            }
        ),
        encoding="utf-8",
    )

    code = cli.main(
        [
            "--sandbox",
            str(tmp_path),
            "--allow-sandbox-outside-safe-root",
            "--task-id",
            "verify-bridge-build-test",
            "verify-bridge-build",
        ]
    )

    assert code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["success"] is False
    assert output["read_only"] is True
    assert output["status"] == "stale_or_unverified"
    assert "restart or reload Revit" in output["recommendation"]


def test_cli_bridge_results_lists_recent_results(tmp_path, capsys):
    bridge = tmp_path / "bridge"
    bridge.mkdir()
    (bridge / "command_results.jsonl").write_text(
        "\n".join(
            [
                json.dumps({"id": "cmd-1", "success": True}),
                json.dumps({"id": "cmd-2", "success": False, "error": "failed"}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    code = cli.main(
        [
            "--sandbox",
            str(tmp_path),
            "--allow-sandbox-outside-safe-root",
            "--task-id",
            "bridge-results-test",
            "bridge-results",
            "--limit",
            "1",
        ]
    )

    assert code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["success"] is True
    assert output["count"] == 1
    assert output["results"][0]["id"] == "cmd-2"


def test_cli_wait_bridge_result_returns_matching_result(tmp_path, capsys):
    bridge = tmp_path / "bridge"
    bridge.mkdir()
    (bridge / "command_results.jsonl").write_text(
        json.dumps({"id": "cmd-1", "success": True, "message": "done"}) + "\n",
        encoding="utf-8",
    )

    code = cli.main(
        [
            "--sandbox",
            str(tmp_path),
            "--allow-sandbox-outside-safe-root",
            "--task-id",
            "wait-bridge-test",
            "wait-bridge-result",
            "--command-id",
            "cmd-1",
            "--timeout",
            "0",
        ]
    )

    assert code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["success"] is True
    assert output["found"] is True
    assert output["result"]["message"] == "done"
