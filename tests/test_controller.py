from __future__ import annotations

import asyncio
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import pytest

from asr_evo.config import AppConfig, LLMProfileConfig
from asr_evo.core.context import ContextStore, DictationRecord
from asr_evo.core.controller import (
    DesktopControllerDependencies,
    DesktopDictationController,
    prepare_runtime_config,
)
from asr_evo.core.errors import PermissionDeniedError
from asr_evo.core.ports import (
    AppContext,
    AppStatsSummary,
    AudioClip,
    InputDeviceSummary,
    TextReviewPreviewRequest,
    TextReviewRequest,
    TextReviewResult,
    TextReviewSaveRequest,
    TextReviewSaveResult,
    Transcript,
)
from asr_evo.core.state import DictationState
from asr_evo.postprocess.styles import StyleDefinition
from asr_evo.storage.history import HistoryStore


async def test_controller_runs_pipeline_and_persists_history(tmp_path: Path) -> None:
    controller, deps = _make_controller(tmp_path)
    deps.recorder.audio_path.write_bytes(b"audio")

    await controller.run_pipeline_once()

    records = deps.history_store.recent()
    assert len(records) == 1
    assert records[0]["raw_text"] == "raw"
    assert records[0]["final_text"] == "final:raw"
    assert records[0]["user_edited_text"] == "final:raw"
    assert records[0]["has_audio"] is True
    assert Path(records[0]["audio_path"]).read_bytes() == b"audio"
    assert not deps.recorder.audio_path.exists()
    assert deps.tray.states[-1] == ("idle", "")
    assert deps.tray.history_records


async def test_controller_reviews_user_text_before_insert(tmp_path: Path) -> None:
    controller, deps = _make_controller(tmp_path)
    deps.text_reviewer.result = "user edited"
    deps.recorder.audio_path.write_bytes(b"audio")

    await controller.run_pipeline_once()

    records = deps.history_store.recent()
    assert deps.text_reviewer.seen[0].raw_text == "raw"
    assert deps.text_reviewer.seen[0].polished_text == "final:raw"
    assert deps.text_reviewer.seen[0].prompt_instruction == "polish"
    assert deps.inserter.text == "user edited"
    assert records[0]["final_text"] == "final:raw"
    assert records[0]["user_edited_text"] == "user edited"
    assert deps.tray.states[-1] == ("idle", "")


async def test_controller_previews_review_prompt_and_persists_selected_style(
    tmp_path: Path,
) -> None:
    controller, deps = _make_controller(tmp_path)
    deps.text_reviewer.preview_request = TextReviewPreviewRequest(
        style_id="情景/邮件",
        prompt_instruction="custom email prompt",
    )
    deps.text_reviewer.result = "user edited email"
    deps.recorder.audio_path.write_bytes(b"audio")

    await controller.run_pipeline_once()

    records = deps.history_store.recent()
    assert deps.llm_provider.calls == [
        ("raw", "", "polish"),
        ("raw", "", "custom email prompt"),
    ]
    assert deps.llm_provider.profiles == [None, "deep"]
    assert deps.inserter.text == "user edited email"
    assert records[0]["final_text"] == "preview:custom email prompt:raw"
    assert records[0]["user_edited_text"] == "user edited email"
    assert records[0]["style"] == "情景/邮件"


async def test_controller_saves_review_prompt_and_current_app_style(tmp_path: Path) -> None:
    controller, deps = _make_controller(tmp_path)
    deps.text_reviewer.save_request = TextReviewSaveRequest(
        style_id="情景/邮件",
        prompt_instruction="saved email prompt",
    )
    deps.recorder.audio_path.write_bytes(b"audio")

    await controller.run_pipeline_once()

    assert (tmp_path / "prompts" / "情景" / "邮件.md").read_text(encoding="utf-8") == (
        '+++\nllm_profile = "deep"\n+++\n\nsaved email prompt\n'
    )
    assert AppConfig.load(tmp_path / "config.toml").style.app_styles["com.example.App"] == "情景/邮件"
    assert deps.text_reviewer.save_result == TextReviewSaveResult(
        message="已保存提示词并绑定 Example"
    )
    assert deps.tray.selected_style_id == "情景/邮件"


