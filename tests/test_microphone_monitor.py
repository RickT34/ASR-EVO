from __future__ import annotations

import asyncio
import threading
import time
from dataclasses import replace

import numpy as np
import pytest

from asr_evo.audio import monitor
from asr_evo.audio.enhancement import AudioProcessingOptions, SpeechEnhancer
from asr_evo.audio.monitor import MicrophoneMonitor, MonitorSettings, PlaybackBuffer
from asr_evo.config import AppConfig, AudioConfig
from asr_evo.core.state import DictationState
from test_controller import _make_controller


def test_playback_buffer_bounds_latency_and_zero_fills_underruns():
    buffer = PlaybackBuffer(6)
    buffer.put(np.arange(4, dtype=np.float32))
    buffer.put(np.arange(4, 9, dtype=np.float32))
    assert buffer.frames == 6
    np.testing.assert_array_equal(buffer.read(4), [3, 4, 5, 6])
    np.testing.assert_array_equal(buffer.read(4), [7, 8, 0, 0])
    assert buffer.frames == 0


def test_monitor_adjusts_gain_without_reopening_audio_devices(monkeypatch):
    opened = []
    exited = []
    ready = threading.Event()
    monkeypatch.setattr(monitor, '_stream_sample_rate', lambda *a, **kw: 48000)
    monkeypatch.setattr(monitor.sd, 'query_devices', lambda *a: {'default_samplerate': 48000, 'max_output_channels': 2})

    class Output:
        def __init__(self, **kwargs):
            self.callback = kwargs['callback']
        def __enter__(self):
            opened.append('output')
            return self
        def __exit__(self, *args):
            exited.append('output')

    class Input:
        def __init__(self, **kwargs):
            self.callback = kwargs['callback']
            self.stop = threading.Event()
        def __enter__(self):
            opened.append('input')
            def feed():
                while not self.stop.wait(.005):
                    self.callback(np.ones((960, 1), dtype=np.float32) * .01, 960, None, None)
                    ready.set()
            self.thread = threading.Thread(target=feed)
            self.thread.start()
            return self
        def __exit__(self, *args):
            self.stop.set()
            self.thread.join()
            exited.append('input')

    monkeypatch.setattr(monitor.sd, 'OutputStream', Output)
    monkeypatch.setattr(monitor.sd, 'InputStream', Input)
    engine = MicrophoneMonitor()
    settings = MonitorSettings('', '', AudioProcessingOptions(), .2)
    engine.configure(settings)
    try:
        assert ready.wait(1)
        engine.configure(replace(settings, processing=AudioProcessingOptions(input_gain_db=6)))
        for _ in range(100):
            status = engine.snapshot()
            if status['output_db'] > -35:
                break
            time.sleep(.005)
        assert status['input_db'] == pytest.approx(-40, abs=.1)
        assert status['output_db'] == pytest.approx(-34, abs=.1)
        assert opened == ['output', 'input']
        assert not status['error']
    finally:
        engine.stop()
    assert exited == ['input', 'output']
    assert not engine.snapshot()['running']
    assert engine._thread is None


def test_monitor_device_failure_is_reported_and_stop_is_idempotent(monkeypatch):
    monkeypatch.setattr(monitor, '_stream_sample_rate', lambda *a, **kw: 48000)
    def fail(*args):
        raise RuntimeError('missing output')
    monkeypatch.setattr(monitor.sd, 'query_devices', fail)
    engine = MicrophoneMonitor()
    engine.configure(MonitorSettings('', '', AudioProcessingOptions()))
    engine.stop()
    assert engine.snapshot()['error'] == 'missing output'
    engine.stop()


def test_live_level_update_preserves_processor_state():
    processor = SpeechEnhancer(16000, AudioProcessingOptions())
    processor.update_levels(6, .5)
    result = processor.process(np.ones((160, 1), dtype=np.float32) * .01)
    np.testing.assert_allclose(result, .01 * 10**(.3), atol=1e-7)
    assert processor.options.denoise_mix == .5
    processor.close()


