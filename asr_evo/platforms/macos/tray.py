from __future__ import annotations

from collections.abc import Callable
from threading import current_thread, main_thread


class ConsoleTrayUI:
    """Small stand-in while the NSStatusItem runtime is being built."""

    def set_state(self, state: str, detail: str = "") -> None:
        suffix = f" {detail}" if detail else ""
        print(f"[asr-evo] {state}{suffix}")


class MacOSStatusTray:
    def __init__(
        self,
        *,
        hotkey_label: str,
        on_toggle: Callable[[], None],
        on_quit: Callable[[], None],
    ) -> None:
        from AppKit import (
            NSApplication,
            NSMenu,
            NSMenuItem,
            NSStatusBar,
            NSVariableStatusItemLength,
        )

        self.app = NSApplication.sharedApplication()
        self.status_item = NSStatusBar.systemStatusBar().statusItemWithLength_(
            NSVariableStatusItemLength
        )
        self.button = self.status_item.button()
        self.button.setTitle_("ASR")

        self.menu = NSMenu.alloc().init()
        self.state_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Idle", None, ""
        )
        self.hotkey_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            f"Hotkey: {hotkey_label}", None, ""
        )
        self.toggle_item = _MenuTargetItem.create(
            title="Start Dictation",
            action=on_toggle,
        )
        self.quit_item = _MenuTargetItem.create(
            title="Quit ASR-EVO",
            action=on_quit,
        )

        self.menu.addItem_(self.state_item)
        self.menu.addItem_(self.hotkey_item)
        self.menu.addItem_(NSMenuItem.separatorItem())
        self.menu.addItem_(self.toggle_item.item)
        self.menu.addItem_(NSMenuItem.separatorItem())
        self.menu.addItem_(self.quit_item.item)
        self.status_item.setMenu_(self.menu)

    def set_state(self, state: str, detail: str = "") -> None:
        if current_thread() is not main_thread():
            from PyObjCTools import AppHelper

            AppHelper.callAfter(self.set_state, state, detail)
            return
        title_map = {
            "idle": "ASR",
            "recording": "REC ASR",
            "transcribing": "... ASR",
            "polishing": "TXT ASR",
            "inserting": "INS ASR",
            "error": "! ASR",
        }
        text_map = {
            "idle": "Idle",
            "recording": "Recording... press hotkey again to stop",
            "transcribing": "Transcribing...",
            "polishing": "Polishing...",
            "inserting": "Inserting...",
            "error": "Error",
        }
        self.button.setTitle_(title_map.get(state, "ASR"))
        suffix = f": {detail}" if detail else ""
        self.state_item.setTitle_(f"{text_map.get(state, state)}{suffix}")
        self.toggle_item.item.setTitle_("Stop Recording" if state == "recording" else "Start Dictation")


class _MenuTargetItem:
    def __init__(self, item, target) -> None:
        self.item = item
        self.target = target

    @classmethod
    def create(cls, *, title: str, action: Callable[[], None]):
        from AppKit import NSMenuItem

        target = _MenuActionTarget.alloc().initWithCallback_(action)
        item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(title, "perform:", "")
        item.setTarget_(target)
        return cls(item, target)


try:
    from Foundation import NSObject
except ImportError:  # pragma: no cover - non-macOS import fallback
    NSObject = object


class _MenuActionTarget(NSObject):
    def initWithCallback_(self, callback):
        self = self.init()
        self.callback = callback
        return self

    def perform_(self, sender):
        self.callback()
