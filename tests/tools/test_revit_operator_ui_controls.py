"""Revit operator UI controls: UIA, OCR, project browser, properties palette and clicks."""

import json
from pathlib import Path

from tools.revit_operator import cli
from tools.revit_operator.actions import ActionRequest, SafeActionExecutor
from tools.revit_operator.bridge import RevitBridgeClient
from tools.revit_operator.journal import TaskJournal
from tools.revit_operator.ocr import ocr_health, ocr_screenshot
import tools.revit_operator.ocr as ocr_module
from tools.revit_operator.palettes import capture_properties_palette_snapshot
from tools.revit_operator.project_browser import (
    capture_project_browser_snapshot,
    plan_project_browser_item_activation,
    plan_project_browser_navigation,
    plan_project_browser_visual_activation,
    run_project_browser_item_activation,
    run_project_browser_visual_activation,
)
from tools.revit_operator.safety import (
    APPROVAL_REQUIRED,
    BLOCK,
    approval_token_for,
)
from tools.revit_operator.uia import (
    find_controls_in_uia_tree,
    uia_control_details,
    uia_invoke_control,
    uia_tree,
)
from tools.revit_operator.windows import find_controls_in_tree


def test_find_controls_in_tree_matches_text_and_class():
    tree = {
        "hwnd": 1,
        "title": "Autodesk Revit",
        "class_name": "MainWindow",
        "enabled": True,
        "visible": True,
        "children": [
            {
                "hwnd": 2,
                "title": "&Manage Links",
                "class_name": "Button",
                "enabled": True,
                "visible": True,
                "rect": {"left": 0, "top": 0, "right": 10, "bottom": 10},
                "children": [],
            },
            {
                "hwnd": 3,
                "title": "Project Browser",
                "class_name": "TreeView",
                "enabled": True,
                "visible": True,
                "children": [],
            },
        ],
    }

    matches = find_controls_in_tree(tree, text="Manage Links", class_name="Button")

    assert len(matches) == 1
    assert matches[0]["hwnd"] == 2
    assert "Autodesk Revit" in matches[0]["path"]


def test_uia_tree_uses_injected_desktop_factory():
    class Info:
        name = "Root"
        control_type = "Window"
        automation_id = "RootId"
        class_name = "RootClass"
        handle = 100

    class ChildInfo:
        name = "Ribbon"
        control_type = "Tab"
        automation_id = "RibbonId"
        class_name = "RibbonClass"
        handle = 101

    class Control:
        def __init__(self, info, children=None):
            self.element_info = info
            self._children = children or []

        def is_enabled(self):
            return True

        def is_visible(self):
            return True

        def children(self):
            return self._children

    class Desktop:
        def window(self, handle):
            assert handle == 100
            return Control(Info(), [Control(ChildInfo())])

    result = uia_tree(hwnd=100, desktop_factory=lambda: Desktop())

    assert result["success"] is True
    assert result["tree"]["automation_id"] == "RootId"
    assert result["tree"]["children"][0]["name"] == "Ribbon"


def test_find_controls_in_uia_tree_matches_automation_id():
    tree = {
        "name": "Autodesk Revit",
        "control_type": "Window",
        "automation_id": "",
        "class_name": "Window",
        "children": [
            {
                "name": "Save",
                "control_type": "Custom",
                "automation_id": "ID_Save_RibbonItemControl",
                "class_name": "",
                "enabled": True,
                "visible": True,
                "children": [],
            }
        ],
    }

    matches = find_controls_in_uia_tree(tree, automation_id="ID_Save_RibbonItemControl")

    assert len(matches) == 1
    assert matches[0]["name"] == "Save"
    assert matches[0]["path"] == "Autodesk Revit > Save"


def test_uia_invoke_control_invokes_exact_fake_match():
    class Info:
        name = "View"
        control_type = "Button"
        automation_id = "View"
        class_name = "Button"
        handle = None

    class Control:
        def __init__(self):
            self.element_info = Info()
            self.invoked = False

        def is_enabled(self):
            return True

        def is_visible(self):
            return True

        def children(self):
            return []

        def invoke(self):
            self.invoked = True

    control = Control()

    class Desktop:
        def window(self, handle):
            assert handle == 100
            return control

    result = uia_invoke_control(
        hwnd=100,
        automation_id="View",
        desktop_factory=lambda: Desktop(),
    )

    assert result["success"] is True
    assert result["method"] == "invoke"
    assert control.invoked is True


def test_uia_control_details_reports_available_methods():
    class Info:
        name = "Sheet S2.0"
        control_type = "TreeItem"
        automation_id = ""
        class_name = "TreeItem"
        handle = None

    class Control:
        element_info = Info()

        def is_enabled(self):
            return True

        def is_visible(self):
            return True

        def children(self):
            return []

        def select(self):
            return None

        def double_click_input(self):
            return None

    class Desktop:
        def window(self, handle):
            assert handle == 100
            return Control()

    result = uia_control_details(
        hwnd=100,
        name="Sheet S2.0",
        desktop_factory=lambda: Desktop(),
        exact=True,
    )

    assert result["success"] is True
    assert result["count"] == 1
    assert "select" in result["matches"][0]["available_methods"]
    assert "double_click_input" in result["matches"][0]["available_methods"]