async def test_controller_cancels_insert_when_review_is_cancelled(tmp_path: Path) -> None:
    controller, deps = _make_controller(tmp_path)
    deps.text_reviewer.cancelled = True
    deps.recorder.audio_path.write_bytes(b"audio")

    await controller.run_pipeline_once()

    records = deps.history_store.recent()
    assert len(records) == 1
    assert records[0]["has_audio"] is True
    assert records[0]["user_edited_text"] == ""
    assert deps.inserter.text is None
    assert ("idle", "已取消插入") in deps.tray.states


async def test_controller_inserts_directly_when_review_disabled(tmp_path: Path) -> None:
    controller, deps = _make_controller(tmp_path)
    controller.config.review.enabled = False
    deps.recorder.audio_path.write_bytes(b"audio")

    await controller.run_pipeline_once()

    records = deps.history_store.recent()
    assert deps.text_reviewer.seen == []
    assert deps.inserter.text == "final:raw"
    assert records[0]["user_edited_text"] == "final:raw"


async def test_controller_preserves_history_when_text_insertion_fails(tmp_path: Path) -> None:
    controller, deps = _make_controller(tmp_path)
    deps.inserter.error = RuntimeError("pasteboard insertion failed")
    deps.recorder.audio_path.write_bytes(b"audio")

    await controller.run_pipeline_once()

    records = deps.history_store.recent()
    assert len(records) == 1
    assert records[0]["raw_text"] == "raw"
    assert records[0]["final_text"] == "final:raw"
    assert controller.state.state == DictationState.ERROR
    assert deps.tray.error_feedback.raw_text_saved is True


async def test_controller_replaces_providers_and_closes_previous_clients(tmp_path: Path) -> None:
    controller, deps = _make_controller(tmp_path)
    previous_asr = deps.asr_provider
    previous_llm = deps.llm_provider
    next_asr = FakeASR()
    next_llm = FakeLLM()

    close_future = controller.replace_providers(next_asr, next_llm)
    await asyncio.wrap_future(close_future)

    assert controller.dependencies.asr_provider is next_asr
    assert controller.dependencies.llm_provider is next_llm
    assert previous_asr.closed is True
    assert previous_llm.closed is True


def test_controller_selects_style_and_binds_current_app(tmp_path: Path) -> None:
    controller, deps = _make_controller(tmp_path)

    controller.select_style("情景/邮件")

    assert controller.config.style.app_styles["com.example.App"] == "情景/邮件"
    assert deps.tray.selected_style_id == "情景/邮件"
    assert "style: 邮件" in deps.tray.states[-1][1]


def test_controller_copies_history_through_clipboard_port(tmp_path: Path) -> None:
    controller, deps = _make_controller(tmp_path)
    record = DictationRecord.create(
        started_at=datetime.now(UTC),
        raw_text="raw text",
        final_text="final text",
        style="通用润色",
        app_context=AppContext(bundle_id="com.example.App", app_name="Example"),
    )
    deps.history_store.add(record)

    controller.copy_history_final(record.id)

    assert deps.clipboard.text == "final text"
    assert deps.tray.states[-1] == ("idle", "已复制润色结果")


def test_controller_exports_history_audio(tmp_path: Path) -> None:
    controller, deps = _make_controller(tmp_path)
    source = tmp_path / "source.wav"
    source.write_bytes(b"recording")
    record = DictationRecord.create(
        started_at=datetime.now(UTC),
        raw_text="raw text",
        final_text="final text",
        style="通用润色",
        app_context=AppContext(bundle_id="com.example.App", app_name="Example"),
    )
    deps.history_store.add(
        record,
        audio=AudioClip(path=source, sample_rate=16000, duration_seconds=1),
    )

    controller.export_history_audio(record.id)

    assert deps.file_exporter.destination is not None
    assert deps.file_exporter.destination.read_bytes() == b"recording"
    assert deps.tray.states[-1] == ("idle", "已导出录音")


