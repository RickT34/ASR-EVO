from __future__ import annotations

import ctypes.util
from collections import deque
from types import SimpleNamespace

import numpy as np
import pytest
import soundfile as sf

from asr_evo.audio import enhancement
from asr_evo.audio.enhancement import AudioProcessingOptions, SpeechEnhancer
from asr_evo.audio.enhance_file import enhance_file


class DelayedLibrary:
    """Stand-in with RNNoise 0.2's two-frame latency, without signal modification."""
    def __init__(self):
        self.pending = deque([np.zeros(480, dtype=np.float32) for _ in range(2)])
        self.destroyed = False

    def rnnoise_get_frame_size(self):
        return 480

    def rnnoise_create(self, model):
        return 1

    def rnnoise_destroy(self, state):
        self.destroyed = True

    def rnnoise_process_frame(self, state, output, source):
        self.pending.append(np.ctypeslib.as_array(source, shape=(480,)).copy())
        np.ctypeslib.as_array(output, shape=(480,))[:] = self.pending.popleft()
        return 0.5


@pytest.mark.parametrize('length', [0, 1, 479, 480, 481, 959, 960, 961, 1601, 16000])
def test_filter_alignment_and_tail_preserve_every_sample(monkeypatch, length):
    library = DelayedLibrary()
    monkeypatch.setattr(enhancement, '_rnnoise_library', lambda: library)
    processor = SpeechEnhancer(48000, AudioProcessingOptions(True, 0, 0.85))
    source = np.random.default_rng(17).uniform(-0.2, 0.2, size=(length, 1)).astype(np.float32)
    output = [processor.process(source[i:i+317]) for i in range(0, length, 317)]
    output.append(processor.finish())
    np.testing.assert_allclose(np.concatenate(output), source, atol=1e-7)
    assert processor.finish().shape == (0, 1)
    processor.close()
    assert library.destroyed


def test_disabled_processing_is_exact_bypass():
    processor = SpeechEnhancer(16000, AudioProcessingOptions())
    source = np.linspace(-1, 1, 3200, dtype=np.float32)[:, None]
    np.testing.assert_array_equal(processor.process(source), source)
    assert processor.finish().shape == (0, 1)
    processor.close()


def test_gain_limiter_protects_unexpected_loud_input():
    processor = SpeechEnhancer(48000, AudioProcessingOptions(input_gain_db=24))
    quiet = np.full((4800, 1), .001, dtype=np.float32)
    np.testing.assert_allclose(processor.process(quiet), quiet * 10**(24/20), atol=1e-7)
    loud = np.full((4800, 1), .8, dtype=np.float32)
    assert np.max(np.abs(processor.process(loud))) <= .981
    assert np.isfinite(processor.process(quiet)).all()
    processor.close()


def test_real_rnnoise_suppresses_stationary_noise_and_preserves_duration():
    if not ctypes.util.find_library('rnnoise'):
        pytest.skip('RNNoise system library is optional')
    processor = SpeechEnhancer(48000, AudioProcessingOptions(True, 0, 1))
    noise = np.random.default_rng(7).normal(0, .01, (48000*2, 1)).astype(np.float32)
    try:
        output = [processor.process(noise[i:i+4800]) for i in range(0, len(noise), 4800)]
        output.append(processor.finish())
        result = np.concatenate(output)
    finally:
        processor.close()
    assert result.shape == noise.shape
    assert np.sqrt(np.mean(result[24000:]**2)) < np.sqrt(np.mean(noise[24000:]**2)) * .8


def test_missing_rnnoise_is_explicit_and_gain_only_still_works(monkeypatch):
    monkeypatch.setattr(ctypes.util, 'find_library', lambda _: None)
    with pytest.raises(RuntimeError, match='RNNoise'):
        SpeechEnhancer(48000, AudioProcessingOptions(True))
    processor = SpeechEnhancer(16000, AudioProcessingOptions(input_gain_db=6))
    processor.close()


def test_file_enhancement_preserves_original_and_refuses_overwrite(tmp_path, monkeypatch):
    monkeypatch.setattr(enhancement, '_rnnoise_library', DelayedLibrary)
    path = tmp_path/'source.wav'
    source = np.random.default_rng(3).uniform(-.05, .05, (4301, 1)).astype(np.float32)
    sf.write(path, source, 48000)
    original = path.read_bytes()
    result = enhance_file(path, tmp_path/'output.wav', AudioProcessingOptions(True, 6))
    assert path.read_bytes() == original
    assert sf.info(result.path).frames == len(source)
    assert result.duration_seconds == len(source)/48000
    with pytest.raises(ValueError):
        enhance_file(path, path, AudioProcessingOptions())
    with pytest.raises(FileExistsError):
        enhance_file(path, result.path, AudioProcessingOptions())


