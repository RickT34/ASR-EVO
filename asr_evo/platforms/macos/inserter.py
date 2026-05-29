from __future__ import annotations

import asyncio
import time


class MacOSTextInserter:
    """macOS text insertion.

    The default strategy mirrors mature dictation/text-expansion tools: put text on the
    pasteboard temporarily, send Cmd+V, then restore the previous pasteboard if the user has not
    changed it meanwhile. That lets the target app own placeholder, selection, cursor and rich text
    behavior instead of mutating an Accessibility value directly.
    """

    def __init__(
        self,
        *,
        mode: str = "pasteboard_restore",
        fallback: str = "unicode_events",
        restore_delay_ms: int = 300,
    ) -> None:
        self.mode = _normalize_mode(mode)
        self.fallback = fallback
        self.restore_delay_seconds = restore_delay_ms / 1000

    async def insert(self, text: str) -> None:
        if self.mode == "pasteboard_restore":
            await asyncio.to_thread(self._insert_via_pasteboard_restore, text)
            return
        if self.mode == "unicode_events":
            await asyncio.to_thread(self._insert_via_unicode_events, text)
            return
        if self._insert_via_accessibility(text):
            return
        if self.fallback == "pasteboard_restore":
            await asyncio.to_thread(self._insert_via_pasteboard_restore, text)
        else:
            await asyncio.to_thread(self._insert_via_unicode_events, text)

    def _insert_via_accessibility(self, text: str) -> bool:
        try:
            import ApplicationServices as AS
        except ImportError:
            return False

        system = AS.AXUIElementCreateSystemWide()
        focused = self._copy_attribute(AS, system, AS.kAXFocusedUIElementAttribute)
        if focused is None:
            return False

        value = self._copy_attribute(AS, focused, AS.kAXValueAttribute)
        selected_range_value = self._copy_attribute(AS, focused, AS.kAXSelectedTextRangeAttribute)
        if not isinstance(value, str) or selected_range_value is None:
            return False

        try:
            ok, selected_range = AS.AXValueGetValue(
                selected_range_value,
                AS.kAXValueCFRangeType,
                None,
            )
            if not ok:
                return False
            start, length = selected_range
            new_value = value[:start] + text + value[start + length :]
            set_err = AS.AXUIElementSetAttributeValue(focused, AS.kAXValueAttribute, new_value)
            if set_err != AS.kAXErrorSuccess:
                return False
            self._set_selected_range(AS, focused, start + len(text), 0)
            return True
        except Exception:
            return False

    def _copy_attribute(self, AS, element, attribute):
        try:
            err, value = AS.AXUIElementCopyAttributeValue(element, attribute, None)
        except Exception:
            return None
        if err != AS.kAXErrorSuccess:
            return None
        return value

    def _set_selected_range(self, AS, element, location: int, length: int) -> bool:
        try:
            import Quartz

            range_value = AS.AXValueCreate(
                AS.kAXValueCFRangeType,
                Quartz.CFRangeMake(location, length),
            )
            err = AS.AXUIElementSetAttributeValue(
                element,
                AS.kAXSelectedTextRangeAttribute,
                range_value,
            )
            return err == AS.kAXErrorSuccess
        except Exception:
            return False

    def _insert_via_unicode_events(self, text: str) -> None:
        try:
            import Quartz
        except ImportError as exc:
            raise RuntimeError("PyObjC Quartz is required for macOS Unicode event insertion") from exc

        for char in text:
            event_down = Quartz.CGEventCreateKeyboardEvent(None, 0, True)
            Quartz.CGEventKeyboardSetUnicodeString(event_down, len(char), char)
            Quartz.CGEventPost(Quartz.kCGHIDEventTap, event_down)

            event_up = Quartz.CGEventCreateKeyboardEvent(None, 0, False)
            Quartz.CGEventKeyboardSetUnicodeString(event_up, len(char), char)
            Quartz.CGEventPost(Quartz.kCGHIDEventTap, event_up)

    def _insert_via_pasteboard_restore(self, text: str) -> None:
        try:
            from AppKit import NSPasteboard, NSPasteboardItem, NSPasteboardTypeString
            import Quartz
        except ImportError as exc:
            raise RuntimeError("PyObjC AppKit/Quartz is required for pasteboard insertion") from exc

        pasteboard = NSPasteboard.generalPasteboard()
        old_items = _PasteboardSnapshot.capture(pasteboard)
        pasteboard.clearContents()
        pasteboard.setString_forType_(text, NSPasteboardTypeString)
        injected_change_count = pasteboard.changeCount()

        self._post_cmd_v(Quartz)
        time.sleep(self.restore_delay_seconds)

        if pasteboard.changeCount() == injected_change_count:
            old_items.restore(pasteboard, NSPasteboardItem)

    def _post_cmd_v(self, Quartz) -> None:
        keycode_v = 9
        for is_down in (True, False):
            event = Quartz.CGEventCreateKeyboardEvent(None, keycode_v, is_down)
            Quartz.CGEventSetFlags(event, Quartz.kCGEventFlagMaskCommand)
            Quartz.CGEventPost(Quartz.kCGHIDEventTap, event)


class _PasteboardSnapshot:
    def __init__(self, items: list[dict]) -> None:
        self.items = items

    @classmethod
    def capture(cls, pasteboard):
        items = []
        for item in pasteboard.pasteboardItems() or []:
            data_by_type = {}
            for item_type in item.types() or []:
                data = item.dataForType_(item_type)
                if data is not None:
                    data_by_type[item_type] = data
            if data_by_type:
                items.append(data_by_type)
        return cls(items)

    def restore(self, pasteboard, NSPasteboardItem) -> None:
        pasteboard.clearContents()
        if not self.items:
            return
        restored_items = []
        for data_by_type in self.items:
            item = NSPasteboardItem.alloc().init()
            for item_type, data in data_by_type.items():
                item.setData_forType_(data, item_type)
            restored_items.append(item)
        pasteboard.writeObjects_(restored_items)


def _normalize_mode(mode: str) -> str:
    aliases = {
        "native": "pasteboard_restore",
        "clipboard_restore": "pasteboard_restore",
        "pasteboard": "pasteboard_restore",
        "pasteboard_restore": "pasteboard_restore",
        "accessibility": "accessibility",
        "unicode_events": "unicode_events",
    }
    if mode not in aliases:
        raise ValueError(f"Unsupported insert mode: {mode}")
    return aliases[mode]