async def test_controller_retranscribes_and_repolishes_history_without_inserting(
    tmp_path: Path,
) -> None:
    controller, deps = _make_controller(tmp_path)
    source = tmp_path / "source.wav"
    source.write_bytes(b"recording")
    record = DictationRecord.create(
        started_at=datetime.now(UTC),
        raw_text="old raw",
        final_text="old final",
        style="通用润色",
        app_context=AppContext(bundle_id="com.example.App", app_name="Example"),
    )
    deps.history_store.add(
        record,
        audio=AudioClip(path=source, sample_rate=24000, duration_seconds=2),
    )
    deps.asr_provider.text = "new raw"

    await controller.reprocess_history_record(record.id, retranscribe=True)

    updated = deps.history_store.get(record.id)
    assert updated is not None
    assert updated["raw_text"] == "new raw"
    assert updated["final_text"] == "final:new raw"
    assert updated["user_edited_text"] == "final:new raw"
    assert deps.asr_provider.audios[0].sample_rate == 24000
    assert deps.inserter.text is None
    assert deps.tray.states[-1] == ("idle", "已重新转写并润色")


async def test_controller_repolishes_history_without_calling_asr(tmp_path: Path) -> None:
    controller, deps = _make_controller(tmp_path)
    record = DictationRecord.create(
        started_at=datetime.now(UTC),
        raw_text="saved raw",
        final_text="old final",
        style="情景/邮件",
        app_context=AppContext(bundle_id="com.example.App", app_name="Example"),
    )
    deps.history_store.add(record)

    await controller.reprocess_history_record(record.id, retranscribe=False)

    updated = deps.history_store.get(record.id)
    assert updated is not None
    assert updated["final_text"] == "final:saved raw"
    assert deps.asr_provider.audios == []
    assert deps.llm_provider.profiles[-1] == "deep"
    assert deps.tray.states[-1] == ("idle", "已重新润色")


def test_runtime_config_rejects_prompt_with_unknown_llm_profile(tmp_path: Path) -> None:
    prompts = tmp_path / "prompts"
    prompts.mkdir()
    (prompts / "unknown.md").write_text(
        '+++\nllm_profile = "missing"\n+++\n\nprompt\n',
        encoding="utf-8",
    )
    config = AppConfig()
    config.style.prompts_dir = str(prompts)

    with pytest.raises(ValueError, match="unknown -> missing"):
        prepare_runtime_config(config, "unknown")


async def test_controller_archives_audio_when_asr_fails(tmp_path: Path) -> None:
    controller, deps = _make_controller(tmp_path)
    deps.recorder.audio_path.write_bytes(b"audio")
    deps.asr_provider.error = RuntimeError("asr unavailable")

    await controller.run_pipeline_once()

    records = deps.history_store.recent()
    assert len(records) == 1
    assert records[0]["raw_text"] == ""
    assert records[0]["has_audio"] is True
    assert controller.state.state == DictationState.ERROR


def test_controller_applies_config_and_persists_it(tmp_path: Path) -> None:
    controller, deps = _make_controller(tmp_path)
    config = controller.config.model_copy(deep=True)
    config.control.port = 9876

    controller.apply_config(config, persist=True)

    assert (tmp_path / "config.toml").exists()
    assert AppConfig.load(tmp_path / "config.toml").control.port == 9876
    assert deps.applied_config is config


def test_controller_applies_config_callback_after_runtime_state(tmp_path: Path) -> None:
    controller, deps = _make_controller(tmp_path)
    config = controller.config.model_copy(deep=True)
    config.review.enabled = False

    controller.apply_config(config)

    assert deps.tray.review_enabled is False
    assert deps.applied_config is config


def test_controller_does_not_commit_config_when_runtime_rejects_it(tmp_path: Path) -> None:
    controller, deps = _make_controller(tmp_path)
    config = controller.config.model_copy(deep=True)
    config.control.port = 9876

    def reject_config(config: AppConfig) -> None:
        raise OSError("port in use")

    controller.dependencies = DesktopControllerDependencies(
        **{
            key: value
            for key, value in deps.__dict__.items()
            if key in DesktopControllerDependencies.__dataclass_fields__
        }
        | {"on_config_applied": reject_config}
    )

    with pytest.raises(OSError, match="port in use"):
        controller.apply_config(config, persist=True)

    assert controller.config.control.port != 9876
    assert not (tmp_path / "config.toml").exists()


def test_controller_validates_config_before_runtime_or_disk_changes(tmp_path: Path) -> None:
    controller, deps = _make_controller(tmp_path)
    config = controller.config.model_copy(deep=True)
    config.style.prompts_dir = str(tmp_path / "missing-prompts")
    callback_called = False

    def apply_runtime(config: AppConfig) -> None:
        nonlocal callback_called
        callback_called = True

    controller.dependencies.on_config_applied = apply_runtime

    with pytest.raises(RuntimeError, match="No prompt files found"):
        controller.apply_config(config, persist=True)

    assert callback_called is False
    assert controller.config.style.prompts_dir != config.style.prompts_dir
    assert not (tmp_path / "config.toml").exists()


