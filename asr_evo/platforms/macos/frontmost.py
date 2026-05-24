from __future__ import annotations

from asr_evo.core.ports import AppContext


class MacOSFrontmostAppProvider:
    def current_app(self) -> AppContext:
        try:
            from AppKit import NSWorkspace
        except ImportError:
            return AppContext()

        app = NSWorkspace.sharedWorkspace().frontmostApplication()
        if app is None:
            return AppContext()
        return AppContext(
            bundle_id=str(app.bundleIdentifier() or ""),
            app_name=str(app.localizedName() or ""),
            window_title=None,
        )