async def test_recorder_stream_and_saved_audio_share_processed_frames(tmp_path, monkeypatch):
    from asr_evo.audio import recorder
    from asr_evo.audio.pcm import PCM16StreamEncoder

    monkeypatch.setattr(enhancement, '_rnnoise_library', DelayedLibrary)
    monkeypatch.setattr(recorder, '_stream_sample_rate', lambda *a, **kw: 48000)
    original = np.random.default_rng(4).uniform(-.01, .01, (1927, 1)).astype(np.float32)
    options = AudioProcessingOptions(True, 6, .85)
    instance = recorder.SoundDeviceRecorder(processing=options)
    in_callback = False
    process = SpeechEnhancer.process

    def checked_process(self, frames):
        assert not in_callback, 'DSP must not run on the audio callback'
        return process(self, frames)

    monkeypatch.setattr(SpeechEnhancer, 'process', checked_process)

    class Stream:
        def __init__(self, **kwargs):
            self.callback = kwargs['callback']
        def __enter__(self):
            nonlocal in_callback
            for i in range(0, len(original), 479):
                frames = original[i:i+479]
                in_callback = True
                self.callback(frames, len(frames), None, SimpleNamespace(input_overflow=False))
                in_callback = False
            instance.stop()
            return self
        def __exit__(self, *args):
            pass

    monkeypatch.setattr(recorder.sd, 'InputStream', Stream)
    sent = []
    clip = await instance.record_until_stopped(sent.append)
    try:
        saved, rate = sf.read(clip.path, dtype='float32', always_2d=True)
        assert rate == 48000 and len(saved) == len(original)
        np.testing.assert_allclose(saved, original * 10**(6/20), atol=1/32768)
        encoder = PCM16StreamEncoder(rate)
        expected = encoder.encode(saved) + encoder.finish()
        np.testing.assert_allclose(np.frombuffer(b''.join(sent), dtype='<i2'),
                                   np.frombuffer(expected, dtype='<i2'), atol=2)
    finally:
        clip.path.unlink()


@pytest.mark.parametrize('sample_rate', [16000, 44100])
def test_resampling_keeps_duration_and_flushes_filter_state(monkeypatch, sample_rate):
    import soxr

    monkeypatch.setattr(enhancement, '_rnnoise_library', DelayedLibrary)
    samples = np.random.default_rng(11).uniform(-.1, .1, (sample_rate+137, 1)).astype(np.float32)
    processor = SpeechEnhancer(sample_rate, AudioProcessingOptions(True))
    try:
        output = [processor.process(samples[i:i+317]) for i in range(0, len(samples), 317)]
        output.append(processor.finish())
    finally:
        processor.close()
    expected = soxr.resample(samples[:, 0], sample_rate, 48000)
    result = np.concatenate(output)[:, 0]
    np.testing.assert_allclose(result, expected, atol=1e-6)


async def test_processing_initialization_failure_does_not_stop_next_recording(monkeypatch):
    from asr_evo.audio.recorder import SoundDeviceRecorder

    instance = SoundDeviceRecorder()
    def fail(*args):
        raise RuntimeError('initialization failed')
    monkeypatch.setattr(instance, '_record_until_stopped_sync', fail)
    with pytest.raises(RuntimeError, match='initialization failed'):
        await instance.record_until_stopped()
    assert not instance._stop_requested


@pytest.mark.parametrize('overflow_indices', [[], [1], [0, 1, 2]])
async def test_input_overflow_retains_current_audio_and_continues(tmp_path, monkeypatch, caplog, overflow_indices):
    from asr_evo.audio import recorder

    instance = recorder.SoundDeviceRecorder()
    monkeypatch.setattr(recorder, '_stream_sample_rate', lambda *a, **kw: 16000)
    chunks = [np.full((160, 1), value, dtype=np.float32) for value in (.01, .02, .03)]
    stream_options = {}
    class Stream:
        def __init__(self, **kwargs):
            stream_options.update(kwargs)
        def __enter__(self):
            for index, frames in enumerate(chunks):
                stream_options['callback'](frames, len(frames), None,
                                          SimpleNamespace(input_overflow=index in overflow_indices))
                assert not instance._stop_event.is_set(), 'Overflow must not stop dictation'
            instance.stop()
            return self
        def __exit__(self, *args):
            pass
    monkeypatch.setattr(recorder.sd, 'InputStream', Stream)
    streamed = []
    clip = await instance.record_until_stopped(streamed.append)
    try:
        assert stream_options['latency'] == 'high'
        saved, rate = sf.read(clip.path, dtype='float32', always_2d=True)
        expected = np.concatenate(chunks)
        assert rate == 16000 and len(saved) == len(expected)
        np.testing.assert_allclose(saved, expected, atol=1/32768)
        assert len(b''.join(streamed)) == len(expected) * 2
        warnings = [item for item in caplog.records if '输入溢出' in item.message]
        assert len(warnings) == (1 if overflow_indices else 0)
        if warnings:
            assert f'{len(overflow_indices)} 次' in warnings[0].message
    finally:
        clip.path.unlink()
    assert not instance._stop_requested


async def test_processing_queue_overflow_still_stops_instead_of_silent_dropping(monkeypatch):
    from asr_evo.audio import recorder

    instance = recorder.SoundDeviceRecorder()
    monkeypatch.setattr(recorder, '_stream_sample_rate', lambda *a, **kw: 16000)
    frame = np.zeros((160, 1), dtype=np.float32)
    class Stream:
        def __init__(self, **kwargs):
            self.callback = kwargs['callback']
        def __enter__(self):
            # Deliberately block processing until the bounded callback queue fills.
            for _ in range(201):
                self.callback(frame, len(frame), None, SimpleNamespace(input_overflow=False))
            assert instance._stop_event.is_set()
            return self
        def __exit__(self, *args):
            pass
    monkeypatch.setattr(recorder.sd, 'InputStream', Stream)
    with pytest.raises(RuntimeError, match='音频处理积压'):
        await instance.record_until_stopped()
    assert not instance._stop_requested
