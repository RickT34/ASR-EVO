"""Native GTK menu; Wayland pointer coordinates come from the layer surface."""

from __future__ import annotations

import json
import sys


def menu_position(x: float, y: float, width: int, height: int, bounds: tuple[int, int]):
    return (
        max(0, min(round(x), bounds[0] - width)),
        max(0, min(round(y), bounds[1] - height)),
    )


def main() -> None:
    import gi

    gi.require_version("Gtk", "3.0")
    gi.require_version("Gdk", "3.0")
    from gi.repository import Gdk, Gtk, Pango

    entries = json.load(sys.stdin)
    display = Gdk.Display.get_default()
    if display is None:
        raise RuntimeError("No graphical display available")
    wayland = "Wayland" in type(display).__name__
    if wayland:
        gi.require_version("GtkLayerShell", "0.1")
        from gi.repository import GtkLayerShell as Layer

        if not Layer.is_supported():
            raise RuntimeError("The Wayland compositor does not support layer-shell")

    css = Gtk.CssProvider()
    css.load_from_data(b"""
        #asr-evo-overlay { background-color: transparent; }
        .asr-evo-menu, .asr-evo-menu viewport {
            background-color: #242832; color: #f3f4f6;
        }
        .asr-evo-menu box { background-color: transparent; }
        .asr-evo-menu { border: 1px solid #657084; border-radius: 6px; padding: 5px; }
        .asr-evo-menu button {
            background-image: none; background-color: transparent;
            border: none; box-shadow: none; border-radius: 3px; padding: 6px 9px;
        }
        .asr-evo-menu button:hover, .asr-evo-menu button:focus {
            background-color: #425779;
        }
        .asr-evo-menu label {
            color: #f3f4f6; font-family: sans-serif; font-size: 14px;
            text-shadow: none;
        }
        .asr-evo-menu button:disabled label { color: #a1a8b4; }
    """)
    Gtk.StyleContext.add_provider_for_screen(
        display.get_default_screen(),
        css,
        Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
    )
    selected = []
    windows = []
    opened = False

    def close(*_):
        if Gtk.main_level():
            Gtk.main_quit()
        return True

    def choose(_, key):
        selected.append(key)
        close()

    def build_panel(items, height_limit, width):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_propagate_natural_height(True)
        scroll.set_max_content_height(height_limit)
        scroll.set_size_request(width, -1)
        scroll.get_style_context().add_class("asr-evo-menu")
        scroll.add(box)
        for entry in items:
            if entry.get("separator"):
                box.pack_start(Gtk.Separator(), False, False, 3)
                continue
            children = entry.get("children")
            button = Gtk.MenuButton() if children is not None else Gtk.Button()
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            mark = ("●" if entry.get("radio") else "✓") if entry.get("checked") else ""
            marker = Gtk.Label(label=mark)
            marker.set_size_request(16, -1)
            row.pack_start(marker, False, False, 0)
            label = Gtk.Label(label=entry["title"], xalign=0)
            label.set_ellipsize(Pango.EllipsizeMode.END)
            label.set_max_width_chars(38)
            row.pack_start(label, True, True, 0)
            if children is not None:
                row.pack_end(Gtk.Label(label="›"), False, False, 0)
                popover = Gtk.Popover.new(button)
                # The full-screen layer already handles outside clicks and focus.
                popover.set_modal(False)
                popover.connect("key-press-event", key_press)
                popover.set_position(Gtk.PositionType.RIGHT)
                content = build_panel(children, height_limit, width)
                popover.add(content)
                content.show_all()
                button.set_popover(popover)
            elif entry.get("id") is not None:
                button.connect("clicked", choose, entry["id"])
            button.add(row)
            button.set_sensitive(entry["enabled"])
            button.set_tooltip_text(entry["title"])
            box.pack_start(button, False, False, 0)
        return scroll

    def key_press(_, event):
        if event.keyval == Gdk.KEY_Escape:
            return close()
        return False

    def pointer_enter(background, event, window, overlay):
        nonlocal opened
        if opened:
            return False
        opened = True
        # Both event coordinates and allocation are surface-local logical pixels.
        # No XWayland pointer query or physical/logical scale conversion is involved.
        bounds = (background.get_allocated_width(), background.get_allocated_height())
        panel = build_panel(entries, max(100, bounds[1] - 24), min(380, bounds[0] - 24))
        panel.set_halign(Gtk.Align.START)
        panel.set_valign(Gtk.Align.START)
        overlay.add_overlay(panel)
        panel.show_all()
        _, size = panel.get_preferred_size()
        x, y = menu_position(event.x, event.y, size.width, size.height, bounds)
        panel.set_margin_start(x)
        panel.set_margin_top(y)
        Layer.set_keyboard_mode(window, Layer.KeyboardMode.EXCLUSIVE)
        panel.child_focus(Gtk.DirectionType.TAB_FORWARD)
        return False

    if wayland:
        for index in range(display.get_n_monitors()):
            window = Gtk.Window()
            window.set_name("asr-evo-overlay")
            window.set_visual(window.get_screen().get_rgba_visual())
            Layer.init_for_window(window)
            Layer.set_namespace(window, "asr-evo-menu")
            Layer.set_monitor(window, display.get_monitor(index))
            Layer.set_layer(window, Layer.Layer.OVERLAY)
            Layer.set_keyboard_mode(window, Layer.KeyboardMode.EXCLUSIVE)
            Layer.set_exclusive_zone(window, -1)
            for edge in (Layer.Edge.TOP, Layer.Edge.BOTTOM, Layer.Edge.LEFT, Layer.Edge.RIGHT):
                Layer.set_anchor(window, edge, True)
            overlay = Gtk.Overlay()
            background = Gtk.EventBox()
            background.set_visible_window(True)
            background.add_events(Gdk.EventMask.ENTER_NOTIFY_MASK | Gdk.EventMask.BUTTON_PRESS_MASK)
            background.connect("enter-notify-event", pointer_enter, window, overlay)
            background.connect("button-press-event", close)
            overlay.add(background)
            window.add(overlay)
            window.connect("key-press-event", key_press)
            window.connect("destroy", close)
            windows.append(window)
            window.show_all()
    else:
        # X11 can query global pointer coordinates and position a managed window.
        window = Gtk.Window(title="ASR-EVO")
        window.set_decorated(False)
        window.set_keep_above(True)
        window.set_skip_taskbar_hint(True)
        _, x, y = display.get_default_seat().get_pointer().get_position()
        monitor = display.get_monitor_at_point(x, y).get_workarea()
        panel = build_panel(entries, max(100, monitor.height - 24), min(380, monitor.width - 24))
        window.add(panel)
        window.connect("key-press-event", key_press)
        window.connect("focus-out-event", close)
        window.connect("destroy", close)
        window.show_all()
        _, size = panel.get_preferred_size()
        px, py = menu_position(
            x - monitor.x, y - monitor.y, size.width, size.height, (monitor.width, monitor.height)
        )
        window.move(monitor.x + px, monitor.y + py)
        windows.append(window)
        window.present()
    try:
        Gtk.main()
    finally:
        for window in windows:
            window.destroy()
    if selected:
        print(selected[0])


if __name__ == "__main__":
    main()