def test_uia_invoke_control_uses_explicit_select_method():
    class Info:
        name = "Sheet S2.0"
        control_type = "TreeItem"
        automation_id = ""
        class_name = "TreeItem"
        handle = None

    class Control:
        def __init__(self):
            self.element_info = Info()
            self.selected = False

        def is_enabled(self):
            return True

        def is_visible(self):
            return True

        def children(self):
            return []

        def select(self):
            self.selected = True

    control = Control()

    class Desktop:
        def window(self, handle):
            assert handle == 100
            return control

    result = uia_invoke_control(
        hwnd=100,
        name="Sheet S2.0",
        method="select",
        desktop_factory=lambda: Desktop(),
        exact=True,
    )

    assert result["success"] is True
    assert result["method"] == "select"
    assert control.selected is True


def test_cli_uia_tree_writes_missing_dependency_result(tmp_path, capsys):
    code = cli.main(
        [
            "--sandbox",
            str(tmp_path),
            "--allow-sandbox-outside-safe-root",
            "--task-id",
            "uia-tree-test",
            "uia-tree",
            "--hwnd",
            "1",
        ]
    )

    output_text = capsys.readouterr().out
    output = json.loads(output_text)
    assert Path(output["path"]).is_relative_to(tmp_path)
    assert output["success"] in {True, False}


def test_cli_uia_find_control_writes_matches(tmp_path, capsys, monkeypatch):
    def fake_uia_find_controls(**kwargs):
        return {
            "success": True,
            "supported": True,
            "backend": "uia",
            "query": {"automation_id": kwargs.get("automation_id")},
            "count": 1,
            "matches": [
                {
                    "name": "Save",
                    "automation_id": "ID_Save_RibbonItemControl",
                    "control_type": "Custom",
                }
            ],
        }

    monkeypatch.setattr(cli, "uia_find_controls", fake_uia_find_controls)

    code = cli.main(
        [
            "--sandbox",
            str(tmp_path),
            "--allow-sandbox-outside-safe-root",
            "--task-id",
            "uia-find-control-test",
            "uia-find-control",
            "--automation-id",
            "ID_Save_RibbonItemControl",
        ]
    )

    assert code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["success"] is True
    assert output["count"] == 1
    assert Path(output["path"]).is_relative_to(tmp_path)


def test_cli_uia_control_details_writes_available_methods(tmp_path, capsys, monkeypatch):
    def fake_uia_control_details(**_kwargs):
        return {
            "success": True,
            "supported": True,
            "backend": "uia",
            "count": 1,
            "matches": [{"name": "S2.0", "available_methods": ["select", "double_click_input"]}],
        }

    monkeypatch.setattr(cli, "uia_control_details", fake_uia_control_details)

    code = cli.main(
        [
            "--sandbox",
            str(tmp_path),
            "--allow-sandbox-outside-safe-root",
            "--task-id",
            "uia-control-details-test",
            "uia-control-details",
            "--name",
            "S2.0",
        ]
    )

    assert code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["success"] is True
    assert output["matches"][0]["available_methods"] == ["select", "double_click_input"]
    assert Path(output["path"]).is_relative_to(tmp_path)


def test_cli_uia_invoke_dry_run_returns_approval_token(tmp_path, capsys):
    code = cli.main(
        [
            "--sandbox",
            str(tmp_path),
            "--allow-sandbox-outside-safe-root",
            "--task-id",
            "uia-invoke-dry-run-test",
            "uia-invoke",
            "--automation-id",
            "View",
        ]
    )

    assert code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["dry_run"] is True
    assert output["executed"] is False
    assert output["policy"]["decision"] == APPROVAL_REQUIRED
    assert output["policy"]["approval_token"].startswith("APPROVE:")


def test_cli_uia_invoke_save_target_remains_blocked(tmp_path, capsys):
    code = cli.main(
        [
            "--sandbox",
            str(tmp_path),
            "--allow-sandbox-outside-safe-root",
            "--task-id",
            "uia-invoke-save-test",
            "uia-invoke",
            "--automation-id",
            "ID_Save_RibbonItemControl",
        ]
    )

    assert code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["policy"]["decision"] == BLOCK
    assert output["executed"] is False
    assert output["status"] == "blocked"
    assert "--execute" not in output["next_step"]


