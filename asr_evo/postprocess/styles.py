from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

import tomli_w


FRONT_MATTER_DELIMITER = "+++"


@dataclass(frozen=True)
class StyleDefinition:
    id: str
    label: str
    prompt: str
    source: str
    category: tuple[str, ...] = ()
    llm_profile: str | None = None


class StyleRegistry:
    def __init__(self, *, prompts_dir: str | Path = "prompts") -> None:
        self.prompts_dir = Path(prompts_dir).expanduser()
        self._styles: dict[str, StyleDefinition] = {}
        self.reload()

    def reload(self) -> None:
        self.prompts_dir.mkdir(parents=True, exist_ok=True)
        styles = {}
        for prompt_file in self._prompt_files():
            prompt, llm_profile = _parse_prompt_file(prompt_file)
            if not prompt:
                continue
            style_id = _style_id_from_file(self.prompts_dir, prompt_file)
            styles[style_id] = StyleDefinition(
                id=style_id,
                label=prompt_file.stem,
                prompt=prompt,
                source=str(prompt_file),
                category=_style_category(self.prompts_dir, prompt_file),
                llm_profile=llm_profile,
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
        path.write_text(
            _render_prompt_file(prompt, llm_profile=style.llm_profile),
            encoding="utf-8",
        )
        updated = StyleDefinition(
            id=style.id,
            label=style.label,
            prompt=prompt.strip(),
            source=style.source,
            category=style.category,
            llm_profile=style.llm_profile,
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


def _parse_prompt_file(path: Path) -> tuple[str, str | None]:
    content = path.read_text(encoding="utf-8").strip()
    lines = content.splitlines()
    if not lines or lines[0].strip() != FRONT_MATTER_DELIMITER:
        return content, None

    try:
        closing_index = next(
            index
            for index, line in enumerate(lines[1:], start=1)
            if line.strip() == FRONT_MATTER_DELIMITER
        )
    except StopIteration as exc:
        raise ValueError(f"Prompt front matter is not closed: {path}") from exc

    try:
        metadata = tomllib.loads("\n".join(lines[1:closing_index]))
    except tomllib.TOMLDecodeError as exc:
        raise ValueError(f"Invalid prompt front matter in {path}: {exc}") from exc

    unknown_keys = metadata.keys() - {"llm_profile"}
    if unknown_keys:
        unknown = ", ".join(sorted(unknown_keys))
        raise ValueError(f"Unsupported prompt metadata in {path}: {unknown}")

    llm_profile = metadata.get("llm_profile")
    if llm_profile is not None and (not isinstance(llm_profile, str) or not llm_profile.strip()):
        raise ValueError(f"llm_profile must be a non-empty string in {path}")

    prompt = "\n".join(lines[closing_index + 1 :]).strip()
    return prompt, llm_profile.strip() if isinstance(llm_profile, str) else None


def _render_prompt_file(prompt: str, *, llm_profile: str | None) -> str:
    body = prompt.strip()
    if llm_profile is None:
        return body + "\n"
    metadata = tomli_w.dumps({"llm_profile": llm_profile}).strip()
    return f"{FRONT_MATTER_DELIMITER}\n{metadata}\n{FRONT_MATTER_DELIMITER}\n\n{body}\n"
