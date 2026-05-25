from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from threading import current_thread, main_thread

from asr_evo.config import StatusConfig
from asr_evo.postprocess.styles import StyleDefinition
from asr_evo.storage.history import AppStats


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
        status_config: StatusConfig,
        styles: list[StyleDefinition],
        selected_style_id: str,
        on_select_style: Callable[[str], None],
        on_reveal_prompts: Callable[[], None],
        on_reload_config: Callable[[], None],
        on_open_config: Callable[[], None],
        on_clear_app_style: Callable[[], None],
        on_refresh_app_binding: Callable[[], None],
        on_refresh_stats: Callable[[], None],
        on_copy_history_raw: Callable[[str], None],
        on_copy_history_final: Callable[[str], None],
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
        self.status_config = status_config
        self.on_select_style = on_select_style
        self.on_refresh_app_binding = on_refresh_app_binding
        self.on_refresh_stats = on_refresh_stats
        self.on_copy_history_raw = on_copy_history_raw
        self.on_copy_history_final = on_copy_history_final
        self._style_targets: list[_MenuTargetItem] = []
        self._history_targets: list[_MenuTargetItem] = []
        self._styles = styles
        self._selected_style_id = selected_style_id
        self._app_binding_title = "当前应用绑定：未检测"

        self.menu = NSMenu.alloc().init()
        self.menu.setDelegate_(self)
        self.hotkey_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            f"快捷键：{hotkey_label}", None, ""
        )
        self.reveal_prompts_item = _MenuTargetItem.create(
            title="打开提示词文件夹",
            action=on_reveal_prompts,
        )
        self.clear_app_style_item = _MenuTargetItem.create(
            title="清除当前应用绑定",
            action=on_clear_app_style,
        )
        self.reload_config_item = _MenuTargetItem.create(
            title="重新加载配置",
            action=on_reload_config,
        )
        self.open_config_item = _MenuTargetItem.create(
            title="打开配置文件",
            action=on_open_config,
        )
        self.stats_menu_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "听写统计", None, ""
        )
        self.stats_menu = NSMenu.alloc().initWithTitle_("听写统计")
        self.stats_menu_item.setSubmenu_(self.stats_menu)
        self.history_menu_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "历史记录", None, ""
        )
        self.history_menu = NSMenu.alloc().initWithTitle_("历史记录")
        self.history_menu_item.setSubmenu_(self.history_menu)
        self.prompt_menu_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "润色风格与提示词", None, ""
        )
        self.prompt_menu = NSMenu.alloc().initWithTitle_("润色风格与提示词")
        self.prompt_menu.setDelegate_(self)
        self.prompt_menu_item.setSubmenu_(self.prompt_menu)
        self.refresh_stats_item = _MenuTargetItem.create(
            title="刷新统计",
            action=on_refresh_stats,
        )
        self.stats_menu.addItem_(self.refresh_stats_item.item)
        self.quit_item = _MenuTargetItem.create(
            title="退出 ASR-EVO",
            action=on_quit,
        )

        self.menu.addItem_(self.hotkey_item)
        self.menu.addItem_(self.prompt_menu_item)
        self.menu.addItem_(NSMenuItem.separatorItem())
        self.menu.addItem_(self.stats_menu_item)
        self.menu.addItem_(self.history_menu_item)
        self.menu.addItem_(self.reload_config_item.item)
        self.menu.addItem_(self.open_config_item.item)
        self.menu.addItem_(NSMenuItem.separatorItem())
        self.menu.addItem_(self.quit_item.item)
        self.status_item.setMenu_(self.menu)
        self.set_styles(styles, selected_style_id)

    def set_state(self, state: str, detail: str = "") -> None:
        if current_thread() is not main_thread():
            from PyObjCTools import AppHelper

            AppHelper.callAfter(self.set_state, state, detail)
            return
        title_map = _status_icon_map(self.status_config)
        text_map = _status_text_map(self.status_config)
        self.button.setTitle_(title_map.get(state, "ASR"))
        status_text = text_map.get(state, state)
        if detail:
            status_text = f"{status_text}：{detail}"
        self.button.setToolTip_(status_text)

    def menuWillOpen_(self, menu) -> None:
        self._refresh_menu_if_needed(menu)

    def menuNeedsUpdate_(self, menu) -> None:
        self._refresh_menu_if_needed(menu)

    def _refresh_menu_if_needed(self, menu) -> None:
        if menu in (self.menu, self.prompt_menu):
            self.on_refresh_app_binding()

    def set_styles(self, styles: list[StyleDefinition], selected_style_id: str) -> None:
        if current_thread() is not main_thread():
            from PyObjCTools import AppHelper

            AppHelper.callAfter(self.set_styles, styles, selected_style_id)
            return
        from AppKit import NSMenuItem

        self._styles = styles
        self._selected_style_id = selected_style_id
        self.prompt_menu.removeAllItems()
        self._style_targets = []
        _add_style_tree_to_menu(
            menu=self.prompt_menu,
            node=_build_style_tree(styles),
            selected_style_id=selected_style_id,
            action=self.on_select_style,
            targets=self._style_targets,
        )
        self.prompt_menu.addItem_(NSMenuItem.separatorItem())
        binding_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            self._app_binding_title, None, ""
        )
        binding_item.setEnabled_(False)
        self.prompt_menu.addItem_(binding_item)
        self.prompt_menu.addItem_(self.clear_app_style_item.item)
        self.prompt_menu.addItem_(NSMenuItem.separatorItem())
        self.prompt_menu.addItem_(self.reveal_prompts_item.item)

    def set_app_binding_summary(self, title: str) -> None:
        self._app_binding_title = title
        self.set_styles(self._styles, self._selected_style_id)

    def set_status_config(self, status_config: StatusConfig) -> None:
        self.status_config = status_config

    def set_stats(self, *, totals: dict[str, int | float], app_stats: list[AppStats]) -> None:
        if current_thread() is not main_thread():
            from PyObjCTools import AppHelper

            AppHelper.callAfter(lambda: self.set_stats(totals=totals, app_stats=app_stats))
            return
        from AppKit import NSMenuItem

        self.stats_menu.removeAllItems()
        self.stats_menu.addItem_(self.refresh_stats_item.item)
        self.stats_menu.addItem_(NSMenuItem.separatorItem())
        rows = [
            f"听写次数：{totals.get('count', 0)}",
            f"累计字数：{totals.get('total_chars', 0)}",
            f"累计音频：{float(totals.get('total_audio_seconds', 0)):.1f} 秒",
        ]
        for title in rows:
            item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(title, None, "")
            item.setEnabled_(False)
            self.stats_menu.addItem_(item)
        if app_stats:
            self.stats_menu.addItem_(NSMenuItem.separatorItem())
        for stat in app_stats[:8]:
            item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
                f"{stat.app_name}: {stat.count} 次，{stat.total_chars} 字",
                None,
                "",
            )
            item.setEnabled_(False)
            self.stats_menu.addItem_(item)

    def set_history_records(self, records: list[dict]) -> None:
        if current_thread() is not main_thread():
            from PyObjCTools import AppHelper

            AppHelper.callAfter(lambda: self.set_history_records(records))
            return
        from AppKit import NSMenu, NSMenuItem

        self.history_menu.removeAllItems()
        self._history_targets = []
        if not records:
            item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("暂无历史记录", None, "")
            item.setEnabled_(False)
            self.history_menu.addItem_(item)
            return
        for record in records[:10]:
            title = _history_title(record)
            item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(title, None, "")
            submenu = NSMenu.alloc().initWithTitle_(title)
            raw_preview = _readonly_preview("原始", record.get("raw_text", ""))
            final_preview = _readonly_preview("润色", record.get("final_text", ""))
            submenu.addItem_(raw_preview)
            submenu.addItem_(final_preview)
            submenu.addItem_(NSMenuItem.separatorItem())
            raw = _MenuTargetItem.create_with_arg(
                title="复制原始转写",
                action=self.on_copy_history_raw,
                arg=record["id"],
            )
            final = _MenuTargetItem.create_with_arg(
                title="复制润色结果",
                action=self.on_copy_history_final,
                arg=record["id"],
            )
            submenu.addItem_(raw.item)
            submenu.addItem_(final.item)
            item.setSubmenu_(submenu)
            self.history_menu.addItem_(item)
            self._history_targets.extend([raw, final])