def test_cli_find_control_writes_matches(tmp_path, capsys, monkeypatch):
    class FakeObserver:
        def find_controls(self, **kwargs):
            return {
                "success": True,
                "supported": True,
                "query": kwargs,
                "count": 1,
                "ambiguous": False,
                "matches": [{"hwnd": 10, "title": "Project Browser", "class_name": "TreeView"}],
            }

    monkeypatch.setattr(cli, "RevitWindowObserver", lambda: FakeObserver())

    code = cli.main(
        [
            "--sandbox",
            str(tmp_path),
            "--allow-sandbox-outside-safe-root",
            "--task-id",
            "find-control-test",
            "find-control",
            "--text",
            "Project Browser",
            "--class-name",
            "TreeView",
        ]
    )

    assert code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["success"] is True
    assert output["count"] == 1
    assert Path(output["path"]).is_relative_to(tmp_path)


def test_ocr_screenshot_uses_injected_runner(tmp_path):
    class FakeObserver:
        def screenshot(self, output, hwnd=None):
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(b"BM")
            return {"success": True, "path": str(output), "hwnd": hwnd}

    result = ocr_screenshot(
        TaskJournal(tmp_path, "ocr-test"),
        FakeObserver(),
        hwnd=123,
        ocr_runner=lambda _path: "Hello\nRevit",
    )

    assert result["success"] is True
    assert result["backend"] == "injected"
    assert result["text_length"] == len("Hello\nRevit")
    assert result["line_count"] == 2
    assert result["item_count"] == 0
    assert Path(result["path"]).is_relative_to(tmp_path)


def test_ocr_screenshot_extracts_rapidocr_geometry_from_runner(tmp_path):
    class FakeObserver:
        def screenshot(self, output, hwnd=None):
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(b"BM")
            return {"success": True, "path": str(output), "hwnd": hwnd}

    rapidocr_shape = (
        [
            [
                [[133.0, 193.0], [354.0, 194.0], [354.0, 214.0], [133.0, 213.0]],
                "S2.0_1_FOUNDATION PLAN",
                0.98,
            ],
        ],
        [0.01, 0.02, 0.03],
    )

    result = ocr_screenshot(
        TaskJournal(tmp_path, "ocr-geometry-test"),
        FakeObserver(),
        hwnd=123,
        ocr_runner=lambda _path: rapidocr_shape,
    )

    assert result["success"] is True
    assert result["text"] == "S2.0_1_FOUNDATION PLAN"
    assert result["item_count"] == 1
    assert result["items"][0]["confidence"] == 0.98
    assert result["items"][0]["bounds"]["left"] == 133.0
    assert result["items"][0]["bounds"]["right"] == 354.0
    assert result["items"][0]["bounds"]["center_x"] == 243.5
    artifact = json.loads(Path(result["path"]).read_text(encoding="utf-8"))
    assert artifact["items"][0]["text"] == "S2.0_1_FOUNDATION PLAN"


def test_ocr_health_reports_dependency_shape(monkeypatch):
    monkeypatch.delenv("HERMES_TESSERACT_CMD", raising=False)

    result = ocr_health()

    assert result["success"] is True
    assert "Pillow" in result["python_packages"]
    assert "pytesseract" in result["python_packages"]
    assert "rapidocr" in result["backends"]
    assert isinstance(result["missing"], list)
    assert "install_hint" in result


def test_rapidocr_result_parser_handles_common_shapes():
    old_shape = (
        [
            [[[0, 0], [1, 0], [1, 1], [0, 1]], "Sheet S2.0", 0.99],
            [[[0, 2], [1, 2], [1, 3], [0, 3]], "FOUNDATION PLAN", 0.98],
        ],
        0.12,
    )
    dict_shape = {"txts": ["Warnings", "Review"]}

    assert ocr_module._rapidocr_result_to_text(old_shape) == "Sheet S2.0\nFOUNDATION PLAN"
    assert ocr_module._rapidocr_result_to_text(dict_shape) == "Warnings\nReview"
    payload = ocr_module._ocr_payload(old_shape)
    assert payload["items"][0]["text"] == "Sheet S2.0"
    assert payload["items"][0]["bounds"] == {
        "left": 0.0,
        "top": 0.0,
        "right": 1.0,
        "bottom": 1.0,
        "width": 1.0,
        "height": 1.0,
        "center_x": 0.5,
        "center_y": 0.5,
    }


def test_ocr_health_can_report_rapidocr_ready_without_tesseract(monkeypatch):
    def fake_has_module(name):
        return name in {"rapidocr_onnxruntime"}

    monkeypatch.setattr(ocr_module, "_has_module", fake_has_module)
    monkeypatch.setattr(ocr_module, "_tesseract_executable", lambda: None)

    result = ocr_module.ocr_health()

    assert result["ready"] is True
    assert result["preferred_backend"] == "rapidocr"
    assert result["backends"]["tesseract"]["ready"] is False
    assert result["backends"]["rapidocr"]["ready"] is True
    assert result["missing"] == []


