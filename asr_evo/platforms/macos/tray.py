from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from threading import current_thread, main_thread

from asr_evo.postprocess.styles import StyleDefinition


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
        styles: list[StyleDefinition],
        selected_style_id: str,
        on_toggle: Callable[[], None],
        on_select_style: Callable[[str], None],
        on_reload_styles: Callable[[], None],
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
        self.on_select_style = on_select_style
        self.on_reload_styles = on_reload_styles
        self._style_targets: list[_MenuTargetItem] = []

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
        self.style_menu_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Style", None, ""
        )
        self.style_menu = NSMenu.alloc().initWithTitle_("Style")
        self.style_menu_item.setSubmenu_(self.style_menu)
        self.reload_styles_item = _MenuTargetItem.create(
            title="Reload Prompt Styles",
            action=on_reload_styles,
        )
        self.quit_item = _MenuTargetItem.create(
            title="Quit ASR-EVO",
            action=on_quit,
        )

        self.menu.addItem_(self.state_item)
        self.menu.addItem_(self.hotkey_item)
        self.menu.addItem_(NSMenuItem.separatorItem())
        self.menu.addItem_(self.toggle_item.item)
        self.menu.addItem_(self.style_menu_item)
        self.menu.addItem_(self.reload_styles_item.item)
        self.menu.addItem_(NSMenuItem.separatorItem())
        self.menu.addItem_(self.quit_item.item)
        self.status_item.setMenu_(self.menu)
        self.set_styles(styles, selected_style_id)

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

    def set_styles(self, styles: list[StyleDefinition], selected_style_id: str) -> None:
        if current_thread() is not main_thread():
            from PyObjCTools import AppHelper

            AppHelper.callAfter(self.set_styles, styles, selected_style_id)
            return
        self.style_menu.removeAllItems()
        self._style_targets = []
        for group_index, group in enumerate(_group_styles(styles)):
            if group_index > 0:
                from AppKit import NSMenuItem

                self.style_menu.addItem_(NSMenuItem.separatorItem())
            for style in group.styles:
                target_item = _MenuTargetItem.create_with_arg(
                    title=style.label,
                    action=self.on_select_style,
                    arg=style.id,
                )
                target_item.item.setState_(1 if style.id == selected_style_id else 0)
                self.style_menu.addItem_(target_item.item)
                self._style_targets.append(target_item)


@dataclass(frozen=True)
class _StyleGroup:
    styles: list[StyleDefinition]


def _group_styles(styles: list[StyleDefinition]) -> list[_StyleGroup]:
    built_in = [style for style in styles if style.source == "built-in"]
    custom = [style for style in styles if style.source != "built-in"]
    groups = []
    if built_in:
        groups.append(_StyleGroup(built_in))
    if custom:
        groups.append(_StyleGroup(custom))
    return groups


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

    @classmethod
    def create_with_arg(cls, *, title: str, action: Callable[[str], None], arg: str):
        from AppKit import NSMenuItem

        target = _MenuActionTarget.alloc().initWithCallback_(lambda: action(arg))
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
