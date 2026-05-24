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
        on_toggle: Callable[[], None],
        on_select_style: Callable[[str], None],
        on_reload_styles: Callable[[], None],
        on_set_context_ttl: Callable[[int], None],
        on_set_context_items: Callable[[int], None],
        on_set_hotkey_preset: Callable[[str, str], None],
        on_new_prompt: Callable[[], None],
        on_delete_prompt: Callable[[], None],
        on_reveal_prompts: Callable[[], None],
        on_reload_config: Callable[[], None],
        on_open_config: Callable[[], None],
        on_bind_style_to_app: Callable[[], None],
        on_clear_app_style: Callable[[], None],
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
        self.on_reload_styles = on_reload_styles
        self.on_set_context_ttl = on_set_context_ttl
        self.on_set_context_items = on_set_context_items
        self.on_set_hotkey_preset = on_set_hotkey_preset
        self.on_refresh_stats = on_refresh_stats
        self.on_copy_history_raw = on_copy_history_raw
        self.on_copy_history_final = on_copy_history_final
        self._style_targets: list[_MenuTargetItem] = []
        self._setting_targets: list[_MenuTargetItem] = []
        self._history_targets: list[_MenuTargetItem] = []
        self._style_prompt_items = 0

        self.menu = NSMenu.alloc().init()
        self.state_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "空闲", None, ""
        )
        self.hotkey_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            f"快捷键：{hotkey_label}", None, ""
        )
        self.toggle_item = _MenuTargetItem.create(
            title="开始听写",
            action=on_toggle,
        )
        self.reload_styles_item = _MenuTargetItem.create(
            title="重新加载提示词",
            action=on_reload_styles,
        )
        self.new_prompt_item = _MenuTargetItem.create(
            title="新建提示词模板",
            action=on_new_prompt,
        )
        self.delete_prompt_item = _MenuTargetItem.create(
            title="删除当前自定义提示词",
            action=on_delete_prompt,
        )
        self.reveal_prompts_item = _MenuTargetItem.create(
            title="在 Finder 中打开提示词目录",
            action=on_reveal_prompts,
        )
        self.bind_style_item = _MenuTargetItem.create(
            title="将当前风格绑定到当前应用",
            action=on_bind_style_to_app,
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
        self.settings_reload_config_item = _MenuTargetItem.create(
            title="重新加载配置",
            action=on_reload_config,
        )
        self.settings_open_config_item = _MenuTargetItem.create(
            title="打开配置文件",
            action=on_open_config,
        )
        self.settings_menu_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "设置", None, ""
        )
        self.settings_menu = NSMenu.alloc().initWithTitle_("设置")
        self.settings_menu_item.setSubmenu_(self.settings_menu)
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

        self.menu.addItem_(self.state_item)
        self.menu.addItem_(self.hotkey_item)
        self.menu.addItem_(NSMenuItem.separatorItem())
        self.menu.addItem_(self.toggle_item.item)
        self.menu.addItem_(self.prompt_menu_item)
        self.menu.addItem_(NSMenuItem.separatorItem())
        self.menu.addItem_(self.settings_menu_item)
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
        suffix = f"：{detail}" if detail else ""
        self.state_item.setTitle_(f"{text_map.get(state, state)}{suffix}")
        self.toggle_item.item.setTitle_("停止录音" if state == "recording" else "开始听写")

    def set_styles(self, styles: list[StyleDefinition], selected_style_id: str) -> None:
        if current_thread() is not main_thread():
            from PyObjCTools import AppHelper

            AppHelper.callAfter(self.set_styles, styles, selected_style_id)
            return
        from AppKit import NSMenuItem

        self.prompt_menu.removeAllItems()
        self._style_targets = []
        for group_index, group in enumerate(_group_styles(styles)):
            if group_index > 0:
                self.prompt_menu.addItem_(NSMenuItem.separatorItem())
            for style in group.styles:
                target_item = _MenuTargetItem.create_with_arg(
                    title=style.label,
                    action=self.on_select_style,
                    arg=style.id,
                )
                target_item.item.setState_(1 if style.id == selected_style_id else 0)
                self.prompt_menu.addItem_(target_item.item)
                self._style_targets.append(target_item)
                if style.id == selected_style_id:
                    for chunk in _chunk_text(" ".join(style.prompt.split()), 38)[:6]:
                        preview_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
                            f"  {chunk}", None, ""
                        )
                        preview_item.setEnabled_(False)
                        self.prompt_menu.addItem_(preview_item)
        self.prompt_menu.addItem_(NSMenuItem.separatorItem())
        self.prompt_menu.addItem_(self.reload_styles_item.item)
        self.prompt_menu.addItem_(self.new_prompt_item.item)
        self.prompt_menu.addItem_(self.delete_prompt_item.item)
        self.prompt_menu.addItem_(NSMenuItem.separatorItem())
        self.prompt_menu.addItem_(self.bind_style_item.item)
        self.prompt_menu.addItem_(self.clear_app_style_item.item)
        self.prompt_menu.addItem_(self.reveal_prompts_item.item)

    def set_status_config(self, status_config: StatusConfig) -> None:
        self.status_config = status_config

    def set_settings_summary(
        self,
        *,
        hotkey: str,
        hotkey_mode: str,
        ttl_seconds: int,
        max_items: int,
        storage_enabled: bool,
        database_path: str,
    ) -> None:
        if current_thread() is not main_thread():
            from PyObjCTools import AppHelper

            AppHelper.callAfter(
                lambda: self.set_settings_summary(
                    hotkey=hotkey,
                    hotkey_mode=hotkey_mode,
                    ttl_seconds=ttl_seconds,
                    max_items=max_items,
                    storage_enabled=storage_enabled,
                    database_path=database_path,
                )
            )
            return
        from AppKit import NSMenuItem

        self.settings_menu.removeAllItems()
        self._setting_targets = []
        help_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "说明：灰色项目显示当前值；带勾项目点击后立即生效", None, ""
        )
        help_item.setEnabled_(False)
        self.settings_menu.addItem_(help_item)
        self.settings_menu.addItem_(NSMenuItem.separatorItem())
        readonly = [
            f"快捷键：{hotkey} ({hotkey_mode})",
            f"上下文 TTL：{ttl_seconds} 秒（超时后不再传给 AI）",
            f"历史上下文条数：{max_items}（限制本轮 AI 可参考的记录）",
            f"持久化历史：{'开启' if storage_enabled else '关闭'}（用于统计和复制历史）",
            f"数据库：{database_path}",
        ]
        for title in readonly:
            item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(title, None, "")
            item.setEnabled_(False)
            self.settings_menu.addItem_(item)
        self.settings_menu.addItem_(NSMenuItem.separatorItem())
        for title, seconds in [("TTL 5 分钟", 300), ("TTL 10 分钟", 600), ("TTL 30 分钟", 1800)]:
            target = _MenuTargetItem.create_with_arg(
                title=title,
                action=self.on_set_context_ttl,
                arg=seconds,
            )
            target.item.setState_(1 if ttl_seconds == seconds else 0)
            self.settings_menu.addItem_(target.item)
            self._setting_targets.append(target)
        self.settings_menu.addItem_(NSMenuItem.separatorItem())
        for title, count in [("历史上下文 10 条", 10), ("历史上下文 20 条", 20), ("历史上下文 50 条", 50)]:
            target = _MenuTargetItem.create_with_arg(
                title=title,
                action=self.on_set_context_items,
                arg=count,
            )
            target.item.setState_(1 if max_items == count else 0)
            self.settings_menu.addItem_(target.item)
            self._setting_targets.append(target)
        self.settings_menu.addItem_(NSMenuItem.separatorItem())
        hotkeys = [
            ("切换：Cmd+Shift+Space", ("cmd+shift+space", "toggle")),
            ("按住：地球仪键", ("globe", "hold")),
        ]
        for title, preset in hotkeys:
            target = _MenuTargetItem.create_with_arg(
                title=title,
                action=lambda value: self.on_set_hotkey_preset(value[0], value[1]),
                arg=preset,
            )
            target.item.setState_(1 if (hotkey, hotkey_mode) == preset else 0)
            self.settings_menu.addItem_(target.item)
            self._setting_targets.append(target)
        self.settings_menu.addItem_(NSMenuItem.separatorItem())
        self.settings_menu.addItem_(self.settings_open_config_item.item)
        self.settings_menu.addItem_(self.settings_reload_config_item.item)

    def set_stats(self, *, totals: dict[str, int | float], app_stats: list[AppStats]) -> None:
        if current_thread() is not main_thread():
            from PyObjCTools import AppHelper

            AppHelper.callAfter(lambda: self.set_stats(totals=totals, app_stats=app_stats))
            return
        from AppKit import NSMenuItem

        self.stats_menu.removeAllItems()
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
        intro = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "选择记录后可复制原始转写或 AI 润色结果", None, ""
        )
        intro.setEnabled_(False)
        self.history_menu.addItem_(intro)
        self.history_menu.addItem_(NSMenuItem.separatorItem())
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

    def set_prompt_preview(self, *, label: str, prompt: str) -> None:
        if current_thread() is not main_thread():
            from PyObjCTools import AppHelper

            AppHelper.callAfter(lambda: self.set_prompt_preview(label=label, prompt=prompt))
            return
        # Prompt preview is rendered inline by set_styles() under the selected style.
        return

    def set_delete_prompt_enabled(self, enabled: bool) -> None:
        self.delete_prompt_item.item.setEnabled_(enabled)


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
    def create_with_arg(cls, *, title: str, action: Callable, arg):
        from AppKit import NSMenuItem

        target = _MenuActionTarget.alloc().initWithCallback_(lambda: action(arg))
        item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(title, "perform:", "")
        item.setTarget_(target)
        return cls(item, target)


def _chunk_text(text: str, size: int) -> list[str]:
    if not text:
        return ["（空）"]
    return [text[index : index + size] for index in range(0, len(text), size)]


def _history_title(record: dict) -> str:
    text = _ellipsize(" ".join(str(record.get("final_text", "")).split()), 24)
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