def test_cli_ocr_health_is_read_only(tmp_path, capsys):
    code = cli.main(
        [
            "--sandbox",
            str(tmp_path),
            "--allow-sandbox-outside-safe-root",
            "--task-id",
            "ocr-health-test",
            "ocr-health",
        ]
    )

    assert code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["success"] is True
    assert "ready" in output
    assert "tesseract_executable" in output
    assert "backends" in output


def test_cli_ocr_screenshot_writes_artifact(tmp_path, capsys, monkeypatch):
    class FakeObserver:
        def screenshot(self, output, hwnd=None):
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(b"BM")
            return {"success": True, "path": str(output), "hwnd": hwnd}

    monkeypatch.setattr(cli, "RevitWindowObserver", lambda: FakeObserver())

    code = cli.main(
        [
            "--sandbox",
            str(tmp_path),
            "--allow-sandbox-outside-safe-root",
            "--task-id",
            "ocr-cli-test",
            "ocr-screenshot",
        ]
    )

    output = json.loads(capsys.readouterr().out)
    assert code in {0, 2}
    assert Path(output["path"]).is_relative_to(tmp_path)
    assert "screenshot" in output


def test_project_browser_snapshot_captures_selected_control(tmp_path):
    class FakeObserver:
        def find_controls(self, **_kwargs):
            return {
                "success": True,
                "matches": [
                    {"hwnd": 42, "title": "Project Browser", "class_name": "Afx:ControlBar"}
                ],
            }

        def ui_tree(self, hwnd, max_depth=4):
            return {
                "supported": True,
                "hwnd": hwnd,
                "max_depth": max_depth,
                "tree": {"title": "Project Browser"},
            }

        def screenshot(self, output, hwnd=None):
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(b"BM")
            return {"success": True, "path": str(output), "hwnd": hwnd}

    result = capture_project_browser_snapshot(
        TaskJournal(tmp_path, "project-browser-test"),
        FakeObserver(),
        include_uia=True,
        include_ocr=True,
        ocr_backend="rapidocr",
        ocr_func=lambda *_args, **_kwargs: {
            "success": True,
            "text": "Sheets\nS2.0\nFOUNDATION PLAN",
            "line_count": 3,
            "path": str(tmp_path / "ocr.json"),
            "screenshot": {"path": str(tmp_path / "ocr.bmp")},
            "read_only": True,
        },
        uia_tree_func=lambda **_kwargs: {"supported": True, "node_count": 2, "tree": {}},
    )

    assert result["success"] is True
    assert result["uia_node_count"] == 2
    snapshot = json.loads(Path(result["path"]).read_text(encoding="utf-8"))
    assert snapshot["selected_control"]["hwnd"] == 42
    assert snapshot["uia_tree"]["node_count"] == 2
    assert snapshot["ocr"]["line_count"] == 3
    assert result["ocr_enabled"] is True
    assert result["ocr_success"] is True
    assert snapshot["note"].startswith("Project Browser was observed")


def test_cli_project_browser_snapshot_writes_bundle(tmp_path, capsys, monkeypatch):
    class FakeObserver:
        def find_controls(self, **_kwargs):
            return {
                "success": True,
                "matches": [
                    {"hwnd": 42, "title": "Project Browser", "class_name": "Afx:ControlBar"}
                ],
            }

        def ui_tree(self, hwnd, max_depth=4):
            return {"supported": True, "hwnd": hwnd, "tree": {"title": "Project Browser"}}

        def screenshot(self, output, hwnd=None):
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(b"BM")
            return {"success": True, "path": str(output), "hwnd": hwnd}

    monkeypatch.setattr(cli, "RevitWindowObserver", lambda: FakeObserver())

    code = cli.main(
        [
            "--sandbox",
            str(tmp_path),
            "--allow-sandbox-outside-safe-root",
            "--task-id",
            "project-browser-cli-test",
            "project-browser-snapshot",
        ]
    )

    assert code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["success"] is True
    assert output["selected_hwnd"] == 42