def test_controller_handles_external_control_commands(tmp_path: Path) -> None:
    controller, deps = _make_controller(tmp_path)
    controller.state.state = DictationState.RECORDING

    busy_start = controller.handle_control_command("start")

    assert busy_start.ok is True
    assert busy_start.state == "recording"
    assert deps.tray.states[-1] == ("recording", "busy")
    stopped = controller.handle_control_command("stop")
    assert stopped.ok is True
    assert stopped.state == "recording"
    assert deps.recorder.stopped is True
    unsupported = controller.handle_control_command("missing")
    assert unsupported.ok is False
    assert unsupported.error == "unsupported command: missing"


def test_controller_does_not_reload_config_while_dictation_is_active(tmp_path: Path) -> None:
    controller, deps = _make_controller(tmp_path)
    controller.state.state = DictationState.POLISHING
    loaded = False

    def load_config() -> AppConfig:
        nonlocal loaded
        loaded = True
        return AppConfig()

    controller.dependencies.config_loader = load_config

    controller.reload_config()

    assert loaded is False
    assert deps.tray.states[-1] == ("polishing", "听写进行中，暂不能重新加载配置")


def test_controller_toggles_review_and_persists_config(tmp_path: Path) -> None:
    controller, deps = _make_controller(tmp_path)

    controller.toggle_review()

    assert controller.config.review.enabled is False
    assert deps.tray.review_enabled is False
    assert deps.tray.states[-1] == ("idle", "已关闭插入前确认")
    assert AppConfig.load(tmp_path / "config.toml").review.enabled is False


def test_controller_shows_error_when_permission_is_missing(tmp_path: Path) -> None:
    controller, deps = _make_controller(tmp_path, trusted=False)

    controller.check_permissions()

    assert controller.state.state == DictationState.ERROR
    assert deps.tray.error_feedback is not None


def _make_controller(
    tmp_path: Path,
    *,
    trusted: bool = True,
) -> tuple[DesktopDictationController, "_Deps"]:
    prompts = tmp_path / "prompts"
    prompts.mkdir()
    (prompts / "通用润色.md").write_text("polish", encoding="utf-8")
    scene = prompts / "情景"
    scene.mkdir()
    (scene / "邮件.md").write_text(
        '+++\nllm_profile = "deep"\n+++\n\nemail\n',
        encoding="utf-8",
    )
    config = AppConfig()
    config.llm.profiles["deep"] = LLMProfileConfig(
        base_url="https://deep.example.test/v1",
        model="deep-model",
        api_key_env="DEEP_API_KEY",
    )
    config.style.prompts_dir = str(prompts)
    deps = _Deps(
        tray=FakeTray(),
        recorder=FakeRecorder(tmp_path / "recording.wav"),
        asr_provider=FakeASR(),
        llm_provider=FakeLLM(),
        inserter=FakeInserter(),
        text_reviewer=FakeTextReviewer(),
        app_provider=FakeAppProvider(),
        history_store=HistoryStore(tmp_path / "history.sqlite3"),
        context_store=ContextStore(scope="app"),
        clipboard=FakeClipboard(),
        file_opener=FakeFileOpener(),
        file_exporter=FakeFileExporter(tmp_path / "exports"),
        permissions=FakePermissions(trusted=trusted),
        lifecycle=FakeLifecycle(),
        config_path=tmp_path / "config.toml",
        on_config_applied=lambda config: setattr(deps, "applied_config", config),
    )
    loop = _controller_loop()
    dependency_values = {
        key: value
        for key, value in deps.__dict__.items()
        if key in DesktopControllerDependencies.__dataclass_fields__
    }
    controller = DesktopDictationController(
        config=config,
        dependencies=DesktopControllerDependencies(**dependency_values),
        loop=loop,
    )
    controller.initialize_tray()
    return controller, deps


def _controller_loop() -> asyncio.AbstractEventLoop | "_UnusedLoop":
    try:
        return asyncio.get_running_loop()
    except RuntimeError:
        return _UnusedLoop()


