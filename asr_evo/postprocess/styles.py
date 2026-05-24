from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from asr_evo.postprocess.prompts import STYLE_INSTRUCTIONS


@dataclass(frozen=True)
class StyleDefinition:
    id: str
    label: str
    prompt: str
    source: str


class StyleRegistry:
    def __init__(self, *, prompts_dir: str | Path = "prompts") -> None:
        self.prompts_dir = Path(prompts_dir).expanduser()
        self._styles: dict[str, StyleDefinition] = {}
        self.reload()

    def reload(self) -> None:
        styles = {
            style_id: StyleDefinition(
                id=style_id,
                label=_title_from_id(style_id),
                prompt=prompt,
                source="built-in",
            )
            for style_id, prompt in STYLE_INSTRUCTIONS.items()
        }
        for prompt_file in self._prompt_files():
            prompt = prompt_file.read_text(encoding="utf-8").strip()
            if not prompt:
                continue
            style_id = f"file:{prompt_file.stem}"
            styles[style_id] = StyleDefinition(
                id=style_id,
                label=_title_from_id(prompt_file.stem),
                prompt=prompt,
                source=str(prompt_file),
            )
        self._styles = styles

    def all(self) -> list[StyleDefinition]:
        built_ins = [style for style in self._styles.values() if style.source == "built-in"]
        custom = [style for style in self._styles.values() if style.source != "built-in"]
        return sorted(built_ins, key=lambda style: style.id) + sorted(
            custom,
            key=lambda style: style.label.lower(),
        )

    def get(self, style_id: str) -> StyleDefinition:
        if style_id in self._styles:
            return self._styles[style_id]
        if style_id in STYLE_INSTRUCTIONS:
            return self._styles[style_id]
        return self._styles["polished"]

    def has(self, style_id: str) -> bool:
        return style_id in self._styles

    def _prompt_files(self) -> list[Path]:
        if not self.prompts_dir.exists():
            return []
        return [
            path
            for path in self.prompts_dir.iterdir()
            if path.is_file()
            and path.suffix.lower() in {".txt", ".md"}
            and path.stem.lower() != "readme"
            and not path.name.startswith(".")
        ]


def _title_from_id(style_id: str) -> str:
    labels = {
        "exact": "精确保留",
        "polished": "书面润色",
        "concise": "简洁整理",
    }
    return labels.get(style_id, style_id.replace("_", " ").replace("-", " ").title())
