"""Windows UI observation primitives for Autodesk Revit."""

from __future__ import annotations

import re
import struct
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

from .safety import classify_dialog


@dataclass
class Rect:
    left: int
    top: int
    right: int
    bottom: int

    @property
    def width(self) -> int:
        return max(0, self.right - self.left)

    @property
    def height(self) -> int:
        return max(0, self.bottom - self.top)

    def to_dict(self) -> dict:
        return {
            "left": self.left,
            "top": self.top,
            "right": self.right,
            "bottom": self.bottom,
            "width": self.width,
            "height": self.height,
        }


@dataclass
class WindowInfo:
    hwnd: int
    pid: int
    title: str
    class_name: str
    rect: Rect
    visible: bool
    enabled: bool
    foreground: bool
    owner_hwnd: int
    process_path: str
    process_name: str
    revit_version: str | None
    is_revit_related: bool
    is_dialog_like: bool
    is_hung: bool

    def to_dict(self) -> dict:
        data = asdict(self)
        data["rect"] = self.rect.to_dict()
        return data


@dataclass
class ProcessInfo:
    pid: int
    process_name: str
    process_path: str
    revit_version: str | None

    def to_dict(self) -> dict:
        return asdict(self)


def is_windows() -> bool:
    return sys.platform == "win32"