def test_properties_palette_snapshot_captures_selected_control(tmp_path):
    class FakeObserver:
        def find_controls(self, **_kwargs):
            return {
                "success": True,
                "matches": [
                    {
                        "hwnd": 101,
                        "title": "Properties",
                        "class_name": "Afx:ControlBar",
                        "depth": 1,
                        "rect": {"width": 250, "height": 400},
                    },
                    {
                        "hwnd": 102,
                        "title": "Properties",
                        "class_name": "#32770",
                        "depth": 3,
                        "rect": {"width": 250, "height": 400},
                    },
                ],
            }

        def ui_tree(self, hwnd, max_depth=4):
            return {
                "supported": True,
                "hwnd": hwnd,
                "max_depth": max_depth,
                "tree": {"title": "Properties"},
            }

        def screenshot(self, output, hwnd=None):
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(b"BM")
            return {"success": True, "path": str(output), "hwnd": hwnd}

    result = capture_properties_palette_snapshot(
        TaskJournal(tmp_path, "properties-palette-test"),
        FakeObserver(),
        include_uia=True,
        include_ocr=True,
        ocr_backend="rapidocr",
        ocr_func=lambda *_args, **_kwargs: {
            "success": True,
            "text": "Properties\nConstraints\nDimensions",
            "line_count": 3,
            "items": [{"text": "Constraints", "confidence": 0.99}],
            "path": str(tmp_path / "ocr.json"),
            "screenshot": {"path": str(tmp_path / "ocr.bmp")},
            "read_only": True,
        },
        uia_tree_func=lambda **_kwargs: {"supported": True, "node_count": 4, "tree": {}},
    )

    assert result["success"] is True
    assert result["selected_hwnd"] == 101
    assert result["uia_node_count"] == 4
    assert result["ocr_line_count"] == 3
    assert result["ocr_items"][0]["text"] == "Constraints"
    snapshot = json.loads(Path(result["path"]).read_text(encoding="utf-8"))
    assert snapshot["selected_control"]["hwnd"] == 101
    assert snapshot["note"].startswith("Properties palette was observed")


def test_cli_properties_palette_snapshot_writes_bundle(tmp_path, capsys, monkeypatch):
    class FakeObserver:
        def find_controls(self, **_kwargs):
            return {
                "success": True,
                "matches": [
                    {"hwnd": 101, "title": "Properties", "class_name": "Afx:ControlBar"}
                ],
            }

        def ui_tree(self, hwnd, max_depth=4):
            return {"supported": True, "hwnd": hwnd, "tree": {"title": "Properties"}}

        def screenshot(self, output, hwnd=None):
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(b"BM")
            return {"success": True, "path": str(output), "hwnd": hwnd}

    monkeypatch.setattr(cli, "RevitWindowObserver", lambda: FakeObserver())

    code = cli.main(
        [
            "--sandbox",
            str(tmp_path),
            "--allow-sandbox-outside-safe-root",
            "--task-id",
            "properties-palette-cli-test",
            "properties-palette-snapshot",
        ]
    )

    assert code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["success"] is True
    assert output["selected_hwnd"] == 101


def test_project_browser_navigation_plan_prefers_guarded_activate_view(tmp_path):
    (tmp_path / "bridge").mkdir()
    (tmp_path / "bridge" / "metadata_snapshot.json").write_text(
        json.dumps(
            {
                "sheets": [
                    {
                        "id": 101,
                        "sheet_number": "S101",
                        "name": "Framing Plan",
                        "is_placeholder": False,
                    }
                ],
                "views": [],
            }
        ),
        encoding="utf-8",
    )

    class FakeObserver:
        def find_controls(self, **_kwargs):
            return {
                "success": True,
                "matches": [
                    {"hwnd": 42, "title": "Project Browser", "class_name": "Afx:ControlBar"}
                ],
            }

        def ui_tree(self, hwnd, max_depth=4):
            return {"supported": True, "hwnd": hwnd, "tree": {"title": "Project Browser"}}

        def screenshot(self, output, hwnd=None):
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(b"BM")
            return {"success": True, "path": str(output), "hwnd": hwnd}

    result = plan_project_browser_navigation(
        TaskJournal(tmp_path, "project-browser-navigation-test"),
        FakeObserver(),
        RevitBridgeClient(tmp_path),
        sheet_number="S101",
        include_ocr=True,
        ocr_func=lambda *_args, **_kwargs: {
            "success": True,
            "text": "S101\nFOUNDATION PLAN",
            "line_count": 2,
            "path": str(tmp_path / "project-browser-ocr.json"),
            "read_only": True,
        },
    )

    assert result["success"] is True
    assert result["project_browser_observed"] is True
    assert result["route"]["recommended_method"] == "request-operation activate-view"
    assert result["route"]["args"] == {"id": 101, "sheet_number": "S101"}
    assert result["visual_evidence"]["ocr_match_count"] == 1
    assert result["visual_evidence"]["ocr_matches"][0]["text"] == "S101"
    plan = json.loads(Path(result["path"]).read_text(encoding="utf-8"))
    assert plan["project_browser_snapshot"]["ocr_line_count"] == 2
    assert plan["visual_evidence"]["ocr_match_count"] == 1
    assert plan["note"].startswith("This command plans navigation only")