@dataclass
class _StyleMenuNode:
    name: str
    styles: list[StyleDefinition]
    children: dict[str, "_StyleMenuNode"]


def _build_style_tree(styles: list[StyleDefinition]) -> _StyleMenuNode:
    root = _StyleMenuNode(name="", styles=[], children={})
    for style in styles:
        node = root
        for category in style.category:
            node = node.children.setdefault(
                category,
                _StyleMenuNode(name=category, styles=[], children={}),
            )
        node.styles.append(style)
    return root


def _add_style_tree_to_menu(
    *,
    menu,
    node: _StyleMenuNode,
    selected_style_id: str,
    action: Callable[[str], None],
    targets: list["_MenuTargetItem"],
) -> None:
    from AppKit import NSMenu, NSMenuItem

    for style in sorted(node.styles, key=lambda item: item.label.lower()):
        _add_style_item(
            menu=menu,
            style=style,
            selected_style_id=selected_style_id,
            action=action,
            targets=targets,
        )
    if node.styles and node.children:
        menu.addItem_(NSMenuItem.separatorItem())
    for child in sorted(node.children.values(), key=lambda item: item.name.lower()):
        child_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(child.name, None, "")
        child_menu = NSMenu.alloc().initWithTitle_(child.name)
        _add_style_tree_to_menu(
            menu=child_menu,
            node=child,
            selected_style_id=selected_style_id,
            action=action,
            targets=targets,
        )
        child_item.setSubmenu_(child_menu)
        menu.addItem_(child_item)