class _UnusedLoop:
    def call_soon_threadsafe(self, *args, **kwargs) -> None:
        raise RuntimeError("test loop is not running")


@dataclass
class _Deps:
    tray: "FakeTray"
    recorder: "FakeRecorder"
    asr_provider: "FakeASR"
    llm_provider: "FakeLLM"
    inserter: "FakeInserter"
    text_reviewer: "FakeTextReviewer"
    app_provider: "FakeAppProvider"
    history_store: HistoryStore
    context_store: ContextStore
    clipboard: "FakeClipboard"
    file_opener: "FakeFileOpener"
    file_exporter: "FakeFileExporter"
    permissions: "FakePermissions"
    lifecycle: "FakeLifecycle"
    config_path: Path
    on_config_applied: object
    applied_config: AppConfig | None = None


class FakeTray:
    def __init__(self) -> None:
        self.states: list[tuple[str, str]] = []
        self.error_feedback = None
        self.styles: list[StyleDefinition] = []
        self.selected_style_id = ""
        self.binding_summary = ""
        self.input_devices = []
        self.stats = {}
        self.history_records = []
        self.review_enabled = True

    def set_state(self, state: str, detail: str = "") -> None:
        self.states.append((state, detail))

    def set_error_feedback(self, feedback) -> None:
        self.error_feedback = feedback

    def set_styles(self, styles: list[StyleDefinition], selected_style_id: str) -> None:
        self.styles = styles
        self.selected_style_id = selected_style_id

    def set_app_binding_summary(self, title: str) -> None:
        self.binding_summary = title

    def set_status_config(self, status_config) -> None:
        pass

    def set_auto_polish(self, enabled: bool) -> None:
        self.auto_polish = enabled

    def set_realtime_enabled(self, enabled: bool) -> None:
        self.realtime_enabled = enabled

    def set_review_enabled(self, enabled: bool) -> None:
        self.review_enabled = enabled

    def set_input_devices(
        self,
        devices: list[InputDeviceSummary],
        selected_device_id: str,
    ) -> None:
        self.input_devices = devices

    def set_stats(
        self,
        *,
        totals: dict[str, int | float],
        app_stats: list[AppStatsSummary],
    ) -> None:
        self.stats = totals

    def set_history_records(self, records: list[dict]) -> None:
        self.history_records = records


class FakeRecorder:
    def __init__(self, audio_path: Path) -> None:
        self.audio_path = audio_path
        self.input_device = ""
        self.stopped = False

    async def record_until_stopped(self) -> AudioClip:
        return AudioClip(path=self.audio_path, sample_rate=16000, duration_seconds=1)

    def stop(self) -> None:
        self.stopped = True

    def set_processing(self, options) -> None:
        self.processing = options

    def set_input_device(self, device_id: str | int | None) -> None:
        self.input_device = "" if device_id is None else str(device_id)

    def input_devices(self) -> list[InputDeviceSummary]:
        return []

    def current_input_label(self) -> str:
        return "系统默认输入"


class FakeASR:
    def __init__(self) -> None:
        self.closed = False
        self.text = "raw"
        self.error: Exception | None = None
        self.audios: list[AudioClip] = []

    async def transcribe(self, audio: AudioClip) -> Transcript:
        self.audios.append(audio)
        if self.error is not None:
            raise self.error
        return Transcript(text=self.text)

    async def aclose(self) -> None:
        self.closed = True


class FakeLLM:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str]] = []
        self.profiles: list[str | None] = []
        self.closed = False

    async def polish(
        self,
        raw_text: str,
        context: str,
        prompt_instruction: str,
        *,
        profile: str | None = None,
    ) -> str:
        self.calls.append((raw_text, context, prompt_instruction))
        self.profiles.append(profile)
        if prompt_instruction.startswith("custom"):
            return f"preview:{prompt_instruction}:{raw_text}"
        return f"final:{raw_text}"

    async def aclose(self) -> None:
        self.closed = True


class FakeInserter:
    def __init__(self) -> None:
        self.text = None
        self.error: Exception | None = None

    async def insert(self, text: str) -> None:
        if self.error is not None:
            raise self.error
        self.text = text


