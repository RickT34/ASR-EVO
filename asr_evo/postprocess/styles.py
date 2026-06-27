from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class StyleDefinition:
    id: str
    label: str
    prompt: str
    source: str
    category: tuple[str, ...] = ()


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
            style_id = _style_id_from_file(self.prompts_dir, prompt_file)
            styles[style_id] = StyleDefinition(
                id=style_id,
                label=prompt_file.stem,
                prompt=prompt,
                source=str(prompt_file),
                category=_style_category(self.prompts_dir, prompt_file),
            )
        self._styles = styles

    def all(self) -> list[StyleDefinition]:
        return sorted(
            self._styles.values(),
            key=lambda style: (tuple(part.lower() for part in style.category), style.label.lower()),
        )

    def get(self, style_id: str) -> StyleDefinition:
        if style_id in self._styles:
            return self._styles[style_id]
        return self._styles[self.default_style_id()]

    def has(self, style_id: str) -> bool:
        return style_id in self._styles

    def update_prompt(self, style_id: str, prompt: str) -> StyleDefinition:
        if style_id not in self._styles:
            raise KeyError(f"style not found: {style_id}")
        style = self._styles[style_id]
        path = Path(style.source)
        path.write_text(prompt.strip() + "\n", encoding="utf-8")
        updated = StyleDefinition(
            id=style.id,
            label=style.label,
            prompt=prompt.strip(),
            source=style.source,
            category=style.category,
        )
        self._styles[style_id] = updated
        return updated

    def default_style_id(self) -> str:
        styles = self.all()
        if not styles:
            raise RuntimeError(f"No prompt files found in {self.prompts_dir}")
        return styles[0].id

    def _prompt_files(self) -> list[Path]:
        if not self.prompts_dir.exists():
            return []
        return [
            path
            for path in self.prompts_dir.rglob("*")
            if path.is_file()
            and path.suffix.lower() == ".md"
            and path.stem.lower() != "readme"
            and not _has_hidden_part(path.relative_to(self.prompts_dir))
        ]


def _style_id_from_file(prompts_dir: Path, path: Path) -> str:
    relative = path.relative_to(prompts_dir).with_suffix("")
    return relative.as_posix()


def _style_category(prompts_dir: Path, path: Path) -> tuple[str, ...]:
    relative = path.relative_to(prompts_dir)
    return tuple(relative.parts[:-1])


def _has_hidden_part(path: Path) -> bool:
    return any(part.startswith(".") for part in path.parts)