class RevitWindowObserver:
    """Observe Revit windows using Win32 APIs and optional UIA fallbacks."""

    def __init__(self) -> None:
        self.supported = is_windows()
        if self.supported:
            self._init_win32()

    def _init_win32(self) -> None:
        import ctypes
        from ctypes import wintypes

        self.ctypes = ctypes
        self.wintypes = wintypes
        self.user32 = ctypes.windll.user32
        self.kernel32 = ctypes.windll.kernel32
        self.gdi32 = ctypes.windll.gdi32

        self._EnumWindowsProc = ctypes.WINFUNCTYPE(
            wintypes.BOOL, wintypes.HWND, wintypes.LPARAM
        )
        self.user32.EnumWindows.argtypes = [self._EnumWindowsProc, wintypes.LPARAM]
        self.user32.EnumWindows.restype = wintypes.BOOL
        self.user32.GetForegroundWindow.restype = wintypes.HWND
        self.user32.GetWindow.argtypes = [wintypes.HWND, ctypes.c_uint]
        self.user32.GetWindow.restype = wintypes.HWND
        self.user32.IsWindowVisible.argtypes = [wintypes.HWND]
        self.user32.IsWindowVisible.restype = wintypes.BOOL
        self.user32.IsWindowEnabled.argtypes = [wintypes.HWND]
        self.user32.IsWindowEnabled.restype = wintypes.BOOL
        self.user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
        self.user32.GetWindowTextLengthW.restype = ctypes.c_int
        self.user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        self.user32.GetWindowTextW.restype = ctypes.c_int
        self.user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        self.user32.GetClassNameW.restype = ctypes.c_int
        self.user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
        self.user32.GetWindowRect.restype = wintypes.BOOL
        self.user32.GetWindowThreadProcessId.argtypes = [
            wintypes.HWND,
            ctypes.POINTER(wintypes.DWORD),
        ]
        self.user32.GetWindowThreadProcessId.restype = wintypes.DWORD
        self.user32.IsHungAppWindow.argtypes = [wintypes.HWND]
        self.user32.IsHungAppWindow.restype = wintypes.BOOL
        self.user32.SetForegroundWindow.argtypes = [wintypes.HWND]
        self.user32.SetForegroundWindow.restype = wintypes.BOOL
        self.user32.SendMessageW.argtypes = [
            wintypes.HWND,
            wintypes.UINT,
            wintypes.WPARAM,
            wintypes.LPARAM,
        ]
        self.user32.SendMessageW.restype = wintypes.LPARAM
        self.user32.keybd_event.argtypes = [
            wintypes.BYTE,
            wintypes.BYTE,
            wintypes.DWORD,
            wintypes.ULONG,
        ]
        self.user32.GetWindowDC.argtypes = [wintypes.HWND]
        self.user32.GetWindowDC.restype = wintypes.HANDLE
        self.user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HANDLE]
        self.kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        self.kernel32.OpenProcess.restype = wintypes.HANDLE
        self.kernel32.QueryFullProcessImageNameW.argtypes = [
            wintypes.HANDLE,
            wintypes.DWORD,
            wintypes.LPWSTR,
            ctypes.POINTER(wintypes.DWORD),
        ]
        self.kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
        self.kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        self.kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
        self.kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
        self.gdi32.CreateCompatibleDC.argtypes = [wintypes.HANDLE]
        self.gdi32.CreateCompatibleDC.restype = wintypes.HANDLE
        self.gdi32.CreateCompatibleBitmap.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_int]
        self.gdi32.CreateCompatibleBitmap.restype = getattr(
            wintypes, "HBITMAP", wintypes.HANDLE
        )
        self.gdi32.SelectObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        self.gdi32.SelectObject.restype = wintypes.HANDLE
        self.gdi32.DeleteObject.argtypes = [wintypes.HANDLE]
        self.gdi32.DeleteDC.argtypes = [wintypes.HANDLE]
        self.gdi32.BitBlt.argtypes = [
            wintypes.HANDLE,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            wintypes.HANDLE,
            ctypes.c_int,
            ctypes.c_int,
            wintypes.DWORD,
        ]
        self.gdi32.BitBlt.restype = wintypes.BOOL
        self.gdi32.GetDIBits.argtypes = [
            wintypes.HANDLE,
            wintypes.HANDLE,
            wintypes.UINT,
            wintypes.UINT,
            ctypes.c_void_p,
            ctypes.c_void_p,
            wintypes.UINT,
        ]
        self.gdi32.GetDIBits.restype = ctypes.c_int

    def health(self) -> dict:
        optional = {
            "pywinauto": _optional_import_available("pywinauto"),
            "PIL.ImageGrab": _optional_import_available("PIL.ImageGrab"),
        }
        return {
            "supported": self.supported,
            "platform": sys.platform,
            "observer": "win32-ctypes" if self.supported else "unsupported",
            "optional_dependencies": optional,
        }

    def list_windows(self, include_all: bool = False) -> dict:
        if not self.supported:
            return {
                "supported": False,
                "windows": [],
                "error": "Windows UI automation is only available on win32.",
            }

        windows = self._top_level_windows()
        selected = windows if include_all else [w for w in windows if w.is_revit_related]
        return {
            "supported": True,
            "windows": [window.to_dict() for window in selected],
            "count": len(selected),
        }

    def list_processes(self) -> dict:
        if not self.supported:
            return {
                "supported": False,
                "processes": [],
                "error": "Windows process enumeration is only available on win32.",
            }
        processes = self._revit_processes()
        return {
            "supported": True,
            "processes": [process.to_dict() for process in processes],
            "count": len(processes),
        }

    def status(self) -> dict:
        health = self.health()
        if not self.supported:
            return {
                **health,
                "state": "unsupported",
                "revit_running": False,
                "main_window": None,
                "active_dialogs": [],
            }

        windows = [w for w in self._top_level_windows() if w.is_revit_related]
        processes = self._revit_processes()
        main = self._choose_main_window(windows)
        dialogs = self._dialog_windows(windows)
        if not windows and not processes:
            state = "not_running"
        elif dialogs:
            state = "modal"
        elif any(w.is_hung for w in windows):
            state = "busy"
        elif main:
            state = "idle"
        else:
            state = "unknown"

        return {
            **health,
            "state": state,
            "revit_running": bool(windows or processes),
            "processes": [process.to_dict() for process in processes],
            "main_window": main.to_dict() if main else None,
            "active_dialogs": [dialog.to_dict() for dialog in dialogs],
            "window_count": len(windows),
        }

    def list_dialogs(self) -> dict:
        if not self.supported:
            return {
                "supported": False,
                "dialogs": [],
                "error": "Windows UI automation is only available on win32.",
            }
        dialogs = []
        for window in self._dialog_windows(
            [w for w in self._top_level_windows() if w.is_revit_related]
        ):
            extracted = self._extract_dialog_content(window.hwnd)
            dialogs.append(
                {
                    **window.to_dict(),
                    **extracted,
                    "classification": classify_dialog(
                        title=window.title,
                        text=extracted.get("dialog_text", ""),
                        buttons=extracted.get("buttons", []),
                    ),
                }
            )
        return {"supported": True, "dialogs": dialogs, "count": len(dialogs)}

    def ui_tree(self, hwnd: int | None = None, max_depth: int = 4) -> dict:
        if not self.supported:
            return {
                "supported": False,
                "tree": None,
                "error": "Windows UI automation is only available on win32.",
            }

        target = hwnd or self._default_target_hwnd()
        if not target:
            return {
                "supported": True,
                "tree": None,
                "error": "No visible Revit window found.",
            }
        return {
            "supported": True,
            "hwnd": target,
            "tree": self._window_tree(target, max_depth=max_depth),
        }

    def find_controls(
        self,
        *,
        text: str = "",
        class_name: str = "",
        hwnd: int | None = None,
        max_depth: int = 6,
        limit: int = 50,
        exact: bool = False,
    ) -> dict:
        if not self.supported:
            return {
                "supported": False,
                "matches": [],
                "error": "Windows UI automation is only available on win32.",
            }

        target = hwnd or self._default_target_hwnd()
        if not target:
            return {
                "supported": True,
                "matches": [],
                "error": "No visible Revit window found.",
            }
        tree = self._window_tree(target, max_depth=max(0, max_depth))
        matches = find_controls_in_tree(
            tree,
            text=text,
            class_name=class_name,
            limit=max(0, limit),
            exact=exact,
        )
        return {
            "success": True,
            "supported": True,
            "hwnd": target,
            "query": {
                "text": text,
                "class_name": class_name,
                "max_depth": max_depth,
                "limit": limit,
                "exact": exact,
            },
            "count": len(matches),
            "ambiguous": len(matches) > 1,
            "matches": matches,
        }

    def screenshot(self, output: Path, hwnd: int | None = None) -> dict:
        if not self.supported:
            return {
                "supported": False,
                "success": False,
                "error": "Windows screenshot capture is only available on win32.",
            }

        target = hwnd or self._default_target_hwnd()
        if not target:
            return {
                "supported": True,
                "success": False,
                "error": "No visible Revit window found.",
            }
        return self._capture_window_bmp(target, output)

    def _top_level_windows(self) -> list[WindowInfo]:
        ctypes = self.ctypes
        wintypes = self.wintypes
        handles: list[int] = []

        @self._EnumWindowsProc
        def callback(hwnd, _lparam):
            handles.append(int(hwnd))
            return True

        self.user32.EnumWindows(callback, 0)
        return [self._window_info(hwnd) for hwnd in handles]

    def _revit_processes(self) -> list[ProcessInfo]:
        ctypes = self.ctypes
        wintypes = self.wintypes
        ULONG_PTR = ctypes.c_ulonglong if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_ulong

        class PROCESSENTRY32W(ctypes.Structure):
            _fields_ = [
                ("dwSize", wintypes.DWORD),
                ("cntUsage", wintypes.DWORD),
                ("th32ProcessID", wintypes.DWORD),
                ("th32DefaultHeapID", ULONG_PTR),
                ("th32ModuleID", wintypes.DWORD),
                ("cntThreads", wintypes.DWORD),
                ("th32ParentProcessID", wintypes.DWORD),
                ("pcPriClassBase", ctypes.c_long),
                ("dwFlags", wintypes.DWORD),
                ("szExeFile", wintypes.WCHAR * 260),
            ]

        self.kernel32.Process32FirstW.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(PROCESSENTRY32W),
        ]
        self.kernel32.Process32FirstW.restype = wintypes.BOOL
        self.kernel32.Process32NextW.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(PROCESSENTRY32W),
        ]
        self.kernel32.Process32NextW.restype = wintypes.BOOL

        TH32CS_SNAPPROCESS = 0x00000002
        snapshot = self.kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
        if int(snapshot) == -1:
            return []
        try:
            entry = PROCESSENTRY32W()
            entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
            processes: list[ProcessInfo] = []
            ok = self.kernel32.Process32FirstW(snapshot, ctypes.byref(entry))
            while ok:
                name = entry.szExeFile
                if "revit" in name.lower():
                    pid = int(entry.th32ProcessID)
                    path = self._process_path(pid)
                    processes.append(
                        ProcessInfo(
                            pid=pid,
                            process_name=name,
                            process_path=path,
                            revit_version=self._revit_version(name, path),
                        )
                    )
                ok = self.kernel32.Process32NextW(snapshot, ctypes.byref(entry))
            return processes
        finally:
            self.kernel32.CloseHandle(snapshot)

    def _window_info(self, hwnd: int) -> WindowInfo:
        title = self._window_text(hwnd)
        class_name = self._class_name(hwnd)
        rect = self._rect(hwnd)
        visible = bool(self.user32.IsWindowVisible(hwnd))
        enabled = bool(self.user32.IsWindowEnabled(hwnd))
        foreground = hwnd == self._hwnd_value(self.user32.GetForegroundWindow())
        owner_hwnd = self._hwnd_value(self.user32.GetWindow(hwnd, 4))  # GW_OWNER
        pid = self._pid(hwnd)
        process_path = self._process_path(pid)
        process_name = Path(process_path).name if process_path else self._process_name(pid)
        haystack = " ".join([title, class_name, process_path, process_name]).lower()
        is_revit = "revit" in haystack
        class_lower = class_name.lower()
        is_dialog_like = class_name == "#32770" or owner_hwnd != 0 or "dialog" in class_lower
        return WindowInfo(
            hwnd=hwnd,
            pid=pid,
            title=title,
            class_name=class_name,
            rect=rect,
            visible=visible,
            enabled=enabled,
            foreground=foreground,
            owner_hwnd=owner_hwnd,
            process_path=process_path,
            process_name=process_name,
            revit_version=self._revit_version(title, process_path),
            is_revit_related=is_revit and visible,
            is_dialog_like=is_dialog_like,
            is_hung=self._is_hung(hwnd),
        )

    def _window_text(self, hwnd: int) -> str:
        length = self.user32.GetWindowTextLengthW(hwnd)
        buffer = self.ctypes.create_unicode_buffer(length + 1)
        self.user32.GetWindowTextW(hwnd, buffer, length + 1)
        return buffer.value

    def _class_name(self, hwnd: int) -> str:
        buffer = self.ctypes.create_unicode_buffer(256)
        self.user32.GetClassNameW(hwnd, buffer, 256)
        return buffer.value

    def _rect(self, hwnd: int) -> Rect:
        rect = self.wintypes.RECT()
        self.user32.GetWindowRect(hwnd, self.ctypes.byref(rect))
        return Rect(rect.left, rect.top, rect.right, rect.bottom)

    def _pid(self, hwnd: int) -> int:
        pid = self.wintypes.DWORD()
        self.user32.GetWindowThreadProcessId(hwnd, self.ctypes.byref(pid))
        return int(pid.value)

    @staticmethod
    def _hwnd_value(hwnd: object) -> int:
        return int(hwnd) if hwnd is not None else 0

    def _process_path(self, pid: int) -> str:
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        handle = self.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return ""
        try:
            size = self.wintypes.DWORD(32768)
            buffer = self.ctypes.create_unicode_buffer(size.value)
            ok = self.kernel32.QueryFullProcessImageNameW(
                handle, 0, buffer, self.ctypes.byref(size)
            )
            return buffer.value if ok else ""
        finally:
            self.kernel32.CloseHandle(handle)

    def _process_name(self, pid: int) -> str:
        if pid <= 0:
            return ""

        ctypes = self.ctypes
        wintypes = self.wintypes
        ULONG_PTR = ctypes.c_ulonglong if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_ulong

        class PROCESSENTRY32W(ctypes.Structure):
            _fields_ = [
                ("dwSize", wintypes.DWORD),
                ("cntUsage", wintypes.DWORD),
                ("th32ProcessID", wintypes.DWORD),
                ("th32DefaultHeapID", ULONG_PTR),
                ("th32ModuleID", wintypes.DWORD),
                ("cntThreads", wintypes.DWORD),
                ("th32ParentProcessID", wintypes.DWORD),
                ("pcPriClassBase", ctypes.c_long),
                ("dwFlags", wintypes.DWORD),
                ("szExeFile", wintypes.WCHAR * 260),
            ]

        self.kernel32.Process32FirstW.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(PROCESSENTRY32W),
        ]
        self.kernel32.Process32FirstW.restype = wintypes.BOOL
        self.kernel32.Process32NextW.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(PROCESSENTRY32W),
        ]
        self.kernel32.Process32NextW.restype = wintypes.BOOL

        TH32CS_SNAPPROCESS = 0x00000002
        snapshot = self.kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
        if int(snapshot) == -1:
            return ""
        try:
            entry = PROCESSENTRY32W()
            entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
            ok = self.kernel32.Process32FirstW(snapshot, ctypes.byref(entry))
            while ok:
                if int(entry.th32ProcessID) == pid:
                    return entry.szExeFile
                ok = self.kernel32.Process32NextW(snapshot, ctypes.byref(entry))
            return ""
        finally:
            self.kernel32.CloseHandle(snapshot)

    def _is_hung(self, hwnd: int) -> bool:
        try:
            return bool(self.user32.IsHungAppWindow(hwnd))
        except Exception:
            return False

    def _revit_version(self, title: str, process_path: str) -> str | None:
        text = f"{title} {process_path}"
        match = re.search(r"(?:Autodesk\s+)?Revit[^\d]*(20\d{2})", text, re.I)
        return match.group(1) if match else None

    def _choose_main_window(self, windows: Iterable[WindowInfo]) -> WindowInfo | None:
        candidates = [
            w
            for w in windows
            if w.visible and not w.is_dialog_like and (w.rect.width * w.rect.height) > 0
        ]
        if not candidates:
            return None
        foreground = [w for w in candidates if w.foreground]
        return (foreground or sorted(candidates, key=lambda w: w.rect.width * w.rect.height, reverse=True))[0]

    def _dialog_windows(self, windows: list[WindowInfo]) -> list[WindowInfo]:
        revit_pids = {w.pid for w in windows if w.is_revit_related}
        main = self._choose_main_window(windows)
        dialogs: list[WindowInfo] = []
        for window in windows:
            if not (window.visible and window.pid in revit_pids and window.is_dialog_like):
                continue
            if self._is_background_monitor_window(window):
                continue
            extracted = self._extract_dialog_content(window.hwnd)
            has_content = bool(
                window.title
                or extracted.get("dialog_text")
                or extracted.get("buttons")
                or extracted.get("controls")
            )
            owned_by_main = bool(main and window.owner_hwnd == main.hwnd)
            contentless_zero_area = not has_content and (
                window.rect.width <= 0 or window.rect.height <= 0
            )
            contentless_background_shell = (
                not has_content
                and owned_by_main
                and not window.foreground
                and bool(main and main.enabled)
            )
            if contentless_zero_area or contentless_background_shell:
                continue
            if has_content or owned_by_main:
                dialogs.append(window)
        return dialogs

    def _is_background_monitor_window(self, window: WindowInfo) -> bool:
        if window.class_name.lower() == "tooltips_class32":
            return True
        if window.class_name.startswith("WindowsForms10.Window") and window.title.endswith("Monitor"):
            return True
        return bool(re.fullmatch(r"[0-9a-f-]{36}Monitor", window.title, re.I))

    def _default_target_hwnd(self) -> int | None:
        windows = [w for w in self._top_level_windows() if w.is_revit_related]
        dialogs = self._dialog_windows(windows)
        if dialogs:
            foreground_dialog = [w for w in dialogs if w.foreground]
            return (foreground_dialog or dialogs)[0].hwnd
        main = self._choose_main_window(windows)
        return main.hwnd if main else None

    def _child_hwnds(self, hwnd: int) -> list[int]:
        children: list[int] = []
        child = self._hwnd_value(self.user32.GetWindow(hwnd, 5))  # GW_CHILD
        seen: set[int] = set()
        while child and child not in seen:
            seen.add(child)
            children.append(child)
            child = self._hwnd_value(self.user32.GetWindow(child, 2))  # GW_HWNDNEXT
        return children

    def _window_tree(self, hwnd: int, max_depth: int, depth: int = 0) -> dict:
        info = self._window_info(hwnd)
        node = {
            "hwnd": info.hwnd,
            "title": info.title,
            "class_name": info.class_name,
            "enabled": info.enabled,
            "visible": info.visible,
            "rect": info.rect.to_dict(),
            "children": [],
        }
        if depth >= max_depth:
            return node
        node["children"] = [
            self._window_tree(child, max_depth=max_depth, depth=depth + 1)
            for child in self._child_hwnds(hwnd)
            if self.user32.IsWindowVisible(child)
        ]
        return node

    def _flat_children(self, hwnd: int) -> list[WindowInfo]:
        result: list[WindowInfo] = []

        def visit(parent: int) -> None:
            for child in self._child_hwnds(parent):
                info = self._window_info(child)
                result.append(info)
                visit(child)

        visit(hwnd)
        return result

    def _extract_dialog_content(self, hwnd: int) -> dict:
        texts: list[str] = []
        buttons: list[str] = []
        controls: list[dict] = []
        for child in self._flat_children(hwnd):
            title = child.title.strip()
            class_name = child.class_name.lower()
            if title:
                controls.append(
                    {
                        "hwnd": child.hwnd,
                        "title": title,
                        "class_name": child.class_name,
                        "enabled": child.enabled,
                    }
                )
            if title and ("static" in class_name or "text" in class_name):
                texts.append(title)
            if title and ("button" in class_name or child.class_name == "Button"):
                buttons.append(title)
        return {
            "dialog_text": "\n".join(dict.fromkeys(texts)),
            "buttons": list(dict.fromkeys(buttons)),
            "controls": controls,
        }

    def _capture_window_bmp(self, hwnd: int, output: Path) -> dict:
        ctypes = self.ctypes
        rect = self._rect(hwnd)
        width = rect.width
        height = rect.height
        if width <= 0 or height <= 0:
            return {"supported": True, "success": False, "error": "Window has no area."}

        hdc_window = self.user32.GetWindowDC(hwnd)
        hdc_mem = self.gdi32.CreateCompatibleDC(hdc_window)
        bitmap = self.gdi32.CreateCompatibleBitmap(hdc_window, width, height)
        old_obj = self.gdi32.SelectObject(hdc_mem, bitmap)
        SRCCOPY = 0x00CC0020
        CAPTUREBLT = 0x40000000
        copied = self.gdi32.BitBlt(
            hdc_mem,
            0,
            0,
            width,
            height,
            hdc_window,
            0,
            0,
            SRCCOPY | CAPTUREBLT,
        )
        if not copied:
            self.gdi32.SelectObject(hdc_mem, old_obj)
            self.gdi32.DeleteObject(bitmap)
            self.gdi32.DeleteDC(hdc_mem)
            self.user32.ReleaseDC(hwnd, hdc_window)
            return {"supported": True, "success": False, "error": "BitBlt failed."}

        class BITMAPINFOHEADER(ctypes.Structure):
            _fields_ = [
                ("biSize", ctypes.c_uint32),
                ("biWidth", ctypes.c_int32),
                ("biHeight", ctypes.c_int32),
                ("biPlanes", ctypes.c_uint16),
                ("biBitCount", ctypes.c_uint16),
                ("biCompression", ctypes.c_uint32),
                ("biSizeImage", ctypes.c_uint32),
                ("biXPelsPerMeter", ctypes.c_int32),
                ("biYPelsPerMeter", ctypes.c_int32),
                ("biClrUsed", ctypes.c_uint32),
                ("biClrImportant", ctypes.c_uint32),
            ]

        class BITMAPINFO(ctypes.Structure):
            _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", ctypes.c_uint32 * 3)]

        stride = ((width * 3 + 3) // 4) * 4
        image_size = stride * height
        buffer = ctypes.create_string_buffer(image_size)
        info = BITMAPINFO()
        info.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        info.bmiHeader.biWidth = width
        info.bmiHeader.biHeight = height
        info.bmiHeader.biPlanes = 1
        info.bmiHeader.biBitCount = 24
        info.bmiHeader.biCompression = 0
        info.bmiHeader.biSizeImage = image_size

        rows = self.gdi32.GetDIBits(
            hdc_mem,
            bitmap,
            0,
            height,
            buffer,
            ctypes.byref(info),
            0,
        )
        self.gdi32.SelectObject(hdc_mem, old_obj)
        self.gdi32.DeleteObject(bitmap)
        self.gdi32.DeleteDC(hdc_mem)
        self.user32.ReleaseDC(hwnd, hdc_window)

        if rows == 0:
            return {"supported": True, "success": False, "error": "GetDIBits failed."}

        output.parent.mkdir(parents=True, exist_ok=True)
        file_size = 14 + 40 + image_size
        bmp_header = b"BM" + struct.pack("<IHHI", file_size, 0, 0, 54)
        dib_header = struct.pack(
            "<IiiHHIIiiII",
            40,
            width,
            height,
            1,
            24,
            0,
            image_size,
            0,
            0,
            0,
            0,
        )
        output.write_bytes(bmp_header + dib_header + buffer.raw)
        return {
            "supported": True,
            "success": True,
            "path": str(output),
            "format": "bmp",
            "hwnd": hwnd,
            "rect": rect.to_dict(),
        }


def _optional_import_available(module_name: str) -> bool:
    try:
        __import__(module_name)
        return True
    except Exception:
        return False


def find_controls_in_tree(
    tree: dict | None,
    *,
    text: str = "",
    class_name: str = "",
    limit: int = 50,
    exact: bool = False,
) -> list[dict]:
    """Find controls in an exported Win32 tree by visible text and/or class."""

    if not tree or limit == 0:
        return []
    text_query = _norm(text)
    class_query = _norm(class_name)
    matches: list[dict] = []

    def visit(node: dict, depth: int, path: list[str]) -> None:
        if len(matches) >= limit:
            return
        title = str(node.get("title") or "")
        node_class = str(node.get("class_name") or "")
        title_norm = _norm(title)
        class_norm = _norm(node_class)
        next_path = [*path, title or node_class or str(node.get("hwnd") or "")]
        text_ok = _matches(title_norm, text_query, exact) if text_query else True
        class_ok = _matches(class_norm, class_query, exact) if class_query else True
        if text_ok and class_ok and (text_query or class_query):
            matches.append(
                {
                    "hwnd": node.get("hwnd"),
                    "title": title,
                    "class_name": node_class,
                    "enabled": node.get("enabled"),
                    "visible": node.get("visible"),
                    "rect": node.get("rect"),
                    "depth": depth,
                    "path": " > ".join(part for part in next_path if part),
                }
            )
        for child in node.get("children") or []:
            if isinstance(child, dict):
                visit(child, depth + 1, next_path)

    visit(tree, 0, [])
    return matches


def _norm(value: object) -> str:
    return str(value or "").strip().lower().replace("&", "")


def _matches(value: str, query: str, exact: bool) -> bool:
    return value == query if exact else query in value
