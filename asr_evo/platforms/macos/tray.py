from __future__ import annotations

from collections.abc import Callable
from threading import current_thread, main_thread

from asr_evo.config import StatusConfig
from asr_evo.core.errors import ErrorFeedback
from asr_evo.ui.menu import (
    APP_BINDING_UNKNOWN_TITLE,
    ERROR_MENU_TITLE,
    HISTORY_MENU_TITLE,
    InputDeviceMenuItem,
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
    error_feedback_lines,
    history_menu_records,
    hotkey_menu_title,
    input_device_menu_title,
    should_separate_input_device,
    stats_menu_lines,
    status_presentation,
)
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
        actions: TrayMenuActions,
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
        self.actions = actions
        self._style_targets: list[_MenuTargetItem] = []
        self._input_device_targets: list[_MenuTargetItem] = []
        self._history_targets: list[_MenuTargetItem] = []
        self._error_targets: list[_MenuTargetItem] = []
        self._styles = styles
        self._selected_style_id = selected_style_id
        self._input_devices: list[InputDeviceMenuItem] = []
        self._selected_input_device_id = ""
        self._review_enabled = True
        self._app_binding_title = APP_BINDING_UNKNOWN_TITLE
        self._error_feedback: ErrorFeedback | None = None

        self.menu = NSMenu.alloc().init()
        self.menu.setDelegate_(self)
        self.hotkey_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            hotkey_menu_title(hotkey_label), None, ""
        )
        self.reveal_prompts_item = _MenuTargetItem.create(
            title=command_title(MenuCommand.REVEAL_PROMPTS),
            action=actions.reveal_prompts,
        )
        self.clear_app_style_item = _MenuTargetItem.create(
            title=command_title(MenuCommand.CLEAR_APP_STYLE),
            action=actions.clear_app_style,
        )
        self.reload_config_item = _MenuTargetItem.create(
            title=command_title(MenuCommand.RELOAD_CONFIG),
            action=actions.reload_config,
        )
        self.open_config_item = _MenuTargetItem.create(
            title=command_title(MenuCommand.OPEN_CONFIG),
            action=actions.open_config,
        )
        self.review_item = _MenuTargetItem.create(
            title=command_title(MenuCommand.TOGGLE_REVIEW),
            action=actions.toggle_review,
        )
        self.stats_menu_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            STATS_MENU_TITLE, None, ""
        )
        self.stats_menu = NSMenu.alloc().initWithTitle_(STATS_MENU_TITLE)
        self.stats_menu_item.setSubmenu_(self.stats_menu)
        self.history_menu_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            HISTORY_MENU_TITLE, None, ""
        )
        self.history_menu = NSMenu.alloc().initWithTitle_(HISTORY_MENU_TITLE)
        self.history_menu_item.setSubmenu_(self.history_menu)
        self.prompt_menu_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            PROMPT_MENU_TITLE, None, ""
        )
        self.prompt_menu = NSMenu.alloc().initWithTitle_(PROMPT_MENU_TITLE)
        self.prompt_menu.setDelegate_(self)
        self.prompt_menu_item.setSubmenu_(self.prompt_menu)
        self.input_device_menu_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            INPUT_DEVICE_MENU_TITLE, None, ""
        )
        self.input_device_menu = NSMenu.alloc().initWithTitle_(INPUT_DEVICE_MENU_TITLE)
        self.input_device_menu.setDelegate_(self)
        self.input_device_menu_item.setSubmenu_(self.input_device_menu)
        self.error_menu_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            ERROR_MENU_TITLE, None, ""
        )
        self.error_menu = NSMenu.alloc().initWithTitle_(ERROR_MENU_TITLE)
        self.error_menu_item.setSubmenu_(self.error_menu)
        self.refresh_stats_item = _MenuTargetItem.create(
            title=command_title(MenuCommand.REFRESH_STATS),
            action=actions.refresh_stats,
        )
        self.stats_menu.addItem_(self.refresh_stats_item.item)
        self.quit_item = _MenuTargetItem.create(
            title=command_title(MenuCommand.QUIT),
            action=actions.quit,
        )

        self.menu.addItem_(self.hotkey_item)
        self.menu.addItem_(self.error_menu_item)
        self.menu.addItem_(self.input_device_menu_item)
        self.menu.addItem_(self.prompt_menu_item)
        self.menu.addItem_(self.review_item.item)
        self.menu.addItem_(NSMenuItem.separatorItem())
        self.menu.addItem_(self.stats_menu_item)
        self.menu.addItem_(self.history_menu_item)
        self.menu.addItem_(self.reload_config_item.item)
        self.menu.addItem_(self.open_config_item.item)
        self.menu.addItem_(NSMenuItem.separatorItem())
        self.menu.addItem_(self.quit_item.item)
        self.status_item.setMenu_(self.menu)
        self.set_styles(styles, selected_style_id)
        self.set_review_enabled(True)
        self.set_error_feedback(None)

    def set_state(self, state: str, detail: str = "") -> None:
        if _call_on_main_thread(self.set_state, state, detail):
            return
        status = status_presentation(self.status_config, state, detail)
        self.button.setTitle_(status.title)
        self.button.setToolTip_(status.tooltip)

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
        for title in error_feedback_lines(feedback):
            item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(title, None, "")
            item.setEnabled_(False)
            self.error_menu.addItem_(item)
        self.error_menu.addItem_(NSMenuItem.separatorItem())
        copy_item = _MenuTargetItem.create(
            title=command_title(MenuCommand.COPY_ERROR),
            action=self.actions.copy_error,
        )
        clear_item = _MenuTargetItem.create(
            title=command_title(MenuCommand.CLEAR_ERROR),
            action=self.actions.clear_error,
        )
        self.error_menu.addItem_(copy_item.item)
        self.error_menu.addItem_(clear_item.item)
        self._error_targets.extend([copy_item, clear_item])

    def menuWillOpen_(self, menu) -> None:
        self._refresh_menu_if_needed(menu)

    def menuNeedsUpdate_(self, menu) -> None:
        self._refresh_menu_if_needed(menu)

    def _refresh_menu_if_needed(self, menu) -> None:
        if menu in (self.menu, self.prompt_menu):
            self.actions.refresh_app_binding()
        if menu in (self.menu, self.input_device_menu):
            self.actions.refresh_input_devices()

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
            node=build_style_tree(styles),
            selected_style_id=selected_style_id,
            action=self.actions.select_style,
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

    def set_review_enabled(self, enabled: bool) -> None:
        if _call_on_main_thread(self.set_review_enabled, enabled):
            return
        self._review_enabled = enabled
        self.review_item.item.setState_(1 if enabled else 0)

    def set_hotkey_label(self, hotkey_label: str) -> None:
        if _call_on_main_thread(self.set_hotkey_label, hotkey_label):
            return
        self.hotkey_item.setTitle_(hotkey_label)

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
        self.input_device_menu_item.setTitle_(input_device_menu_title(devices, selected_device_id))
        if not devices:
            item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
                NO_INPUT_DEVICES_TITLE,
                None,
                "",
            )
            item.setEnabled_(False)
            self.input_device_menu.addItem_(item)
            return
        _add_input_devices_to_menu(
            menu=self.input_device_menu,
            devices=devices,
            selected_device_id=selected_device_id,
            action=self.actions.select_input_device,
            targets=self._input_device_targets,
        )

    def set_stats(self, *, totals: dict[str, int | float], app_stats: list[AppStats]) -> None:
        if _call_on_main_thread(self.set_stats, totals=totals, app_stats=app_stats):
            return
        from AppKit import NSMenuItem

        self.stats_menu.removeAllItems()
        self.stats_menu.addItem_(self.refresh_stats_item.item)
        self.stats_menu.addItem_(NSMenuItem.separatorItem())
        total_lines, app_lines = stats_menu_lines(totals=totals, app_stats=app_stats)
        for title in total_lines:
            item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(title, None, "")
            item.setEnabled_(False)
            self.stats_menu.addItem_(item)
        if app_lines:
            self.stats_menu.addItem_(NSMenuItem.separatorItem())
        for title in app_lines:
            item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(title, None, "")
            item.setEnabled_(False)
            self.stats_menu.addItem_(item)

    def set_history_records(self, records: list[dict]) -> None:
        if _call_on_main_thread(self.set_history_records, records):
            return
        from AppKit import NSMenu, NSMenuItem

        self.history_menu.removeAllItems()
        self._history_targets = []
        if not records:
            item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
                NO_HISTORY_RECORDS_TITLE,
                None,
                "",
            )
            item.setEnabled_(False)
            self.history_menu.addItem_(item)
            return
        for record in history_menu_records(records):
            title = record.title
            item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(title, None, "")
            submenu = NSMenu.alloc().initWithTitle_(title)
            raw_preview = _readonly_item(record.raw_preview)
            final_preview = _readonly_item(record.final_preview)
            submenu.addItem_(raw_preview)
            submenu.addItem_(final_preview)
            if record.user_edit_preview is not None:
                submenu.addItem_(_readonly_item(record.user_edit_preview))
            submenu.addItem_(NSMenuItem.separatorItem())
            raw = _MenuTargetItem.create_with_arg(
                title=command_title(MenuCommand.COPY_HISTORY_RAW),
                action=self.actions.copy_history_raw,
                arg=record.id,
            )
            final = _MenuTargetItem.create_with_arg(
                title=command_title(MenuCommand.COPY_HISTORY_FINAL),
                action=self.actions.copy_history_final,
                arg=record.id,
            )
            submenu.addItem_(raw.item)
            submenu.addItem_(final.item)
            targets = [raw, final]
            if record.user_edit_preview is not None:
                user_edit = _MenuTargetItem.create_with_arg(
                    title=command_title(MenuCommand.COPY_HISTORY_USER_EDIT),
                    action=self.actions.copy_history_user_edit,
                    arg=record.id,
                )
                submenu.addItem_(user_edit.item)
                targets.append(user_edit)
            item.setSubmenu_(submenu)
            self.history_menu.addItem_(item)
            self._history_targets.extend(targets)


def _call_on_main_thread(callback: Callable, *args, **kwargs) -> bool:
    if current_thread() is main_thread():
        return False
    from PyObjCTools import AppHelper

    AppHelper.callAfter(callback, *args, **kwargs)
    return True


def _add_style_tree_to_menu(
    *,
    menu,
    node: StyleMenuNode,
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
        if should_separate_input_device(devices, index):
            menu.addItem_(NSMenuItem.separatorItem())


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


def _readonly_item(title: str) -> object:
    from AppKit import NSMenuItem

    item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(title, None, "")
    item.setEnabled_(False)
    return item


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
