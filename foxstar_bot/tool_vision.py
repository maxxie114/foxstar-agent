from __future__ import annotations

import base64

import mimetypes

import shutil

from pathlib import Path

from .llm_client import LLMClient

from .persistence import Database, utc_now

class VisionTool:
    def __init__(self, db: Database, images_dir: Path, llm: LLMClient) -> None:
        self.db = db
        self.images_dir = images_dir
        self.images_dir.mkdir(parents=True, exist_ok=True)
        self.llm = llm

    def _save_copy(self, path: Path) -> Path:
        target = self.images_dir / path.name
        if path.resolve() != target.resolve():
            shutil.copy2(path, target)
        return target

def image_to_data_url(path: Path) -> str:
    mime = mimetypes.guess_type(path.name)[0] or "image/jpeg"
    data = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{data}"
