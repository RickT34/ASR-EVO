from __future__ import annotations

from collections.abc import Callable

from asr_evo.config import API_KEY_ENV, AppConfig, save_env_value
from asr_evo.storage.history import HistoryStore, format_datetime


def _activate_window(window) -> None:
    from AppKit import (
        NSApp,
        NSApplication,
        NSApplicationActivateIgnoringOtherApps,
        NSApplicationActivationPolicyRegular,
        NSFloatingWindowLevel,
    )

    NSApplication.sharedApplication().setActivationPolicy_(NSApplicationActivationPolicyRegular)
    window.setLevel_(NSFloatingWindowLevel)
    window.center()
    window.makeKeyAndOrderFront_(None)
    NSApp.activateIgnoringOtherApps_(True)
    NSApp.activateWithOptions_(NSApplicationActivateIgnoringOtherApps)


class SettingsWindow:
    def __init__(
        self,
        *,
        config: AppConfig,
        config_path: str = "config.toml",
        on_saved: Callable[[AppConfig], None] | None = None,
    ) -> None:
        from AppKit import (
            NSButton,
            NSMakeRect,
            NSTextField,
            NSWindow,
            NSWindowStyleMaskClosable,
            NSWindowStyleMaskMiniaturizable,
            NSWindowStyleMaskResizable,
            NSWindowStyleMaskTitled,
        )

        self.config = config
        self.config_path = config_path
        self.on_saved = on_saved
        self.fields = {}
        self.window = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(0, 0, 560, 420),
            NSWindowStyleMaskTitled
            | NSWindowStyleMaskClosable
            | NSWindowStyleMaskMiniaturizable
            | NSWindowStyleMaskResizable,
            2,
            False,
        )
        self.window.setReleasedWhenClosed_(False)
        self.window.setTitle_("ASR-EVO 设置")
        content = self.window.contentView()

        rows = [
            ("DASHSCOPE API Key", "api_key", config.llm_api_key() or ""),
            ("快捷键", "hotkey", config.hotkey.toggle),
            ("快捷键模式(toggle/hold)", "hotkey_mode", config.hotkey.mode),
            ("上下文 TTL 秒数", "ttl", str(config.context.ttl_seconds)),
            ("历史上下文条数", "max_items", str(config.context.max_items)),
            ("提示词目录", "prompts_dir", config.style.prompts_dir),
        ]
        title = NSTextField.labelWithString_("常用设置")
        title.setFrame_(NSMakeRect(24, 372, 200, 26))
        title.setFont_(title.font().boldSystemFontOfSize_(16))
        content.addSubview_(title)

        y = 330
        for label, key, value in rows:
            label_view = NSTextField.labelWithString_(label)
            label_view.setFrame_(NSMakeRect(28, y, 150, 24))
            content.addSubview_(label_view)
            field = NSTextField.alloc().initWithFrame_(NSMakeRect(190, y, 330, 26))
            field.setStringValue_(value)
            content.addSubview_(field)
            self.fields[key] = field
            y -= 40

        self.save_target = _WindowActionTarget.alloc().initWithCallback_(self.save)
        button = NSButton.alloc().initWithFrame_(NSMakeRect(420, 22, 100, 32))
        button.setTitle_("保存")
        button.setTarget_(self.save_target)
        button.setAction_("perform:")
        content.addSubview_(button)
        self.status_label = NSTextField.labelWithString_("")
        self.status_label.setFrame_(NSMakeRect(28, 24, 360, 24))
        content.addSubview_(self.status_label)

    def show(self) -> None:
        _activate_window(self.window)

    def save(self) -> None:
        try:
            data = self._build_config()
            api_key = self.fields["api_key"].stringValue().strip()
            if api_key:
                save_env_value(API_KEY_ENV, api_key)
            data.save(self.config_path)
            self.config = data
            if self.on_saved:
                self.on_saved(data)
            self.status_label.setStringValue_("已保存")
        except Exception as exc:
            self.status_label.setStringValue_(f"保存失败：{exc}")

    def _build_config(self) -> AppConfig:
        current = self.config.model_dump(mode="json")
        current["hotkey"]["toggle"] = self.fields["hotkey"].stringValue()
        current["hotkey"]["mode"] = self.fields["hotkey_mode"].stringValue()
        current["context"]["ttl_seconds"] = int(self.fields["ttl"].stringValue())
        current["context"]["max_items"] = int(self.fields["max_items"].stringValue())
        current["style"]["prompts_dir"] = self.fields["prompts_dir"].stringValue()
        return AppConfig.model_validate(current)


class HistoryWindow:
    def __init__(self, history: HistoryStore) -> None:
        from AppKit import (
            NSMakeRect,
            NSScrollView,
            NSTextView,
            NSWindow,
            NSWindowStyleMaskClosable,
            NSWindowStyleMaskMiniaturizable,
            NSWindowStyleMaskResizable,
            NSWindowStyleMaskTitled,
        )

        self.history = history
        self.window = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(0, 0, 720, 520),
            NSWindowStyleMaskTitled
            | NSWindowStyleMaskClosable
            | NSWindowStyleMaskMiniaturizable
            | NSWindowStyleMaskResizable,
            2,
            False,
        )
        self.window.setReleasedWhenClosed_(False)
        self.window.setTitle_("ASR-EVO 听写历史与统计")
        self.text_view = NSTextView.alloc().initWithFrame_(NSMakeRect(0, 0, 700, 500))
        self.text_view.setEditable_(False)
        scroll = NSScrollView.alloc().initWithFrame_(NSMakeRect(10, 10, 700, 500))
        scroll.setDocumentView_(self.text_view)
        scroll.setHasVerticalScroller_(True)
        self.window.contentView().addSubview_(scroll)

    def show(self) -> None:
        self.refresh()
        _activate_window(self.window)

    def refresh(self) -> None:
        totals = self.history.totals()
        lines = [
            "总体统计",
            f"听写次数：{totals['count']}",
            f"累计字数：{totals['total_chars']}",
            f"累计音频秒数：{totals['total_audio_seconds']:.1f}",
            "",
            "按应用统计",
        ]
        for stat in self.history.stats_by_app():
            lines.append(
                f"- {stat.app_name}: {stat.count} 次，{stat.total_chars} 字，"
                f"{stat.total_audio_seconds:.1f} 秒"
            )
        lines.extend(["", "最近听写"])
        for row in self.history.recent(limit=80):
            lines.append(
                f"[{format_datetime(row['ended_at'])}] {row['app_name'] or row['bundle_id']} "
                f"({row['style']}, {row['final_chars']} 字)"
            )
            lines.append(row["final_text"])
            lines.append("")
        self.text_view.setString_("\n".join(lines))


try:
    from Foundation import NSObject
except ImportError:  # pragma: no cover
    NSObject = object


class _WindowActionTarget(NSObject):
    def initWithCallback_(self, callback):
        self = self.init()
        self.callback = callback
        return self

    def perform_(self, sender):
        self.callback()
