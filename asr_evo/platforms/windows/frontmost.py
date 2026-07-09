from __future__ import annotations

from pathlib import Path

from asr_evo.core.ports import AppContext


class WindowsFrontmostAppProvider:
    def current_app(self) -> AppContext:
        try:
            import win32api
            import win32con
            import win32gui
            import win32process
        except ImportError:
            return AppContext()

        hwnd = win32gui.GetForegroundWindow()
        if not hwnd:
            return AppContext()

        title = str(win32gui.GetWindowText(hwnd) or "")
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        exe_path = ""
        handle = None
        try:
            access = win32con.PROCESS_QUERY_LIMITED_INFORMATION | win32con.PROCESS_VM_READ
            handle = win32api.OpenProcess(access, False, pid)
            exe_path = str(win32process.GetModuleFileNameEx(handle, 0) or "")
        except Exception:
            exe_path = ""
        finally:
            if handle is not None:
                win32api.CloseHandle(handle)

        app_name = Path(exe_path).stem if exe_path else ""
        bundle_id = str(Path(exe_path)).lower() if exe_path else ""
        return AppContext(
            bundle_id=bundle_id,
            app_name=app_name,
            window_title=title,
            process_id=int(pid),
        )
