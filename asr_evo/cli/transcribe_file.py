from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

import soundfile as sf

from asr_evo.config import AppConfig
from asr_evo.core.ports import AudioClip
from asr_evo.core.style_binding import StyleBindingService
from asr_evo.postprocess.styles import StyleRegistry
from asr_evo.providers.factory import create_asr_provider, create_llm_provider


def main() -> None:
    parser = argparse.ArgumentParser(description="Transcribe and polish an existing audio file.")
    parser.add_argument("audio", type=Path)
    parser.add_argument("--config", default="config.toml")
    args = parser.parse_args()
    asyncio.run(_run(args.audio, AppConfig.load(args.config)))


async def _run(audio_path: Path, config: AppConfig) -> None:
    info = sf.info(audio_path)
    clip = AudioClip(
        path=audio_path,
        sample_rate=info.samplerate,
        duration_seconds=float(info.duration),
    )
    asr = create_asr_provider(config)
    llm = create_llm_provider(config)
    styles = StyleRegistry(prompts_dir=config.style.prompts_dir)
    style = styles.get(StyleBindingService(config=config, styles=styles).current_style_id)
    try:
        transcript = await asr.transcribe(clip)
        final_text = await llm.polish(
            transcript.text,
            context="",
            prompt_instruction=style.prompt,
        )
    finally:
        await asr.aclose()
        await llm.aclose()

    print("Raw transcript:")
    print(transcript.text)
    print()
    print("Final text:")
    print(final_text)


if __name__ == "__main__":
    main()
