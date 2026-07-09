from __future__ import annotations

from asr_evo.audio.recorder import (
    InputDevice,
    _normalize_device_id,
    _stream_sample_rate,
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


def test_stream_sample_rate_uses_preferred_rate_when_supported(monkeypatch) -> None:
    checked = []

    def check_input_settings(*, device, channels, samplerate) -> None:
        checked.append((device, channels, samplerate))

    monkeypatch.setattr("asr_evo.audio.recorder.sd.check_input_settings", check_input_settings)

    assert _stream_sample_rate("2", channels=1, preferred_sample_rate=16000) == 16000
    assert checked == [(2, 1, 16000)]


def test_stream_sample_rate_falls_back_to_device_default(monkeypatch) -> None:
    def check_input_settings(*, device, channels, samplerate) -> None:
        if samplerate == 16000:
            raise RuntimeError("invalid sample rate")

    def query_devices(device, kind):
        assert device == 2
        assert kind == "input"
        return {"default_samplerate": 48000.0}

    monkeypatch.setattr("asr_evo.audio.recorder.sd.check_input_settings", check_input_settings)
    monkeypatch.setattr("asr_evo.audio.recorder.sd.query_devices", query_devices)

    assert _stream_sample_rate("2", channels=1, preferred_sample_rate=16000) == 48000