def _add_style_item(
    *,
    menu,
    style: StyleDefinition,
    selected_style_id: str,
    action: Callable[[str], None],
    targets: list["_MenuTargetItem"],
) -> None:
    target_item = _MenuTargetItem.create_with_arg(
        title=style.label,
        action=action,
        arg=style.id,
    )
    target_item.item.setState_(1 if style.id == selected_style_id else 0)
    menu.addItem_(target_item.item)
    targets.append(target_item)


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
    def create_with_arg(cls, *, title: str, action: Callable, arg):
        from AppKit import NSMenuItem

        target = _MenuActionTarget.alloc().initWithCallback_(lambda: action(arg))
        item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(title, "perform:", "")
        item.setTarget_(target)
        return cls(item, target)


def _history_title(record: dict) -> str:
    text = " ".join(str(record.get("final_text", "")).split())
    if not text and record.get("raw_text"):
        text = "转写失败待重试"
    text = _ellipsize(text, 24)
    app = record.get("app_name") or record.get("bundle_id") or "未知应用"
    return f"{app}: {text or '（空）'}"


def _readonly_preview(label: str, value: str) -> object:
    from AppKit import NSMenuItem

    text = _ellipsize(" ".join(str(value).split()), 42) or "（空）"
    item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(f"{label}：{text}", None, "")
    item.setEnabled_(False)
    return item


def _ellipsize(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + "..."


def _status_icon_map(config: StatusConfig) -> dict[str, str]:
    return {
        "idle": config.idle_icon,
        "recording": config.recording_icon,
        "transcribing": config.transcribing_icon,
        "polishing": config.polishing_icon,
        "inserting": config.inserting_icon,
        "error": config.error_icon,
    }


def _status_text_map(config: StatusConfig) -> dict[str, str]:
    return {
        "idle": config.idle_text,
        "recording": config.recording_text,
        "transcribing": config.transcribing_text,
        "polishing": config.polishing_text,
        "inserting": config.inserting_text,
        "error": config.error_text,
    }


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