def test_project_browser_navigation_uses_ocr_evidence_when_metadata_has_no_match(tmp_path):
    (tmp_path / "bridge").mkdir()
    (tmp_path / "bridge" / "metadata_snapshot.json").write_text(
        json.dumps({"sheets": [], "views": []}),
        encoding="utf-8",
    )

    class FakeObserver:
        def find_controls(self, **_kwargs):
            return {
                "success": True,
                "matches": [
                    {"hwnd": 42, "title": "Project Browser", "class_name": "Afx:ControlBar"}
                ],
            }

        def ui_tree(self, hwnd, max_depth=4):
            return {"supported": True, "hwnd": hwnd, "tree": {"title": "Project Browser"}}

        def screenshot(self, output, hwnd=None):
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(b"BM")
            return {"success": True, "path": str(output), "hwnd": hwnd}

    result = plan_project_browser_navigation(
        TaskJournal(tmp_path, "project-browser-navigation-ocr-fallback-test"),
        FakeObserver(),
        RevitBridgeClient(tmp_path),
        sheet_number="S2.0",
        include_ocr=True,
        ocr_func=lambda *_args, **_kwargs: {
            "success": True,
            "text": "Views\nSheet Views\nS2.0_1_FOUNDATION PLAN",
            "line_count": 3,
            "path": str(tmp_path / "project-browser-ocr.json"),
            "read_only": True,
        },
    )

    assert result["success"] is True
    assert result["route"]["recommended_method"] == "ask_human"
    assert "OCR found possible visible Project Browser matches" in result["route"]["reason"]
    assert result["visual_evidence"]["ocr_match_count"] == 1
    assert result["visual_evidence"]["ocr_matches"][0]["matched_terms"] == ["S2.0"]


def test_project_browser_navigation_keeps_ocr_match_geometry(tmp_path):
    (tmp_path / "bridge").mkdir()
    (tmp_path / "bridge" / "metadata_snapshot.json").write_text(
        json.dumps({"sheets": [], "views": []}),
        encoding="utf-8",
    )

    class FakeObserver:
        def find_controls(self, **_kwargs):
            return {
                "success": True,
                "matches": [
                    {"hwnd": 42, "title": "Project Browser", "class_name": "Afx:ControlBar"}
                ],
            }

        def ui_tree(self, hwnd, max_depth=4):
            return {"supported": True, "hwnd": hwnd, "tree": {"title": "Project Browser"}}

        def screenshot(self, output, hwnd=None):
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(b"BM")
            return {"success": True, "path": str(output), "hwnd": hwnd}

    result = plan_project_browser_navigation(
        TaskJournal(tmp_path, "project-browser-navigation-ocr-geometry-test"),
        FakeObserver(),
        RevitBridgeClient(tmp_path),
        sheet_number="S2.0",
        include_ocr=True,
        ocr_func=lambda *_args, **_kwargs: {
            "success": True,
            "text": "Views\nS2.0_1_FOUNDATION PLAN",
            "line_count": 2,
            "items": [
                {
                    "line_number": 2,
                    "text": "S2.0_1_FOUNDATION PLAN",
                    "confidence": 0.979,
                    "bounds": {
                        "left": 133.0,
                        "top": 193.0,
                        "right": 354.0,
                        "bottom": 214.0,
                        "width": 221.0,
                        "height": 21.0,
                        "center_x": 243.5,
                        "center_y": 203.5,
                    },
                }
            ],
            "path": str(tmp_path / "project-browser-ocr.json"),
            "read_only": True,
        },
    )

    match = result["visual_evidence"]["ocr_matches"][0]
    assert result["visual_evidence"]["ocr_item_count"] == 1
    assert match["source"] == "ocr_item"
    assert match["confidence"] == 0.979
    assert match["bounds"]["left"] == 133.0
    assert match["bounds"]["center_y"] == 203.5
    plan = json.loads(Path(result["path"]).read_text(encoding="utf-8"))
    assert plan["project_browser_snapshot"]["ocr_items"][0]["bounds"]["right"] == 354.0


def test_project_browser_visual_activation_plans_ocr_coordinate_click(tmp_path):
    class FakeObserver:
        def find_controls(self, **_kwargs):
            return {
                "success": True,
                "matches": [
                    {"hwnd": 42, "title": "Project Browser", "class_name": "Afx:ControlBar"}
                ],
            }

        def ui_tree(self, hwnd, max_depth=4):
            return {"supported": True, "hwnd": hwnd, "tree": {"title": "Project Browser"}}

        def screenshot(self, output, hwnd=None):
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(b"BM")
            return {
                "success": True,
                "path": str(output),
                "hwnd": hwnd,
                "rect": {"left": 100.0, "top": 200.0, "right": 500.0, "bottom": 800.0},
            }

    result = plan_project_browser_visual_activation(
        TaskJournal(tmp_path, "project-browser-visual-plan-test"),
        FakeObserver(),
        sheet_number="S2.0",
        ocr_func=lambda *_args, **_kwargs: {
            "success": True,
            "text": "S2.0_1_FOUNDATION PLAN",
            "line_count": 1,
            "items": [
                {
                    "text": "S2.0_1_FOUNDATION PLAN",
                    "bounds": {
                        "left": 133.0,
                        "top": 193.0,
                        "right": 354.0,
                        "bottom": 214.0,
                        "width": 221.0,
                        "height": 21.0,
                        "center_x": 243.5,
                        "center_y": 203.5,
                    },
                }
            ],
            "read_only": True,
        },
    )

    assert result["success"] is True
    assert result["executable"] is True
    assert result["policy"]["action"] == "visual-click"
    assert result["policy"]["decision"] == APPROVAL_REQUIRED
    assert result["payload"]["coordinate_source"] == "project-browser-ocr"
    assert result["payload"]["screen_x"] == 343.5
    assert result["payload"]["screen_y"] == 403.5
    assert result["read_only"] is True