class FakeTextReviewer:
    def __init__(self) -> None:
        self.result: str | None = None
        self.cancelled = False
        self.seen: list[TextReviewRequest] = []
        self.preview_request: TextReviewPreviewRequest | None = None
        self.save_request: TextReviewSaveRequest | None = None
        self.save_result: TextReviewSaveResult | None = None

    async def review(self, request, previewer, saver) -> TextReviewResult | None:
        self.seen.append(request)
        if self.cancelled:
            return None
        style_id = request.style_id
        prompt_instruction = request.prompt_instruction
        polished_text = request.polished_text
        if self.preview_request is not None:
            polished_text = await previewer(self.preview_request)
            style_id = self.preview_request.style_id
            prompt_instruction = self.preview_request.prompt_instruction
        if self.save_request is not None:
            self.save_result = await saver(self.save_request)
            style_id = self.save_request.style_id
            prompt_instruction = self.save_request.prompt_instruction
        text = self.result if self.result is not None else polished_text
        return TextReviewResult(
            text=text,
            polished_text=polished_text,
            style_id=style_id,
            prompt_instruction=prompt_instruction,
        )


class FakeAppProvider:
    def current_app(self) -> AppContext:
        return AppContext(bundle_id="com.example.App", app_name="Example")


class FakeClipboard:
    def __init__(self) -> None:
        self.text = ""

    def copy_text(self, text: str) -> None:
        self.text = text


class FakeFileOpener:
    def __init__(self) -> None:
        self.paths: list[Path] = []

    def open_path(self, path: Path) -> None:
        self.paths.append(path)


class FakeFileExporter:
    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self.destination: Path | None = None

    def export_file(self, source: Path, suggested_name: str) -> Path:
        self.directory.mkdir(parents=True, exist_ok=True)
        self.destination = self.directory / suggested_name
        shutil.copy2(source, self.destination)
        return self.destination


class FakePermissions:
    def __init__(self, *, trusted: bool = True) -> None:
        self.trusted = trusted

    def accessibility_trusted(self, *, prompt: bool = False) -> bool:
        return self.trusted

    def accessibility_error(self) -> PermissionDeniedError:
        return PermissionDeniedError(
            "test permission denied",
            suggestion="grant test permission",
        )


class FakeLifecycle:
    def __init__(self) -> None:
        self.did_quit = False

    def quit(self) -> None:
        self.did_quit = True


@pytest.mark.parametrize("review_enabled", [True, False])
async def test_auto_polish_disabled_inserts_raw_without_llm(tmp_path, review_enabled):
    controller, deps = _make_controller(tmp_path)
    controller.config.llm.auto_polish = False
    controller.config.review.enabled = review_enabled
    deps.recorder.audio_path.write_bytes(b"audio")
    await controller.run_pipeline_once()
    assert deps.llm_provider.calls == []
    assert deps.inserter.text == "raw"
    record = deps.history_store.recent()[0]
    assert record["raw_text"] == record["final_text"] == record["user_edited_text"] == "raw"
    assert not any(state == "polishing" for state, _ in deps.tray.states)
    if review_enabled:
        assert deps.text_reviewer.seen[0].auto_polish is False


async def test_auto_polish_off_still_allows_manual_review_polish(tmp_path):
    controller, deps = _make_controller(tmp_path)
    controller.config.llm.auto_polish = False
    deps.recorder.audio_path.write_bytes(b"audio")
    deps.text_reviewer.preview_request = TextReviewPreviewRequest("通用润色", "manual polish")
    await controller.run_pipeline_once()
    assert deps.llm_provider.calls == [("raw", "", "manual polish")]
    assert deps.history_store.recent()[0]["final_text"] == "final:raw"


def test_auto_polish_menu_switch_is_shared_and_persisted(tmp_path):
    controller, deps = _make_controller(tmp_path)
    controller.tray_actions().toggle_auto_polish()
    assert not deps.tray.auto_polish
    assert not AppConfig.load(tmp_path / "config.toml").llm.auto_polish
    controller.config.review.realtime_enabled = True
    assert not controller.config.llm.auto_polish
    controller.state.state = DictationState.RECORDING
    controller.toggle_auto_polish()
    assert not controller.config.llm.auto_polish
    controller.state.state = DictationState.IDLE
    controller.toggle_auto_polish()
    assert deps.tray.auto_polish
    assert AppConfig.load(tmp_path / "config.toml").llm.auto_polish
