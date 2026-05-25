from __future__ import annotations

from dataclasses import dataclass

from asr_evo.config import AppConfig
from asr_evo.core.ports import AppContext
from asr_evo.postprocess.styles import StyleRegistry


@dataclass(frozen=True)
class StyleSync:
    app: AppContext
    style_id: str
    summary: str
    warning: str = ""


@dataclass(frozen=True)
class StyleBindingUpdate:
    config: AppConfig | None
    app: AppContext
    removed: bool = False


class StyleBindingService:
    def __init__(self, *, config: AppConfig, styles: StyleRegistry) -> None:
        self.config = config
        self.styles = styles
        self.current_style_id = self.default_style_id()
        self.last_target_app = AppContext()

    def configure(self, config: AppConfig, *, styles: StyleRegistry | None = None) -> None:
        self.config = config
        if styles is not None:
            self.styles = styles
        if not self.styles.has(self.current_style_id):
            self.current_style_id = self.default_style_id()

    def reload_styles(self) -> None:
        self.styles.reload()
        if not self.styles.has(self.current_style_id):
            self.current_style_id = self.default_style_id()

    def select(self, style_id: str) -> bool:
        if not self.styles.has(style_id):
            self.reload_styles()
        if not self.styles.has(style_id):
            return False
        self.current_style_id = style_id
        return True

    def sync_for_app(self, app: AppContext) -> StyleSync:
        app = self._remember(app)
        if not app.bundle_id:
            self.current_style_id = self.default_style_id()
            return StyleSync(app=app, style_id=self.current_style_id, summary=self.summary_for(app))

        style_id = self.config.style.app_styles.get(app.bundle_id) or self.default_style_id()
        warning = ""
        if not self.styles.has(style_id):
            warning = f"应用绑定的风格不存在：{style_id}"
            style_id = self.default_style_id()
        self.current_style_id = style_id
        return StyleSync(app=app, style_id=style_id, summary=self.summary_for(app), warning=warning)

    def bind_current_style(self, app: AppContext) -> StyleBindingUpdate:
        app = self._target_app(app)
        if not app.bundle_id:
            return StyleBindingUpdate(config=None, app=app)
        config = self.config.model_copy(deep=True)
        config.style.app_styles[app.bundle_id] = self.current_style_id
        return StyleBindingUpdate(config=config, app=app)

    def clear_current_app_style(self, app: AppContext) -> StyleBindingUpdate:
        app = self._target_app(app)
        if not app.bundle_id:
            return StyleBindingUpdate(config=None, app=app)
        config = self.config.model_copy(deep=True)
        removed = config.style.app_styles.pop(app.bundle_id, None) is not None
        return StyleBindingUpdate(config=config, app=app, removed=removed)

    def summary_for(self, app: AppContext) -> str:
        if not app.bundle_id:
            return "当前应用绑定：未识别当前应用"

        app_name = app.app_name or app.bundle_id
        style_id = self.config.style.app_styles.get(app.bundle_id)
        if not style_id:
            return f"当前应用绑定：{app_name} 未绑定"

        label = self.styles.get(style_id).label if self.styles.has(style_id) else f"{style_id}（不存在）"
        return f"当前应用绑定：{app_name} -> {label}"

    def default_style_id(self) -> str:
        mode = self.config.style.mode
        return mode if self.styles.has(mode) else self.styles.default_style_id()

    def _remember(self, app: AppContext) -> AppContext:
        if app.bundle_id:
            self.last_target_app = app
        return app

    def _target_app(self, app: AppContext) -> AppContext:
        if app.bundle_id:
            self.last_target_app = app
            return app
        return self.last_target_app