def test_project_browser_visual_activation_dry_run_returns_token(tmp_path):
    class FakeObserver:
        def find_controls(self, **_kwargs):
            return {
                "success": True,
                "matches": [
                    {"hwnd": 42, "title": "Project Browser", "class_name": "Afx:ControlBar"}
                ],
            }

        def ui_tree(self, hwnd, max_depth=4):
            return {"supported": True, "hwnd": hwnd, "tree": {"title": "Project Browser"}}

        def screenshot(self, output, hwnd=None):
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(b"BM")
            return {
                "success": True,
                "path": str(output),
                "hwnd": hwnd,
                "rect": {"left": 100.0, "top": 200.0, "right": 500.0, "bottom": 800.0},
            }

        def status(self):
            return {"state": "idle"}

    result = run_project_browser_visual_activation(
        TaskJournal(tmp_path, "project-browser-visual-run-test"),
        FakeObserver(),
        sheet_number="S2.0",
        ocr_func=lambda *_args, **_kwargs: {
            "success": True,
            "text": "S2.0_1_FOUNDATION PLAN",
            "line_count": 1,
            "items": [
                {
                    "text": "S2.0_1_FOUNDATION PLAN",
                    "bounds": {
                        "left": 133.0,
                        "top": 193.0,
                        "right": 354.0,
                        "bottom": 214.0,
                        "center_x": 243.5,
                        "center_y": 203.5,
                    },
                }
            ],
            "read_only": True,
        },
    )

    assert result["dry_run"] is True
    assert result["execution"]["status"] == "dry_run"
    assert result["execution"]["policy"]["approval_token"].startswith("APPROVE:")
    assert result["executed"] is False


def test_visual_click_executor_uses_screen_coordinates_after_approval(tmp_path):
    calls = []

    class FakeUser32:
        def SetForegroundWindow(self, hwnd):
            calls.append(("focus", hwnd))
            return True

        def SetCursorPos(self, x, y):
            calls.append(("cursor", x, y))
            return True

        def mouse_event(self, event, dx, dy, data, extra):
            calls.append(("mouse", event, dx, dy, data, extra))
            return None

    class FakeObserver:
        supported = True
        user32 = FakeUser32()

        def status(self):
            return {"state": "idle"}

        def _default_target_hwnd(self):
            return 42

    payload = {
        "hwnd": 42,
        "screen_x": 344,
        "screen_y": 404,
        "target_text": "S2.0_1_FOUNDATION PLAN",
        "coordinate_source": "project-browser-ocr",
    }
    result = SafeActionExecutor(FakeObserver(), TaskJournal(tmp_path, "visual-click-test")).run(
        ActionRequest(
            action="visual-click",
            payload=payload,
            dry_run=False,
            approval_token=approval_token_for("visual-click", payload),
        )
    )

    assert result["executed"] is True
    assert ("focus", 42) in calls
    assert ("cursor", 344, 404) in calls
    assert [call[0] for call in calls].count("mouse") == 2


def test_cli_project_browser_plan_navigation_writes_plan(tmp_path, capsys, monkeypatch):
    (tmp_path / "bridge").mkdir()
    (tmp_path / "bridge" / "metadata_snapshot.json").write_text(
        json.dumps(
            {
                "sheets": [
                    {
                        "id": 202,
                        "sheet_number": "S202",
                        "name": "Enlarged Plan",
                        "is_placeholder": False,
                    }
                ],
                "views": [],
            }
        ),
        encoding="utf-8",
    )

    class FakeObserver:
        def find_controls(self, **_kwargs):
            return {
                "success": True,
                "matches": [
                    {"hwnd": 7, "title": "Project Browser", "class_name": "Afx:ControlBar"}
                ],
            }

        def ui_tree(self, hwnd, max_depth=4):
            return {"supported": True, "hwnd": hwnd, "tree": {"title": "Project Browser"}}

        def screenshot(self, output, hwnd=None):
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(b"BM")
            return {"success": True, "path": str(output), "hwnd": hwnd}

    monkeypatch.setattr(cli, "RevitWindowObserver", lambda: FakeObserver())

    code = cli.main(
        [
            "--sandbox",
            str(tmp_path),
            "--allow-sandbox-outside-safe-root",
            "--task-id",
            "project-browser-plan-cli-test",
            "project-browser-plan-navigation",
            "--sheet-number",
            "S202",
        ]
    )

    assert code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["success"] is True
    assert output["route"]["recommended_method"] == "request-operation activate-view"
    assert Path(output["path"]).is_relative_to(tmp_path)


