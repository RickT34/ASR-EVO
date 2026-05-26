from __future__ import annotations

from asr_evo.audio.recorder import (
    InputDevice,
    _normalize_device_id,
    _stream_device_arg,
    input_device_label,
)


def test_normalize_input_device_id_treats_blank_as_system_default() -> None:
    assert _normalize_device_id(None) == ""
    assert _normalize_device_id("") == ""
    assert _normalize_device_id(" default ") == ""
    assert _normalize_device_id(3) == "3"


def test_stream_device_arg_preserves_default_and_named_devices() -> None:
    assert _stream_device_arg("") is None
    assert _stream_device_arg("4") == 4
    assert _stream_device_arg("External Microphone") == "External Microphone"


def test_input_device_label_marks_missing_selected_device() -> None:
    devices = [
        InputDevice(id="", name="系统默认输入", channels=0, is_default=True),
        InputDevice(id="1", name="Studio Mic", channels=2),
    ]

    assert input_device_label("", devices) == "系统默认输入（系统默认）"
    assert input_device_label("1", devices) == "Studio Mic"
    assert input_device_label("7", devices) == "输入设备 7（不可用）"
