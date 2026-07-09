from __future__ import annotations

from collections.abc import Callable

from asr_evo.config import StatusConfig
from asr_evo.core.errors import ErrorFeedback
from asr_evo.postprocess.styles import StyleDefinition
from asr_evo.storage.history import AppStats
from asr_evo.ui.menu import (
    APP_BINDING_UNKNOWN_TITLE,
    ERROR_MENU_TITLE,
    HISTORY_MENU_TITLE,
    INPUT_DEVICE_MENU_TITLE,
    MenuCommand,
    NO_HISTORY_RECORDS_TITLE,
    NO_INPUT_DEVICES_TITLE,
    PROMPT_MENU_TITLE,
    STATS_MENU_TITLE,
    StyleMenuNode,
    TrayMenuActions,
    build_style_tree,
    command_title,
    control_menu_title,
    error_feedback_lines,
    history_menu_records,
    input_device_menu_title,
    stats_menu_lines,
    status_presentation,
)


class WindowsStatusTray:
    def __init__(
        self,
        *,
        control_label: str,
        status_config: StatusConfig,
        styles: list[StyleDefinition],
        selected_style_id: str,
        actions: TrayMenuActions,
    ) -> None:
        self.control_label = control_label
        self.status_config = status_config
        self.actions = actions
        self._styles = styles
        self._selected_style_id = selected_style_id
        self._input_devices = []
        self._selected_input_device_id = ""
        self._review_enabled = True
        self._app_binding_title = APP_BINDING_UNKNOWN_TITLE
        self._error_feedback: ErrorFeedback | None = None
        self._state = "idle"
        self._tooltip = status_presentation(status_config, "idle").tooltip
        self._totals: dict[str, int | float] = {}
        self._app_stats: list[AppStats] = []
        self._history_records: list[dict] = []
        self.icon = None

    def run(self) -> None:
        try:
            import pystray
        except ImportError as exc:
            raise RuntimeError("pystray is required for the Windows tray menu") from exc

        self.icon = pystray.Icon(
            "ASR-EVO",
            _status_icon(self._state),
            self._tooltip,
            self._build_menu(),
        )
        self.icon.run()

    def stop(self) -> None:
        if self.icon is not None:
            self.icon.stop()

    def set_state(self, state: str, detail: str = "") -> None:
        self._state = state
        status = status_presentation(self.status_config, state, detail)
        self._tooltip = status.tooltip
        if self.icon is not None:
            self.icon.icon = _status_icon(state)
            self.icon.title = self._tooltip
            self._publish_menu()

    def set_error_feedback(self, feedback: ErrorFeedback | None) -> None:
        self._error_feedback = feedback
        self._publish_menu()

    def set_styles(self, styles: list[StyleDefinition], selected_style_id: str) -> None:
        self._styles = styles
        self._selected_style_id = selected_style_id
        self._publish_menu()

    def set_app_binding_summary(self, title: str) -> None:
        self._app_binding_title = title
        self._publish_menu()

    def set_status_config(self, status_config: StatusConfig) -> None:
        self.status_config = status_config
        self.set_state(self._state)

    def set_review_enabled(self, enabled: bool) -> None:
        self._review_enabled = enabled
        self._publish_menu()

    def set_control_label(self, endpoint: str) -> None:
        self.control_label = endpoint
        self._publish_menu()

    def set_input_devices(self, devices: list, selected_device_id: str) -> None:
        self._input_devices = devices
        self._selected_input_device_id = selected_device_id
        self._publish_menu()

    def set_stats(self, *, totals: dict[str, int | float], app_stats: list[AppStats]) -> None:
        self._totals = totals
        self._app_stats = app_stats
        self._publish_menu()

    def set_history_records(self, records: list[dict]) -> None:
        self._history_records = records
        self._publish_menu()

    def _publish_menu(self) -> None:
        if self.icon is None:
            return
        self.icon.menu = self._build_menu()
        self.icon.update_menu()

    def _build_menu(self):
        import pystray

        items = [
            _readonly(control_menu_title(self.control_label)),
        ]
        if self._error_feedback is not None:
            items.append(self._error_menu())
        items.extend(
            [
                self._input_device_menu(),
                self._prompt_menu(),
                pystray.MenuItem(
                    command_title(MenuCommand.TOGGLE_REVIEW),
                    _action(self.actions.toggle_review),
                    checked=lambda item: self._review_enabled,
                ),
                pystray.Menu.SEPARATOR,
                self._stats_menu(),
                self._history_menu(),
                pystray.MenuItem(
                    command_title(MenuCommand.RELOAD_CONFIG),
                    _action(self.actions.reload_config),
                ),
                pystray.MenuItem(
                    command_title(MenuCommand.OPEN_CONFIG),
                    _action(self.actions.open_config),
                ),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem(command_title(MenuCommand.QUIT), _action(self.actions.quit)),
            ]
        )
        return pystray.Menu(*items)

    def _error_menu(self):
        import pystray

        assert self._error_feedback is not None
        lines = [_readonly(line) for line in error_feedback_lines(self._error_feedback)]
        lines.extend(
            [
                pystray.Menu.SEPARATOR,
                pystray.MenuItem(command_title(MenuCommand.COPY_ERROR), _action(self.actions.copy_error)),
                pystray.MenuItem(command_title(MenuCommand.CLEAR_ERROR), _action(self.actions.clear_error)),
            ]
        )
        return pystray.MenuItem(
            f"{ERROR_MENU_TITLE}：{self._error_feedback.title}",
            pystray.Menu(*lines),
        )

    def _input_device_menu(self):
        import pystray

        title = input_device_menu_title(self._input_devices, self._selected_input_device_id)
        if not self._input_devices:
            return pystray.MenuItem(title or INPUT_DEVICE_MENU_TITLE, pystray.Menu(_readonly(NO_INPUT_DEVICES_TITLE)))
        items = [
            pystray.MenuItem(
                device.label,
                _action_with_arg(self.actions.select_input_device, device.id),
                checked=lambda item, device_id=device.id: device_id == self._selected_input_device_id,
                radio=True,
            )
            for device in self._input_devices
        ]
        return pystray.MenuItem(title, pystray.Menu(*items))

    def _prompt_menu(self):
        import pystray

        style_items = _style_tree_items(
            build_style_tree(self._styles),
            self._selected_style_id,
            self.actions.select_style,
        )
        items = [
            *style_items,
            pystray.Menu.SEPARATOR,
            _readonly(self._app_binding_title),
            pystray.MenuItem(
                command_title(MenuCommand.CLEAR_APP_STYLE),
                _action(self.actions.clear_app_style),
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(
                command_title(MenuCommand.REVEAL_PROMPTS),
                _action(self.actions.reveal_prompts),
            ),
        ]
        return pystray.MenuItem(PROMPT_MENU_TITLE, pystray.Menu(*items))

    def _stats_menu(self):
        import pystray

        total_lines, app_lines = stats_menu_lines(totals=self._totals, app_stats=self._app_stats)
        items = [
            pystray.MenuItem(
                command_title(MenuCommand.REFRESH_STATS),
                _action(self.actions.refresh_stats),
            ),
            pystray.Menu.SEPARATOR,
            *[_readonly(line) for line in total_lines],
        ]
        if app_lines:
            items.append(pystray.Menu.SEPARATOR)
            items.extend(_readonly(line) for line in app_lines)
        return pystray.MenuItem(STATS_MENU_TITLE, pystray.Menu(*items))

    def _history_menu(self):
        import pystray

        if not self._history_records:
            return pystray.MenuItem(HISTORY_MENU_TITLE, pystray.Menu(_readonly(NO_HISTORY_RECORDS_TITLE)))
        items = []
        for record in history_menu_records(self._history_records):
            children = [
                _readonly(record.raw_preview),
                _readonly(record.final_preview),
            ]
            if record.user_edit_preview is not None:
                children.append(_readonly(record.user_edit_preview))
            children.extend(
                [
                    pystray.Menu.SEPARATOR,
                    pystray.MenuItem(
                        command_title(MenuCommand.COPY_HISTORY_RAW),
                        _action_with_arg(self.actions.copy_history_raw, record.id),
                    ),
                    pystray.MenuItem(
                        command_title(MenuCommand.COPY_HISTORY_FINAL),
                        _action_with_arg(self.actions.copy_history_final, record.id),
                    ),
                ]
            )
            if record.user_edit_preview is not None:
                children.append(
                    pystray.MenuItem(
                        command_title(MenuCommand.COPY_HISTORY_USER_EDIT),
                        _action_with_arg(self.actions.copy_history_user_edit, record.id),
                    )
                )
            items.append(pystray.MenuItem(record.title, pystray.Menu(*children)))
        return pystray.MenuItem(HISTORY_MENU_TITLE, pystray.Menu(*items))


def _style_tree_items(
    node: StyleMenuNode,
    selected_style_id: str,
    action: Callable[[str], None],
) -> list:
    import pystray

    items = [
        pystray.MenuItem(
            style.label,
            _action_with_arg(action, style.id),
            checked=lambda item, style_id=style.id: style_id == selected_style_id,
            radio=True,
        )
        for style in sorted(node.styles, key=lambda item: item.label.lower())
    ]
    for child in sorted(node.children.values(), key=lambda item: item.name.lower()):
        items.append(
            pystray.MenuItem(
                child.name,
                pystray.Menu(*_style_tree_items(child, selected_style_id, action)),
            )
        )
    return items


def _readonly(title: str):
    import pystray

    return pystray.MenuItem(title, None, enabled=False)


def _action(callback: Callable[[], None]):
    def run(icon=None, item=None) -> None:
        callback()

    return run


def _action_with_arg(callback: Callable, arg):
    def run(icon=None, item=None) -> None:
        callback(arg)

    return run


def _status_icon(state: str):
    try:
        from PIL import Image, ImageDraw
    except ImportError as exc:
        raise RuntimeError("Pillow is required for the Windows tray icon") from exc

    colors = {
        "idle": (45, 111, 214, 255),
        "recording": (220, 53, 69, 255),
        "transcribing": (111, 66, 193, 255),
        "polishing": (25, 135, 84, 255),
        "reviewing": (245, 158, 11, 255),
        "inserting": (13, 148, 136, 255),
        "error": (220, 53, 69, 255),
    }
    image = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    color = colors.get(state, colors["idle"])
    draw.ellipse((8, 8, 56, 56), fill=color)
    draw.rounded_rectangle((28, 18, 36, 38), radius=4, fill=(255, 255, 255, 255))
    draw.line((32, 38, 32, 47), fill=(255, 255, 255, 255), width=4)
    draw.arc((22, 30, 42, 48), start=0, end=180, fill=(255, 255, 255, 255), width=3)
    return image
