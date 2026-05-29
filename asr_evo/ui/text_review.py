from __future__ import annotations

import asyncio
import sys
from collections.abc import Awaitable, Callable


ProcessFactory = Callable[..., Awaitable[asyncio.subprocess.Process]]


class TkTextReviewer:
    def __init__(
        self,
        *,
        process_factory: ProcessFactory = asyncio.create_subprocess_exec,
    ) -> None:
        self.process_factory = process_factory

    async def review(self, text: str) -> str | None:
        process = await self.process_factory(
            sys.executable,
            "-m",
            "asr_evo.ui.text_review",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate(text.encode("utf-8"))
        return parse_review_process_result(process.returncode, stdout, stderr)


def parse_review_process_result(returncode: int, stdout: bytes, stderr: bytes) -> str | None:
    if returncode == 0:
        return stdout.decode("utf-8")
    if returncode == 2:
        return None
    message = stderr.decode("utf-8", errors="replace").strip()
    if not message:
        message = f"text review dialog exited with code {returncode}"
    raise RuntimeError(message)


def show_text_review(initial_text: str) -> str | None:
    import tkinter as tk
    from tkinter.scrolledtext import ScrolledText

    result: dict[str, str | None] = {"text": None}
    cancelled = {"value": True}

    root = tk.Tk()
    root.title("确认文本")
    root.geometry("680x360")
    root.minsize(420, 240)
    root.attributes("-topmost", True)
    root.attributes("-alpha", 0.92)
    root.columnconfigure(0, weight=1)
    root.rowconfigure(0, weight=1)

    text_box = ScrolledText(root, wrap="word", undo=True)
    text_box.insert("1.0", initial_text)
    text_box.grid(row=0, column=0, sticky="nsew", padx=14, pady=(14, 8))

    buttons = tk.Frame(root)
    buttons.grid(row=1, column=0, sticky="ew", padx=14, pady=(0, 14))
    buttons.columnconfigure(0, weight=1)

    def confirm(event: object | None = None) -> str:
        result["text"] = text_box.get("1.0", "end-1c")
        cancelled["value"] = False
        root.destroy()
        return "break"

    def cancel(event: object | None = None) -> str:
        cancelled["value"] = True
        root.destroy()
        return "break"

    cancel_button = tk.Button(buttons, text="取消", command=cancel)
    cancel_button.grid(row=0, column=1, padx=(0, 8))
    ok_button = tk.Button(buttons, text="确定", command=confirm, default="active")
    ok_button.grid(row=0, column=2)

    root.bind("<Escape>", cancel)
    root.bind("<Command-Return>", confirm)
    root.bind("<Control-Return>", confirm)
    root.protocol("WM_DELETE_WINDOW", cancel)

    def focus_text() -> None:
        root.lift()
        root.focus_force()
        text_box.focus_set()
        text_box.mark_set("insert", "end-1c")
        text_box.see("insert")

    root.after(50, focus_text)
    root.mainloop()
    if cancelled["value"]:
        return None
    return result["text"] or ""


def main() -> int:
    try:
        result = show_text_review(sys.stdin.read())
    except Exception as exc:
        print(exc, file=sys.stderr)
        return 1
    if result is None:
        return 2
    sys.stdout.write(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
