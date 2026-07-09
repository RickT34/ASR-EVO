from __future__ import annotations

from asr_evo.core.ports import AppStatsSummary, InputDeviceSummary, StatusTray
from asr_evo.postprocess.styles import StyleDefinition


class UnboundStatusTray(StatusTray):
    def __init__(self) -> None:
        self._tray: StatusTray | None = None

    def bind(self, tray: StatusTray) -> None:
        self._tray = tray

    def set_state(self, state: str, detail: str = "") -> None:
        self._bound().set_state(state, detail)

    def set_error_feedback(self, feedback) -> None:
        self._bound().set_error_feedback(feedback)

    def set_styles(self, styles: list[StyleDefinition], selected_style_id: str) -> None:
        self._bound().set_styles(styles, selected_style_id)

    def set_app_binding_summary(self, title: str) -> None:
        self._bound().set_app_binding_summary(title)

    def set_status_config(self, status_config: object) -> None:
        self._bound().set_status_config(status_config)

    def set_review_enabled(self, enabled: bool) -> None:
        self._bound().set_review_enabled(enabled)

    def set_input_devices(
        self,
        devices: list[InputDeviceSummary],
        selected_device_id: str,
    ) -> None:
        self._bound().set_input_devices(devices, selected_device_id)

    def set_stats(
        self,
        *,
        totals: dict[str, int | float],
        app_stats: list[AppStatsSummary],
    ) -> None:
        self._bound().set_stats(totals=totals, app_stats=app_stats)

    def set_history_records(self, records: list[dict]) -> None:
        self._bound().set_history_records(records)

    def _bound(self) -> StatusTray:
        if self._tray is None:
            raise RuntimeError("status tray has not been bound")
        return self._tray