async def test_controller_opens_one_test_window_and_blocks_dictation(tmp_path):
    controller, deps = _make_controller(tmp_path)
    opened = asyncio.Event()
    release = asyncio.Event()
    seen = []
    async def test_window(audio, save):
        seen.append(audio)
        opened.set()
        await release.wait()
    controller.dependencies.microphone_tester = test_window
    controller.open_microphone_test()
    await asyncio.wait_for(opened.wait(), 1)
    controller.open_microphone_test()
    controller.start_dictation()
    assert len(seen) == 1
    assert controller.state.state == DictationState.IDLE
    assert not deps.recorder.audio_path.exists()
    release.set()
    await asyncio.wrap_future(controller._microphone_test_future)
    assert not controller._microphone_test_running()


async def test_controller_saves_only_audio_and_closes_window_on_shutdown(tmp_path):
    controller, deps = _make_controller(tmp_path)
    opened = asyncio.Event()
    closed = asyncio.Event()
    llm = controller.config.llm.model_dump()
    selected = AudioConfig(input_device='2', noise_suppression=True, input_gain_db=12, denoise_mix=.7)
    async def test_window(audio, save):
        save(selected)
        opened.set()
        try:
            await asyncio.Event().wait()
        finally:
            closed.set()
    controller.dependencies.microphone_tester = test_window
    controller.open_microphone_test()
    await asyncio.wait_for(opened.wait(), 1)
    saved = AppConfig.load(tmp_path/'config.toml')
    assert saved.audio == selected
    assert saved.llm.model_dump() == llm
    assert deps.recorder.processing == selected.processing_options()
    await controller.close_clients()
    assert closed.is_set()


def test_controller_cannot_open_microphone_test_while_recording(tmp_path):
    controller, _ = _make_controller(tmp_path)
    controller.state.state = DictationState.RECORDING
    controller.open_microphone_test()
    assert controller._microphone_test_future is None


async def test_dialog_bridge_saves_settings_and_ignores_updates_after_stop(tmp_path, monkeypatch):
    import sys
    from asr_evo.ui import microphone_test

    calls = []
    saved = []
    class Monitor:
        running = False
        def configure(self, settings):
            self.running = True
            calls.append(('configure', settings))
        def stop(self):
            self.running = False
            calls.append(('stop',))
        def snapshot(self):
            return {'running': self.running}
    monkeypatch.setattr(microphone_test, 'MicrophoneMonitor', Monitor)
    monkeypatch.setattr(microphone_test, '_devices', lambda: {'inputs': [], 'outputs': []})
    monkeypatch.setattr(microphone_test, '_review_child_command', lambda: ('unused', '-m', 'unused'))
    script = tmp_path/'dialog.py'
    script.write_text('''import json,sys
initial=json.loads(sys.stdin.readline())
audio=initial['audio'];audio['input_gain_db']=12
for kind in ['start','save','stop','update']:
 print(json.dumps({'type':kind,'audio':audio,'volume':0}),flush=True)
while True:
 response=json.loads(sys.stdin.readline())
 if response.get('type')=='saved':
  assert response['audio']['input_gain_db']==12
  break
print(json.dumps({'type':'close'}),flush=True)
''')
    spawn = asyncio.create_subprocess_exec
    async def fake_spawn(*args, **kwargs):
        return await spawn(sys.executable, str(script), **kwargs)
    monkeypatch.setattr(microphone_test.asyncio, 'create_subprocess_exec', fake_spawn)
    await asyncio.wait_for(microphone_test.show_microphone_test(AudioConfig(), saved.append), 3)
    assert len(saved) == 1 and saved[0].input_gain_db == 12
    assert [entry[0] for entry in calls] == ['configure', 'stop', 'stop']


async def test_cancelled_audio_command_finishes_before_cleanup():
    from asr_evo.ui.microphone_test import _audio_call
    entered = threading.Event()
    released = threading.Event()
    finished = threading.Event()
    def command():
        entered.set()
        released.wait(1)
        finished.set()
    task = asyncio.create_task(_audio_call(command))
    await asyncio.to_thread(entered.wait, 1)
    task.cancel()
    await asyncio.sleep(0)
    assert not task.done()
    released.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert finished.is_set()
