from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


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
        self.prompts_dir.mkdir(parents=True, exist_ok=True)
        styles = {}
        for prompt_file in self._prompt_files():
            prompt = prompt_file.read_text(encoding="utf-8").strip()
            if not prompt:
                continue
            style_id = _style_id_from_file(prompt_file)
            styles[style_id] = StyleDefinition(
                id=style_id,
                label=prompt_file.name,
                prompt=prompt,
                source=str(prompt_file),
            )
        self._styles = styles

    def all(self) -> list[StyleDefinition]:
        return sorted(self._styles.values(), key=lambda style: style.label.lower())

    def get(self, style_id: str) -> StyleDefinition:
        if style_id in self._styles:
            return self._styles[style_id]
        return self._styles[self.default_style_id()]

    def has(self, style_id: str) -> bool:
        return style_id in self._styles

    def default_style_id(self) -> str:
        if "polished" in self._styles:
            return "polished"
        styles = self.all()
        if not styles:
            raise RuntimeError(f"No prompt files found in {self.prompts_dir}")
        return styles[0].id

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

def _style_id_from_file(path: Path) -> str:
    return path.stem
