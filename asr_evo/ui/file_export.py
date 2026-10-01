from __future__ import annotations

import shutil
from pathlib import Path

from asr_evo.core.ports import FileExporter


class TkFileExporter(FileExporter):
    def export_file(self, source: Path, suggested_name: str) -> Path | None:
        from tkinter import Tk, filedialog

        root = Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        try:
            selected = filedialog.asksaveasfilename(
                parent=root,
                initialfile=suggested_name,
                defaultextension=source.suffix,
                filetypes=[("音频文件", f"*{source.suffix}"), ("所有文件", "*.*")],
            )
        finally:
            root.destroy()
        if not selected:
            return None
        destination = Path(selected)
        if source.resolve() != destination.resolve():
            shutil.copy2(source, destination)
        return destination

