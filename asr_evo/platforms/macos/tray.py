from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from threading import current_thread, main_thread
from typing import Protocol

from asr_evo.config import StatusConfig
from asr_evo.core.errors import ErrorFeedback
from asr_evo.postprocess.styles import StyleDefinition
from asr_evo.storage.history import AppStats


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
        on_refresh_input_devices: Callable[[], None],
        on_select_input_device: Callable[[str], None],
        on_clear_app_style: Callable[[], None],
        on_refresh_app_binding: Callable[[], None],
        on_refresh_stats: Callable[[], None],
        on_copy_history_raw: Callable[[str], None],
        on_copy_history_final: Callable[[str], None],
        on_copy_error: Callable[[], None],
        on_clear_error: Callable[[], None],
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
        self.on_refresh_input_devices = on_refresh_input_devices
        self.on_select_input_device = on_select_input_device
        self.on_refresh_app_binding = on_refresh_app_binding
        self.on_refresh_stats = on_refresh_stats
        self.on_copy_history_raw = on_copy_history_raw
        self.on_copy_history_final = on_copy_history_final
        self.on_copy_error = on_copy_error
        self.on_clear_error = on_clear_error
        self._style_targets: list[_MenuTargetItem] = []
        self._input_device_targets: list[_MenuTargetItem] = []
        self._history_targets: list[_MenuTargetItem] = []
        self._error_targets: list[_MenuTargetItem] = []
        self._styles = styles
        self._selected_style_id = selected_style_id
        self._input_devices: list[InputDeviceMenuItem] = []
        self._selected_input_device_id = ""
        self._app_binding_title = "当前应用绑定：未检测"
        self._error_feedback: ErrorFeedback | None = None

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
        self.input_device_menu_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "输入来源", None, ""
        )
        self.input_device_menu = NSMenu.alloc().initWithTitle_("输入来源")
        self.input_device_menu.setDelegate_(self)
        self.input_device_menu_item.setSubmenu_(self.input_device_menu)
        self.error_menu_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "当前错误", None, ""
        )
        self.error_menu = NSMenu.alloc().initWithTitle_("当前错误")
        self.error_menu_item.setSubmenu_(self.error_menu)
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
        self.menu.addItem_(self.error_menu_item)
        self.menu.addItem_(self.input_device_menu_item)
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
        self.set_error_feedback(None)

    def set_state(self, state: str, detail: str = "") -> None:
        if _call_on_main_thread(self.set_state, state, detail):
            return
        title_map = _status_icon_map(self.status_config)
        text_map = _status_text_map(self.status_config)
        self.button.setTitle_(title_map.get(state, "ASR"))
        status_text = text_map.get(state, state)
        if detail:
            status_text = f"{status_text}：{detail}"
        self.button.setToolTip_(status_text)

    def set_error_feedback(self, feedback: ErrorFeedback | None) -> None:
        if _call_on_main_thread(self.set_error_feedback, feedback):
            return
        from AppKit import NSMenuItem

        self._error_feedback = feedback
        self._error_targets = []
        self.error_menu.removeAllItems()
        if feedback is None:
            self.error_menu_item.setHidden_(True)
            return

        self.error_menu_item.setHidden_(False)
        self.error_menu_item.setTitle_(f"当前错误：{feedback.title}")
        for title in _error_feedback_lines(feedback):
            item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(title, None, "")
            item.setEnabled_(False)
            self.error_menu.addItem_(item)
        self.error_menu.addItem_(NSMenuItem.separatorItem())
        copy_item = _MenuTargetItem.create(title="复制错误详情", action=self.on_copy_error)
        clear_item = _MenuTargetItem.create(title="清除错误状态", action=self.on_clear_error)
        self.error_menu.addItem_(copy_item.item)
        self.error_menu.addItem_(clear_item.item)
        self._error_targets.extend([copy_item, clear_item])

    def menuWillOpen_(self, menu) -> None:
        self._refresh_menu_if_needed(menu)

    def menuNeedsUpdate_(self, menu) -> None:
        self._refresh_menu_if_needed(menu)

    def _refresh_menu_if_needed(self, menu) -> None:
        if menu in (self.menu, self.prompt_menu):
            self.on_refresh_app_binding()
        if menu in (self.menu, self.input_device_menu):
            self.on_refresh_input_devices()

    def set_styles(self, styles: list[StyleDefinition], selected_style_id: str) -> None:
        if _call_on_main_thread(self.set_styles, styles, selected_style_id):
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

    def set_input_devices(
        self,
        devices: list["InputDeviceMenuItem"],
        selected_device_id: str,
    ) -> None:
        if _call_on_main_thread(self.set_input_devices, devices, selected_device_id):
            return
        from AppKit import NSMenuItem

        self._input_devices = devices
        self._selected_input_device_id = selected_device_id
        self._input_device_targets = []
        self.input_device_menu.removeAllItems()
        self.input_device_menu_item.setTitle_(
            f"输入来源：{_selected_input_device_title(devices, selected_device_id)}"
        )
        if not devices:
            item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("未找到输入设备", None, "")
            item.setEnabled_(False)
            self.input_device_menu.addItem_(item)
            return
        _add_input_devices_to_menu(
            menu=self.input_device_menu,
            devices=devices,
            selected_device_id=selected_device_id,
            action=self.on_select_input_device,
            targets=self._input_device_targets,
        )

    def set_stats(self, *, totals: dict[str, int | float], app_stats: list[AppStats]) -> None:
        if _call_on_main_thread(self.set_stats, totals=totals, app_stats=app_stats):
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
        if _call_on_main_thread(self.set_history_records, records):
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


def _call_on_main_thread(callback: Callable, *args, **kwargs) -> bool:
    if current_thread() is main_thread():
        return False
    from PyObjCTools import AppHelper

    AppHelper.callAfter(callback, *args, **kwargs)
    return True


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


class InputDeviceMenuItem(Protocol):
    id: str
    label: str
    is_default: bool


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


def _add_input_devices_to_menu(
    *,
    menu,
    devices: list[InputDeviceMenuItem],
    selected_device_id: str,
    action: Callable[[str], None],
    targets: list["_MenuTargetItem"],
) -> None:
    from AppKit import NSMenuItem

    for index, device in enumerate(devices):
        target_item = _MenuTargetItem.create_with_arg(
            title=device.label,
            action=action,
            arg=device.id,
        )
        target_item.item.setState_(1 if device.id == selected_device_id else 0)
        menu.addItem_(target_item.item)
        targets.append(target_item)
        if device.is_default and index < len(devices) - 1:
            menu.addItem_(NSMenuItem.separatorItem())


def _selected_input_device_title(
    devices: list[InputDeviceMenuItem],
    selected_device_id: str,
) -> str:
    for device in devices:
        if device.id == selected_device_id:
            return _ellipsize(device.label, 24)
    if selected_device_id:
        return _ellipsize(f"设备 {selected_device_id}（不可用）", 24)
    return "系统默认输入"


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


def _error_feedback_lines(feedback: ErrorFeedback) -> list[str]:
    lines = [
        f"原因：{_ellipsize(feedback.detail, 42)}",
        f"建议：{_ellipsize(feedback.suggestion, 52)}",
    ]
    if feedback.raw_text_saved:
        lines.append("原始转写已保存到历史记录")
    if feedback.technical_detail and feedback.technical_detail != feedback.detail:
        lines.append(f"技术细节：{_ellipsize(feedback.technical_detail, 52)}")
    return lines


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
