from __future__ import annotations

import asyncio
import time


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
    import tkinter as tk

    root = tk.Tk()
    root.withdraw()
    try:
        try:
            return str(root.clipboard_get())
        except tk.TclError:
            return ""
    finally:
        root.destroy()


def _clipboard_set_text(text: str) -> None:
    import tkinter as tk

    root = tk.Tk()
    root.withdraw()
    try:
        root.clipboard_clear()
        root.clipboard_append(text)
        root.update()
    finally:
        root.destroy()
