from __future__ import annotations

import asyncio
import json
from collections.abc import Callable

import sounddevice as sd

from asr_evo.audio.monitor import MicrophoneMonitor, MonitorSettings
from asr_evo.audio.recorder import list_input_devices
from asr_evo.config import AudioConfig
from asr_evo.ui.text_review import (
    _review_child_command, _review_child_process_options, _write_json_line,
)


def _devices() -> dict:
    inputs = [{"id": device.id, "label": device.label} for device in list_input_devices()]
    outputs = [{"id": "", "label": "系统默认输出"}]
    outputs.extend({"id": str(index), "label": str(device["name"])}
                   for index, device in enumerate(sd.query_devices()) if device["max_output_channels"] > 0)
    return {"inputs": inputs, "outputs": outputs}


async def show_microphone_test(audio: AudioConfig, save: Callable[[AudioConfig], None]) -> None:
    devices = await asyncio.to_thread(_devices)
    process = await asyncio.create_subprocess_exec(
        *_review_child_command()[:-1], "asr_evo.ui.microphone_test_dialog",
        **_review_child_process_options(),
    )
    monitor = MicrophoneMonitor()
    meters = None

    async def publish():
        while True:
            await _write_json_line(process.stdin, {"type": "levels", **monitor.snapshot()})
            await asyncio.sleep(0.1)

    try:
        await _write_json_line(process.stdin, {"type": "init", "audio": audio.model_dump(), **devices})
        meters = asyncio.create_task(publish())
        while line := await process.stdout.readline():
            message = json.loads(line)
            command = message.get("type")
            if command == "close":
                return
            try:
                if command in {"start", "update", "save"}:
                    configured = AudioConfig.model_validate(message["audio"])
                    if command == "save":
                        save(configured)
                        await _write_json_line(process.stdin, {"type": "saved", "audio": configured.model_dump()})
                    elif command == "start" or monitor.snapshot()["running"]:
                        settings = MonitorSettings(
                            str(configured.input_device), str(message.get("output_device", "")),
                            configured.processing_options(), float(message.get("volume", 0.2)),
                        )
                        await _audio_call(monitor.configure, settings)
                elif command == "stop":
                    await _audio_call(monitor.stop)
                elif command == "refresh":
                    await _write_json_line(process.stdin, {"type": "devices", **await asyncio.to_thread(_devices)})
                else:
                    raise ValueError(f"未知麦克风测试命令：{command}")
            except Exception as exc:
                await _write_json_line(process.stdin, {"type": "error", "message": str(exc)})
        code = await process.wait()
        if code:
            detail = (await process.stderr.read()).decode("utf-8", errors="replace")
            raise RuntimeError(f"麦克风测试窗口退出 ({code})：{detail}")
    finally:
        if meters is not None:
            meters.cancel()
            await asyncio.gather(meters, return_exceptions=True)
        try:
            await _audio_call(monitor.stop)
        finally:
            if process.returncode is None:
                try:
                    process.kill()
                except ProcessLookupError:
                    pass
            await process.communicate()


async def _audio_call(function, *args):
    # A cancelled window must wait for a pending device switch before final stop.
    task = asyncio.create_task(asyncio.to_thread(function, *args))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        await task
        raise
