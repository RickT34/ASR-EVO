from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from asr_evo.config import AppConfig
from asr_evo.core.context import ContextStore, DictationRecord
from asr_evo.core.controller import DesktopControllerDependencies, DesktopDictationController
from asr_evo.core.errors import PermissionDeniedError
from asr_evo.core.ports import AppContext, AppStatsSummary, AudioClip, InputDeviceSummary, Transcript
from asr_evo.core.state import DictationState
from asr_evo.postprocess.styles import StyleDefinition


async def test_controller_runs_pipeline_and_persists_history(tmp_path: Path) -> None:
    controller, deps = _make_controller(tmp_path)
    deps.recorder.audio_path.write_bytes(b"audio")

    await controller.run_pipeline_once()

    records = deps.history_store.recent()
    assert len(records) == 1
    assert records[0]["raw_text"] == "raw"
    assert records[0]["final_text"] == "final:raw"
    assert records[0]["user_edited_text"] == "final:raw"
    assert deps.tray.states[-1] == ("idle", "")
    assert deps.tray.history_records


async def test_controller_reviews_user_text_before_insert(tmp_path: Path) -> None:
    controller, deps = _make_controller(tmp_path)
    deps.text_reviewer.result = "user edited"
    deps.recorder.audio_path.write_bytes(b"audio")

    await controller.run_pipeline_once()

    records = deps.history_store.recent()
    assert deps.text_reviewer.seen == ["final:raw"]
    assert deps.inserter.text == "user edited"
    assert records[0]["final_text"] == "final:raw"
    assert records[0]["user_edited_text"] == "user edited"
    assert deps.tray.states[-1] == ("idle", "")


async def test_controller_cancels_insert_when_review_is_cancelled(tmp_path: Path) -> None:
    controller, deps = _make_controller(tmp_path)
    deps.text_reviewer.cancelled = True
    deps.recorder.audio_path.write_bytes(b"audio")

    await controller.run_pipeline_once()

    assert deps.history_store.recent() == []
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

    try:
        controller.apply_config(config, persist=True)
    except OSError:
        pass

    assert controller.config.control.port != 9876
    assert not (tmp_path / "config.toml").exists()


def test_controller_handles_external_control_commands(tmp_path: Path) -> None:
    controller, deps = _make_controller(tmp_path)
    controller.start_dictation = lambda: setattr(controller.state, "state", DictationState.RECORDING)

    started = controller.handle_control_command("start")

    assert started.ok is True
    assert started.state == "recording"
    stopped = controller.handle_control_command("stop")
    assert stopped.ok is True
    assert stopped.state == "recording"
    assert deps.recorder.stopped is True
    unsupported = controller.handle_control_command("missing")
    assert unsupported.ok is False
    assert unsupported.error == "unsupported command: missing"


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
    (scene / "邮件.md").write_text("email", encoding="utf-8")
    config = AppConfig()
    config.style.prompts_dir = str(prompts)
    deps = _Deps(
        tray=FakeTray(),
        recorder=FakeRecorder(tmp_path / "recording.wav"),
        asr_provider=FakeASR(),
        llm_provider=FakeLLM(),
        inserter=FakeInserter(),
        text_reviewer=FakeTextReviewer(),
        app_provider=FakeAppProvider(),
        history_store=FakeHistoryStore(),
        context_store=ContextStore(scope="app"),
        clipboard=FakeClipboard(),
        file_opener=FakeFileOpener(),
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
    history_store: "FakeHistoryStore"
    context_store: ContextStore
    clipboard: "FakeClipboard"
    file_opener: "FakeFileOpener"
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

    def set_input_device(self, device_id: str | int | None) -> None:
        self.input_device = "" if device_id is None else str(device_id)

    def input_devices(self) -> list[InputDeviceSummary]:
        return []

    def current_input_label(self) -> str:
        return "系统默认输入"


class FakeASR:
    async def transcribe(self, audio: AudioClip) -> Transcript:
        return Transcript(text="raw")

    async def aclose(self) -> None:
        pass


class FakeLLM:
    async def polish(self, raw_text: str, context: str, prompt_instruction: str) -> str:
        return f"final:{raw_text}"

    async def aclose(self) -> None:
        pass


class FakeInserter:
    def __init__(self) -> None:
        self.text = None

    async def insert(self, text: str) -> None:
        self.text = text


class FakeTextReviewer:
    def __init__(self) -> None:
        self.result: str | None = None
        self.cancelled = False
        self.seen: list[str] = []

    async def review(self, text: str) -> str | None:
        self.seen.append(text)
        if self.cancelled:
            return None
        return self.result if self.result is not None else text


class FakeAppProvider:
    def current_app(self) -> AppContext:
        return AppContext(bundle_id="com.example.App", app_name="Example")


class FakeHistoryStore:
    def __init__(self) -> None:
        self.records: list[dict] = []

    def add(self, record: DictationRecord, *, audio_seconds: float = 0) -> None:
        self.records.append(
            {
                "id": record.id,
                "raw_text": record.raw_text,
                "final_text": record.final_text,
                "app_name": record.app_context.app_name,
                "bundle_id": record.app_context.bundle_id,
                "style": record.style,
                "audio_seconds": audio_seconds,
                "user_edited_text": record.user_edited_text,
            }
        )

    def recent(self, limit: int = 100) -> list[dict]:
        return self.records[:limit]

    def recent_records(self, limit: int = 100) -> list[DictationRecord]:
        return []

    def get(self, record_id: str) -> dict | None:
        for record in self.records:
            if record["id"] == record_id:
                return record
        return None

    def totals(self) -> dict[str, int | float]:
        return {"count": len(self.records), "total_chars": 0, "total_audio_seconds": 0}

    def stats_by_app(self) -> list[AppStatsSummary]:
        return []


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
