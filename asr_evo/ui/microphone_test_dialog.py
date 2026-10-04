"""Standard-library-only Tk worker: audio remains in the app's Python environment."""
from __future__ import annotations

import json
import queue
import sys
import threading

from asr_evo.ui.text_review import _configure_tk_fonts, _send_stdout, configure_stdio_encoding


def show_microphone_test_dialog(initial: dict) -> None:
    import tkinter as tk
    from tkinter import ttk

    root = tk.Tk(className="ae_microphone_test")
    _configure_tk_fonts(root)
    root.title("麦克风测试")
    if sys.platform == "linux":
        root.attributes("-type", "dialog")
    root.geometry("740x650")
    root.minsize(680, 620)
    frame = ttk.Frame(root, padding=18)
    frame.pack(fill="both", expand=True)
    frame.columnconfigure(1, weight=1)
    incoming = queue.Queue()
    saved = dict(initial["audio"])
    active = False
    pending = None
    input_ids = []
    output_ids = []
    input_var = tk.StringVar()
    output_var = tk.StringVar()
    gain = tk.DoubleVar(value=saved.get("input_gain_db", 0))
    mix = tk.DoubleVar(value=saved.get("denoise_mix", .85))
    denoise = tk.BooleanVar(value=saved.get("noise_suppression", False))
    volume = tk.DoubleVar(value=.2)
    gain_label = tk.StringVar()
    mix_label = tk.StringVar()
    volume_label = tk.StringVar()
    status = tk.StringVar(value="未开始测试")
    notice = tk.StringVar(value="调整仅用于试听；点击保存后应用于听写。")
    input_level = tk.DoubleVar(value=0)
    output_level = tk.DoubleVar(value=0)
    input_db = tk.StringVar(value="−96 dBFS")
    output_db = tk.StringVar(value="−96 dBFS")

    ttk.Label(frame, text="麦克风测试", font="TkHeadingFont").grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 8))
    ttk.Label(frame, text="建议佩戴耳机，避免扬声器声音被麦克风再次收录产生啸叫。", wraplength=650).grid(row=1, column=0, columnspan=3, sticky="w", pady=(0, 14))
    ttk.Label(frame, text="输入设备").grid(row=2, column=0, sticky="w")
    inputs = ttk.Combobox(frame, textvariable=input_var, state="readonly", font="TkTextFont")
    inputs.grid(row=2, column=1, columnspan=2, sticky="ew", pady=5)
    ttk.Label(frame, text="监听输出").grid(row=3, column=0, sticky="w")
    outputs = ttk.Combobox(frame, textvariable=output_var, state="readonly", font="TkTextFont")
    outputs.grid(row=3, column=1, columnspan=2, sticky="ew", pady=5)

    def device_id(widget, ids):
        index = widget.current()
        return ids[index] if 0 <= index < len(ids) else ""

    def audio_values():
        return {**saved, "input_device": device_id(inputs, input_ids),
                "noise_suppression": denoise.get(), "input_gain_db": round(gain.get(), 1),
                "denoise_mix": round(mix.get(), 2)}

    def send_settings(kind):
        _send_stdout({"type": kind, "audio": audio_values(),
                      "output_device": device_id(outputs, output_ids), "volume": volume.get()})

    def apply_update():
        nonlocal pending
        pending = None
        if active:
            send_settings("update")

    def changed(*_):
        nonlocal pending
        gain_label.set(f"{gain.get():+.1f} dB")
        mix_label.set(f"{mix.get():.0%}")
        volume_label.set(f"{volume.get():.0%}")
        if pending is not None:
            root.after_cancel(pending)
        pending = root.after(150, apply_update) if active else None

    def slider(row, title, variable, minimum, maximum, label):
        ttk.Label(frame, text=title).grid(row=row, column=0, sticky="w")
        control = ttk.Scale(frame, variable=variable, from_=minimum, to=maximum, command=changed)
        control.grid(row=row, column=1, sticky="ew", padx=12, pady=10)
        ttk.Label(frame, textvariable=label, width=9).grid(row=row, column=2, sticky="e")
        return control

    slider(4, "输入增益", gain, -12, 36, gain_label)
    ttk.Checkbutton(frame, text="启用 RNNoise 降噪", variable=denoise, command=changed).grid(row=5, column=0, columnspan=3, sticky="w", pady=8)
    slider(6, "降噪混合比例", mix, 0, 1, mix_label)
    slider(7, "监听音量", volume, 0, 1, volume_label)
    ttk.Label(frame, text="监听音量只影响耳机／扬声器，不改变录音文件音量。", wraplength=650).grid(row=8, column=0, columnspan=3, sticky="w", pady=(0, 10))
    for row, title, value, db in [(9, "原始输入", input_level, input_db), (10, "处理后", output_level, output_db)]:
        ttk.Label(frame, text=title).grid(row=row, column=0, sticky="w")
        ttk.Progressbar(frame, variable=value, maximum=96).grid(row=row, column=1, sticky="ew", padx=12, pady=8)
        ttk.Label(frame, textvariable=db, width=12).grid(row=row, column=2, sticky="e")
    ttk.Label(frame, textvariable=status).grid(row=11, column=0, columnspan=3, sticky="w", pady=6)
    ttk.Label(frame, textvariable=notice, wraplength=650).grid(row=12, column=0, columnspan=3, sticky="w", pady=6)

    def set_active(value):
        nonlocal active
        active = value
        start_button.configure(text="停止监听" if active else "开始监听")

    def toggle():
        if active:
            set_active(False)
            _send_stdout({"type": "stop"})
        else:
            set_active(True)
            status.set("正在打开音频设备…")
            send_settings("start")

    def choose(widget, ids, values, selected):
        ids[:] = [str(item["id"]) for item in values]
        labels = [f"{item['id'] or '默认'} · {item['label']}" for item in values]
        if str(selected) not in ids:
            ids.append(str(selected))
            labels.append(f"{selected}（不可用）")
        widget.configure(values=labels)
        widget.current(ids.index(str(selected)))

    def restore():
        selected = str(saved.get("input_device", ""))
        if selected in input_ids:
            inputs.current(input_ids.index(selected))
        gain.set(saved.get("input_gain_db", 0))
        mix.set(saved.get("denoise_mix", .85))
        denoise.set(saved.get("noise_suppression", False))
        changed()

    def close(*_):
        _send_stdout({"type": "close"})
        root.destroy()

    buttons = ttk.Frame(frame)
    buttons.grid(row=13, column=0, columnspan=3, sticky="ew", pady=(12, 0))
    start_button = ttk.Button(buttons, text="开始监听", command=toggle)
    start_button.pack(side="left")
    ttk.Button(buttons, text="刷新设备", command=lambda: _send_stdout({"type": "refresh"})).pack(side="left", padx=6)
    ttk.Button(buttons, text="恢复已保存", command=restore).pack(side="left")
    confirmation = ttk.Frame(frame)
    confirmation.grid(row=14, column=0, columnspan=3, sticky="e", pady=(8, 0))
    ttk.Button(confirmation, text="保存设置", command=lambda: send_settings("save")).pack(side="left", padx=(0, 8))
    ttk.Button(confirmation, text="关闭", command=close).pack(side="left")
    inputs.bind("<<ComboboxSelected>>", changed)
    outputs.bind("<<ComboboxSelected>>", changed)
    choose(inputs, input_ids, initial["inputs"], saved.get("input_device", ""))
    choose(outputs, output_ids, initial["outputs"], "")
    changed()

    def read():
        for line in sys.stdin:
            try:
                incoming.put(json.loads(line))
            except ValueError:
                continue
        incoming.put({"type": "disconnected"})

    def poll():
        nonlocal saved
        while not incoming.empty():
            message = incoming.get_nowait()
            kind = message.get("type")
            if kind == "levels":
                for key, meter, label in [("input_db", input_level, input_db), ("output_db", output_level, output_db)]:
                    value = float(message.get(key, -96))
                    meter.set(max(0, min(96, value + 96)))
                    label.set(f"{value:.1f} dBFS")
                set_active(bool(message.get("running")))
                if message.get("error"):
                    set_active(False)
                    status.set("测试已停止")
                    notice.set(str(message["error"]))
                elif message.get("running") and active:
                    status.set(f"正在监听 · 输入 {message.get('input_rate', '…')} Hz · 输出 {message.get('output_rate', '…')} Hz")
                elif not active:
                    status.set("未开始测试")
            elif kind == "saved":
                saved = dict(message["audio"])
                notice.set("设置已保存，将用于之后的听写。")
            elif kind == "error":
                notice.set(str(message.get("message", "操作失败")))
            elif kind == "devices":
                selected_in, selected_out = device_id(inputs, input_ids), device_id(outputs, output_ids)
                choose(inputs, input_ids, message["inputs"], selected_in)
                choose(outputs, output_ids, message["outputs"], selected_out)
            elif kind == "disconnected":
                root.destroy()
                return
        root.after(50, poll)

    threading.Thread(target=read, daemon=True).start()
    root.update_idletasks()
    width = max(740, root.winfo_reqwidth())
    height = max(520, root.winfo_reqheight() + 20)
    x = max(0, (root.winfo_screenwidth() - width) // 2)
    y = max(40, (root.winfo_screenheight() - height) // 2)
    root.geometry(f"{width}x{height}+{x}+{y}")
    root.minsize(width, height)
    root.after(50, poll)
    root.protocol("WM_DELETE_WINDOW", close)
    root.bind("<Escape>", close)
    root.mainloop()


def main() -> None:
    configure_stdio_encoding()
    initial = json.loads(sys.stdin.readline())
    show_microphone_test_dialog(initial)


if __name__ == "__main__":
    main()
