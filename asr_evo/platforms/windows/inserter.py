from __future__ import annotations

import asyncio
import time

CLIPBOARD_RETRIES = 8
CLIPBOARD_RETRY_DELAY_SECONDS = 0.05


class WindowsTextInserter:
    def __init__(self, *, restore_delay_ms: int = 300) -> None:
        self.restore_delay_seconds = restore_delay_ms / 1000

    async def insert(self, text: str) -> None:
        await asyncio.to_thread(self._insert_via_clipboard_restore, text)

    def _insert_via_clipboard_restore(self, text: str) -> None:
        try:
            from pynput.keyboard import Controller, Key
        except ImportError as exc:
            raise RuntimeError("pynput is required for Windows text insertion") from exc

        old_text = _clipboard_get_text()
        _clipboard_set_text(text)
        time.sleep(CLIPBOARD_RETRY_DELAY_SECONDS)

        keyboard = Controller()
        with keyboard.pressed(Key.ctrl):
            keyboard.press("v")
            keyboard.release("v")

        time.sleep(self.restore_delay_seconds)
        if _clipboard_get_text() == text:
            _clipboard_set_text(old_text)


class WindowsClipboard:
    def copy_text(self, text: str) -> None:
        _clipboard_set_text(text)


def _clipboard_get_text() -> str:
    try:
        import win32clipboard
        import win32con
    except ImportError as exc:
        raise RuntimeError("pywin32 is required for Windows clipboard access") from exc

    def read() -> str:
        if not win32clipboard.IsClipboardFormatAvailable(win32con.CF_UNICODETEXT):
            return ""
        return str(win32clipboard.GetClipboardData(win32con.CF_UNICODETEXT) or "")

    return _with_open_clipboard(read)


def _clipboard_set_text(text: str) -> None:
    try:
        import win32clipboard
        import win32con
    except ImportError as exc:
        raise RuntimeError("pywin32 is required for Windows clipboard access") from exc

    def write() -> None:
        win32clipboard.EmptyClipboard()
        win32clipboard.SetClipboardData(win32con.CF_UNICODETEXT, text)

    _with_open_clipboard(write)


def _with_open_clipboard(callback):
    import win32clipboard

    last_error: Exception | None = None
    for _ in range(CLIPBOARD_RETRIES):
        try:
            win32clipboard.OpenClipboard()
            try:
                return callback()
            finally:
                win32clipboard.CloseClipboard()
        except Exception as exc:
            last_error = exc
            time.sleep(CLIPBOARD_RETRY_DELAY_SECONDS)
    assert last_error is not None
    raise RuntimeError("Windows clipboard is unavailable") from last_error
