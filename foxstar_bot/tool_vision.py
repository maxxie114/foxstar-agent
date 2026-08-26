from __future__ import annotations

import base64
import logging
import mimetypes
import shutil
from pathlib import Path

from .llm_client import LLMClient
from .persistence import Database, utc_now

LOG = logging.getLogger(__name__)

DEFAULT_IMAGE_PROMPT = (
    "分析这张图片里的所有可见文字，并说明它在说什么。"
    "请先尽量逐段提取可读文字，再给出简短理解。"
    "如果文字很多，优先保留标题、列表项、关键术语、数字、按钮、网址和明显主张。"
    "看不清的地方标记为[不清楚]，不要脑补。不要 Markdown。"
)


class VisionTool:
    def __init__(self, db: Database, images_dir: Path, llm: LLMClient) -> None:
        self.db = db
        self.images_dir = images_dir
        self.images_dir.mkdir(parents=True, exist_ok=True)
        self.llm = llm

    def analyze_local_image(
        self,
        path: Path,
        chat_id: str,
        user_id: str,
        prompt: str = "",
        *,
        analysis_mode: str = "tool",
        model: str | None = None,
        provider: str | None = None,
        reasoning_effort: str | None = None,
    ) -> str:
        saved = self._save_copy(path)
        effective_prompt = prompt or DEFAULT_IMAGE_PROMPT
        if analysis_mode == "native":
            summary = self.llm.analyze_image_native(
                saved,
                effective_prompt,
                model=model,
                provider=provider,
                reasoning_effort=reasoning_effort,
                usage_context={"chat_id": chat_id, "feature": "native_image_analysis"},
            )
        else:
            summary = self.llm.analyze_image(saved, effective_prompt)
        with self.db.connect() as conn:
            conn.execute(
                "INSERT INTO images(chat_id, user_id, image_path, ocr_text, vision_summary, created_at) "
                "VALUES(?, ?, ?, ?, ?, ?)",
                (chat_id, user_id, str(saved), "", summary, utc_now()),
            )
        LOG.info(
            "image analysis complete mode=%s provider=%s model=%s image=%s chars=%s",
            analysis_mode,
            provider or "dedicated",
            model or "configured-vision-model",
            saved,
            len(summary),
        )
        return summary

    def _save_copy(self, path: Path) -> Path:
        target = self.images_dir / path.name
        if path.resolve() != target.resolve():
            shutil.copy2(path, target)
        return target


def image_to_data_url(path: Path) -> str:
    mime = mimetypes.guess_type(path.name)[0] or "image/jpeg"
    data = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{data}"
