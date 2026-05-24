from __future__ import annotations

import asyncio
import time


class MacOSTextInserter:
    """Native macOS text insertion.

    Primary strategy: Accessibility focused element mutation.
    Fallback strategy: CGEvent Unicode keyboard events.
    Clipboard restore is intentionally not part of the default path.
    """

    def __init__(self, *, fallback: str = "unicode_events") -> None:
        self.fallback = fallback

    def can_insert(self) -> bool:
        return True

    async def insert(self, text: str) -> None:
        if self._insert_via_accessibility(text):
            return
        if self.fallback == "clipboard_restore":
            await asyncio.to_thread(self._insert_via_clipboard_restore, text)
            return
        await asyncio.to_thread(self._insert_via_unicode_events, text)

    def _insert_via_accessibility(self, text: str) -> bool:
        try:
            import ApplicationServices as AS
        except ImportError:
            return False

        system = AS.AXUIElementCreateSystemWide()
        err, focused = AS.AXUIElementCopyAttributeValue(system, AS.kAXFocusedUIElementAttribute, None)
        if err != AS.kAXErrorSuccess or focused is None:
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

    def _insert_via_clipboard_restore(self, text: str) -> None:
        try:
            from AppKit import NSPasteboard, NSStringPboardType
            import Quartz
        except ImportError as exc:
            raise RuntimeError("PyObjC AppKit/Quartz is required for clipboard fallback") from exc

        pasteboard = NSPasteboard.generalPasteboard()
        old_items = pasteboard.pasteboardItems()
        pasteboard.clearContents()
        pasteboard.setString_forType_(text, NSStringPboardType)

        self._post_cmd_v(Quartz)
        time.sleep(0.25)

        pasteboard.clearContents()
        if old_items:
            pasteboard.writeObjects_(old_items)

    def _post_cmd_v(self, Quartz) -> None:
        keycode_v = 9
        for is_down in (True, False):
            event = Quartz.CGEventCreateKeyboardEvent(None, keycode_v, is_down)
            Quartz.CGEventSetFlags(event, Quartz.kCGEventFlagMaskCommand)
            Quartz.CGEventPost(Quartz.kCGHIDEventTap, event)
