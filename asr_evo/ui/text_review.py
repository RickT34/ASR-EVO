from __future__ import annotations

import asyncio
import json
import sys
import threading
from dataclasses import asdict
from typing import Any

from asr_evo.core.ports import (
    TextReviewPreviewRequest,
    TextReviewPreviewer,
    TextReviewRequest,
    TextReviewResult,
    TextReviewSaveRequest,
    TextReviewSaver,
    TextReviewStyle,
)


class ReviewProcessProtocolError(RuntimeError):
    pass


ProcessFactory = Any


class TkTextReviewer:
    def __init__(
        self,
        *,
        process_factory: ProcessFactory = asyncio.create_subprocess_exec,
    ) -> None:
        self.process_factory = process_factory

    async def review(
        self,
        request: TextReviewRequest,
        previewer: TextReviewPreviewer,
        saver: TextReviewSaver,
    ) -> TextReviewResult | None:
        process = await self.process_factory(
            sys.executable,
            "-m",
            "asr_evo.ui.text_review",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        if process.stdin is None or process.stdout is None:
            raise ReviewProcessProtocolError("text review process pipes were not created")
        await _write_json_line(process.stdin, {"type": "init", "request": asdict(request)})

        while True:
            line = await process.stdout.readline()
            if not line:
                stderr = await _read_process_stderr(process)
                raise ReviewProcessProtocolError(
                    parse_review_process_error(process.returncode, stderr)
                )
            message = _loads_json_line(line)
            message_type = message.get("type")
            if message_type == "preview":
                await self._handle_preview_request(process.stdin, message, previewer)
            elif message_type == "save":
                await self._handle_save_request(process.stdin, message, saver)
            elif message_type == "confirm":
                await _close_stdin(process.stdin)
                await _wait_process(process)
                return _review_result_from_message(message)
            elif message_type == "cancel":
                await _close_stdin(process.stdin)
                await _wait_process(process)
                return None
            else:
                raise ReviewProcessProtocolError(f"unexpected review message: {message_type}")

    async def _handle_preview_request(
        self,
        stdin: asyncio.StreamWriter,
        message: dict[str, Any],
        previewer: TextReviewPreviewer,
    ) -> None:
        request_id = str(message.get("id", ""))
        try:
            result = await previewer(
                TextReviewPreviewRequest(
                    style_id=str(message.get("style_id", "")),
                    prompt_instruction=str(message.get("prompt_instruction", "")),
                )
            )
        except Exception as exc:
            await _write_json_line(
                stdin,
                {
                    "type": "preview_error",
                    "id": request_id,
                    "message": str(exc),
                },
            )
            return
        await _write_json_line(
            stdin,
            {
                "type": "preview_result",
                "id": request_id,
                "polished_text": result,
            },
        )

    async def _handle_save_request(
        self,
        stdin: asyncio.StreamWriter,
        message: dict[str, Any],
        saver: TextReviewSaver,
    ) -> None:
        request_id = str(message.get("id", ""))
        try:
            result = await saver(
                TextReviewSaveRequest(
                    style_id=str(message.get("style_id", "")),
                    prompt_instruction=str(message.get("prompt_instruction", "")),
                )
            )
        except Exception as exc:
            await _write_json_line(
                stdin,
                {
                    "type": "save_error",
                    "id": request_id,
                    "message": str(exc),
                },
            )
            return
        await _write_json_line(
            stdin,
            {
                "type": "save_result",
                "id": request_id,
                "message": result.message,
            },
        )


async def _write_json_line(stdin: asyncio.StreamWriter, message: dict[str, Any]) -> None:
    stdin.write((json.dumps(message, ensure_ascii=False) + "\n").encode("utf-8"))
    await stdin.drain()


async def _close_stdin(stdin: asyncio.StreamWriter) -> None:
    stdin.close()
    wait_closed = getattr(stdin, "wait_closed", None)
    if wait_closed is not None:
        await wait_closed()


async def _wait_process(process: asyncio.subprocess.Process) -> None:
    returncode = await process.wait()
    if returncode not in (0, 2):
        stderr = await _read_process_stderr(process)
        raise RuntimeError(parse_review_process_error(returncode, stderr))


async def _read_process_stderr(process: asyncio.subprocess.Process) -> bytes:
    stderr = process.stderr
    if stderr is None:
        return b""
    return await stderr.read()


def _loads_json_line(line: bytes) -> dict[str, Any]:
    try:
        value = json.loads(line.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise ReviewProcessProtocolError("invalid JSON from text review process") from exc
    if not isinstance(value, dict):
        raise ReviewProcessProtocolError("text review process returned a non-object message")
    return value


def _review_result_from_message(message: dict[str, Any]) -> TextReviewResult:
    return TextReviewResult(
        text=str(message.get("text", "")),
        polished_text=str(message.get("polished_text", "")),
        style_id=str(message.get("style_id", "")),
        prompt_instruction=str(message.get("prompt_instruction", "")),
    )


def parse_review_process_result(returncode: int, stdout: bytes, stderr: bytes) -> str | None:
    if returncode == 0:
        message = _loads_json_line(stdout) if stdout.strip().startswith(b"{") else None
        if message and message.get("type") == "confirm":
            return str(message.get("text", ""))
        return stdout.decode("utf-8")
    if returncode == 2:
        return None
    raise RuntimeError(parse_review_process_error(returncode, stderr))


def parse_review_process_error(returncode: int | None, stderr: bytes) -> str:
    message = stderr.decode("utf-8", errors="replace").strip()
    if not message:
        message = f"text review dialog exited with code {returncode}"
    return message


def show_text_review(request: TextReviewRequest) -> TextReviewResult | None:
    import tkinter as tk
    from tkinter import ttk
    from tkinter.scrolledtext import ScrolledText

    result: dict[str, TextReviewResult | None] = {"value": None}
    styles_by_id = {style.id: style for style in request.styles}
    current_style = styles_by_id.get(request.style_id) or (
        request.styles[0] if request.styles else TextReviewStyle("", "", request.prompt_instruction)
    )
    request_counter = {"value": 0}
    last_preview = {"text": request.polished_text}
    prompt_expanded = {"value": False}
    io_busy = {"value": False}
    pending_preview = {"value": False}
    prompt_after_id = {"value": ""}

    root = tk.Tk()
    root.title("确认文本")
    root.geometry("860x500")
    root.minsize(680, 420)
    root.attributes("-topmost", True)
    root.attributes("-alpha", 0.96)
    root.columnconfigure(0, weight=1)
    root.rowconfigure(0, weight=1)

    main = ttk.Frame(root, padding=12)
    main.grid(row=0, column=0, sticky="nsew")
    main.columnconfigure(0, weight=1)
    main.columnconfigure(1, weight=1)
    main.rowconfigure(1, weight=1)
    main.rowconfigure(3, weight=0)

    ttk.Label(main, text="转写原文").grid(row=0, column=0, sticky="w")
    ttk.Label(main, text="润色后文本").grid(row=0, column=1, sticky="w", padx=(10, 0))

    raw_box = ScrolledText(main, wrap="word", height=10)
    raw_box.insert("1.0", request.raw_text)
    raw_box.configure(state="disabled")
    raw_box.grid(row=1, column=0, sticky="nsew", pady=(4, 10))

    polished_box = ScrolledText(main, wrap="word", undo=True, height=10)
    polished_box.insert("1.0", request.polished_text)
    polished_box.grid(row=1, column=1, sticky="nsew", padx=(10, 0), pady=(4, 10))

    controls = ttk.Frame(main)
    controls.grid(row=2, column=0, columnspan=2, sticky="ew")
    controls.columnconfigure(1, weight=1)
    controls.columnconfigure(3, weight=0)
    controls.columnconfigure(4, weight=0)

    ttk.Label(controls, text="提示词").grid(row=0, column=0, sticky="w")
    toggle_prompt_button = ttk.Button(controls, text="显示提示词", command=lambda: toggle_prompt())
    toggle_prompt_button.grid(row=0, column=1, sticky="w", padx=(8, 0))
    style_var = tk.StringVar(value=current_style.id)
    style_box = ttk.Combobox(
        controls,
        textvariable=style_var,
        values=[style.id for style in request.styles],
        state="readonly" if request.styles else "disabled",
        width=24,
    )
    style_box.grid(row=0, column=2, sticky="e", padx=(10, 8))
    save_button = ttk.Button(controls, text="保存", command=lambda: request_save())
    save_button.grid(row=0, column=3, sticky="e")

    prompt_box = ScrolledText(main, wrap="word", undo=True, height=8)
    prompt_box.insert("1.0", current_style.prompt or request.prompt_instruction)
    prompt_box.grid(row=3, column=0, columnspan=2, sticky="nsew", pady=(4, 10))
    prompt_box.grid_remove()

    status_var = tk.StringVar(value="")
    status = ttk.Label(main, textvariable=status_var)
    status.grid(row=4, column=0, sticky="w")

    buttons = ttk.Frame(main)
    buttons.grid(row=4, column=1, sticky="e")

    def selected_style() -> TextReviewStyle:
        style_id = style_var.get()
        return styles_by_id.get(style_id) or current_style

    def set_polished_text(text: str) -> None:
        polished_box.delete("1.0", "end")
        polished_box.insert("1.0", text)
        polished_box.mark_set("insert", "end-1c")
        polished_box.see("insert")

    def set_busy(value: bool) -> None:
        io_busy["value"] = value
        state = "disabled" if value else "normal"
        save_button.configure(state=state)
        style_box.configure(state="disabled" if value else ("readonly" if request.styles else "disabled"))

    def request_preview(event: object | None = None) -> str:
        if io_busy["value"]:
            pending_preview["value"] = True
            return "break"
        request_counter["value"] += 1
        request_id = str(request_counter["value"])
        set_busy(True)
        status_var.set("正在预览...")
        style = selected_style()
        _send_stdout(
            {
                "type": "preview",
                "id": request_id,
                "style_id": style.id,
                "prompt_instruction": prompt_box.get("1.0", "end-1c"),
            }
        )
        threading.Thread(
            target=lambda: wait_for_preview_response(request_id),
            daemon=True,
        ).start()
        return "break"

    def schedule_preview() -> None:
        if prompt_after_id["value"]:
            root.after_cancel(prompt_after_id["value"])
        prompt_after_id["value"] = root.after(600, request_preview)

    def request_save(event: object | None = None) -> str:
        if io_busy["value"]:
            return "break"
        request_counter["value"] += 1
        request_id = str(request_counter["value"])
        set_busy(True)
        status_var.set("正在保存...")
        style = selected_style()
        _send_stdout(
            {
                "type": "save",
                "id": request_id,
                "style_id": style.id,
                "prompt_instruction": prompt_box.get("1.0", "end-1c"),
            }
        )
        threading.Thread(
            target=lambda: wait_for_save_response(request_id),
            daemon=True,
        ).start()
        return "break"

    def wait_for_preview_response(request_id: str) -> None:
        line = sys.stdin.readline()
        if not line:
            root.after(0, lambda: finish_preview_error("父进程已断开"))
            return
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            root.after(0, lambda: finish_preview_error("响应格式错误"))
            return
        if str(message.get("id", "")) != request_id:
            return
        root.after(0, lambda: finish_preview(message))

    def wait_for_save_response(request_id: str) -> None:
        line = sys.stdin.readline()
        if not line:
            root.after(0, lambda: finish_save_error("父进程已断开"))
            return
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            root.after(0, lambda: finish_save_error("响应格式错误"))
            return
        if str(message.get("id", "")) != request_id:
            return
        root.after(0, lambda: finish_save(message))

    def finish_preview(message: dict[str, Any]) -> None:
        set_busy(False)
        if message.get("type") == "preview_result":
            last_preview["text"] = str(message.get("polished_text", ""))
            set_polished_text(last_preview["text"])
            status_var.set("预览已更新")
            if pending_preview["value"]:
                pending_preview["value"] = False
                schedule_preview()
            return
        status_var.set(f"预览失败：{message.get('message', '未知错误')}")

    def finish_preview_error(message: str) -> None:
        set_busy(False)
        status_var.set(f"预览失败：{message}")

    def finish_save(message: dict[str, Any]) -> None:
        set_busy(False)
        if message.get("type") == "save_result":
            status_var.set(str(message.get("message", "已保存")))
            return
        status_var.set(f"保存失败：{message.get('message', '未知错误')}")

    def finish_save_error(message: str) -> None:
        set_busy(False)
        status_var.set(f"保存失败：{message}")

    def on_style_selected(event: object | None = None) -> None:
        style = selected_style()
        prompt_box.delete("1.0", "end")
        prompt_box.insert("1.0", style.prompt)
        prompt_box.edit_modified(False)
        request_preview()

    def on_prompt_modified(event: object | None = None) -> None:
        if prompt_box.edit_modified():
            prompt_box.edit_modified(False)
            schedule_preview()

    def toggle_prompt(event: object | None = None) -> str:
        prompt_expanded["value"] = not prompt_expanded["value"]
        if prompt_expanded["value"]:
            main.rowconfigure(3, weight=1)
            prompt_box.grid()
            toggle_prompt_button.configure(text="隐藏提示词")
        else:
            main.rowconfigure(3, weight=0)
            prompt_box.grid_remove()
            toggle_prompt_button.configure(text="显示提示词")
        return "break"

    def confirm(event: object | None = None) -> str:
        style = selected_style()
        prompt_instruction = prompt_box.get("1.0", "end-1c")
        polished_text = polished_box.get("1.0", "end-1c")
        result["value"] = TextReviewResult(
            text=polished_text,
            polished_text=last_preview["text"],
            style_id=style.id,
            prompt_instruction=prompt_instruction,
        )
        _send_stdout({"type": "confirm", **asdict(result["value"])})
        root.destroy()
        return "break"

    def cancel(event: object | None = None) -> str:
        _send_stdout({"type": "cancel"})
        root.destroy()
        return "break"

    cancel_button = ttk.Button(buttons, text="取消", command=cancel)
    cancel_button.grid(row=0, column=0, padx=(0, 8))
    ok_button = ttk.Button(buttons, text="确定", command=confirm, default="active")
    ok_button.grid(row=0, column=1)

    style_box.bind("<<ComboboxSelected>>", on_style_selected)
    prompt_box.bind("<<Modified>>", on_prompt_modified)
    root.bind("<Escape>", cancel)
    root.bind("<Command-Return>", confirm)
    root.bind("<Control-Return>", confirm)
    root.bind("<Command-r>", request_preview)
    root.bind("<Control-r>", request_preview)
    root.bind("<Command-s>", request_save)
    root.bind("<Control-s>", request_save)
    root.protocol("WM_DELETE_WINDOW", cancel)

    def focus_text() -> None:
        root.lift()
        root.focus_force()
        polished_box.focus_set()
        polished_box.mark_set("insert", "end-1c")
        polished_box.see("insert")

    root.after(50, focus_text)
    root.mainloop()
    return result["value"]


def _send_stdout(message: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(message, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def _request_from_message(message: dict[str, Any]) -> TextReviewRequest:
    payload = message.get("request")
    if not isinstance(payload, dict):
        raise ReviewProcessProtocolError("missing review request")
    styles = [
        TextReviewStyle(
            id=str(item.get("id", "")),
            label=str(item.get("label", "")),
            prompt=str(item.get("prompt", "")),
        )
        for item in payload.get("styles", [])
        if isinstance(item, dict)
    ]
    return TextReviewRequest(
        raw_text=str(payload.get("raw_text", "")),
        polished_text=str(payload.get("polished_text", "")),
        style_id=str(payload.get("style_id", "")),
        prompt_instruction=str(payload.get("prompt_instruction", "")),
        styles=styles,
        context=str(payload.get("context", "")),
    )


def main() -> int:
    try:
        init_line = sys.stdin.readline()
        if not init_line:
            raise ReviewProcessProtocolError("missing init message")
        request = _request_from_message(json.loads(init_line))
        result = show_text_review(request)
    except Exception as exc:
        print(exc, file=sys.stderr)
        return 1
    if result is None:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