def test_project_browser_item_activation_plan_requires_single_uia_target(tmp_path):
    class FakeObserver:
        def find_controls(self, **_kwargs):
            return {
                "success": True,
                "matches": [{"hwnd": 99, "title": "Project Browser", "class_name": "Afx:ControlBar"}],
            }

    def fake_uia_find(**_kwargs):
        return {
            "success": True,
            "count": 1,
            "ambiguous": False,
            "matches": [
                {
                    "name": "S2.0 - FOUNDATION PLAN",
                    "control_type": "TreeItem",
                    "enabled": True,
                    "visible": True,
                }
            ],
        }

    result = plan_project_browser_item_activation(
        TaskJournal(tmp_path, "project-browser-activation-plan-test"),
        FakeObserver(),
        name="S2.0",
        uia_find_func=fake_uia_find,
    )

    assert result["success"] is True
    assert result["executable"] is True
    assert result["policy"]["decision"] == APPROVAL_REQUIRED
    assert result["payload"]["hwnd"] == 99
    assert Path(result["path"]).is_relative_to(tmp_path)


def test_project_browser_activate_item_dry_run_returns_approval_token(tmp_path):
    class FakeObserver:
        def find_controls(self, **_kwargs):
            return {
                "success": True,
                "matches": [{"hwnd": 99, "title": "Project Browser", "class_name": "Afx:ControlBar"}],
            }

        def status(self):
            return {"state": "idle", "active_dialogs": []}

    def fake_uia_find(**_kwargs):
        return {
            "success": True,
            "count": 1,
            "ambiguous": False,
            "matches": [{"name": "S2.0", "enabled": True, "visible": True}],
        }

    result = run_project_browser_item_activation(
        TaskJournal(tmp_path, "project-browser-activation-dry-run-test"),
        FakeObserver(),
        name="S2.0",
        dry_run=True,
        uia_find_func=fake_uia_find,
    )

    assert result["executed"] is False
    assert result["execution"]["dry_run"] is True
    assert result["execution"]["policy"]["approval_token"].startswith("APPROVE:")


def test_cli_project_browser_plan_activation_writes_plan(tmp_path, capsys, monkeypatch):
    class FakeObserver:
        def find_controls(self, **_kwargs):
            return {
                "success": True,
                "matches": [{"hwnd": 77, "title": "Project Browser", "class_name": "Afx:ControlBar"}],
            }

    def fake_uia_find_controls(**_kwargs):
        return {
            "success": True,
            "count": 1,
            "ambiguous": False,
            "matches": [{"name": "S3.0", "enabled": True, "visible": True}],
        }

    monkeypatch.setattr(cli, "RevitWindowObserver", lambda: FakeObserver())
    monkeypatch.setattr("tools.revit_operator.project_browser.uia_find_controls", fake_uia_find_controls)

    code = cli.main(
        [
            "--sandbox",
            str(tmp_path),
            "--allow-sandbox-outside-safe-root",
            "--task-id",
            "project-browser-plan-activation-cli-test",
            "project-browser-plan-activation",
            "--name",
            "S3.0",
        ]
    )

    assert code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["success"] is True
    assert output["executable"] is True
    assert output["payload"]["hwnd"] == 77


def test_cli_click_dry_run_returns_approval_token_and_does_not_execute(tmp_path, capsys):
    code = cli.main(
        [
            "--sandbox",
            str(tmp_path),
            "--allow-sandbox-outside-safe-root",
            "--task-id",
            "click-test",
            "click",
            "--target",
            "Cancel",
        ]
    )

    assert code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["dry_run"] is True
    assert output["executed"] is False
    assert output["policy"]["decision"] == APPROVAL_REQUIRED
    assert output["policy"]["approval_token"].startswith("APPROVE:")


def test_cli_visual_click_dry_run_returns_coordinate_payload(tmp_path, capsys):
    code = cli.main(
        [
            "--sandbox",
            str(tmp_path),
            "--allow-sandbox-outside-safe-root",
            "--task-id",
            "visual-click-cli-test",
            "visual-click",
            "--screen-x",
            "245",
            "--screen-y",
            "134",
            "--target-text",
            "Visibility/Graphics",
            "--coordinate-source",
            "test-screenshot",
        ]
    )

    assert code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["dry_run"] is True
    assert output["executed"] is False
    assert output["policy"]["action"] == "visual-click"
    assert output["policy"]["decision"] == APPROVAL_REQUIRED
    assert output["policy"]["approval_token"] == approval_token_for(
        "visual-click",
        {
            "screen_x": 245,
            "screen_y": 134,
            "target_text": "Visibility/Graphics",
            "coordinate_source": "test-screenshot",
        },
    )
