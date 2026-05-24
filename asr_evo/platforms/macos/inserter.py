from __future__ import annotations

import asyncio


class MacOSTextInserter:
    """Native macOS text insertion.

    Primary strategy: Accessibility focused element mutation.
    Fallback strategy: CGEvent Unicode keyboard events.
    Clipboard restore is intentionally not part of the default path.
    """

    def can_insert(self) -> bool:
        return True

    async def insert(self, text: str) -> None:
        if self._insert_via_accessibility(text):
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

        selected_range = self._copy_attribute(AS, focused, AS.kAXSelectedTextRangeAttribute)
        if selected_range is None:
            return False

        # kAXSelectedTextRangeAttribute is an AXValue CFRange. PyObjC bridges parameterized
        # insertion unevenly across apps, so this is conservative until tested app by app.
        try:
            set_err = AS.AXUIElementSetAttributeValue(focused, AS.kAXSelectedTextAttribute, text)
            return set_err == AS.kAXErrorSuccess
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
