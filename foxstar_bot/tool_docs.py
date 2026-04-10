from __future__ import annotations

import logging

import shutil

from pathlib import Path

from .persistence import Database, utc_now

LOG = logging.getLogger(__name__)

class DocumentTool:
    def __init__(self, db: Database, files_dir: Path) -> None:
        self.db = db
        self.files_dir = files_dir
        self.files_dir.mkdir(parents=True, exist_ok=True)

    def ingest_local_file(self, path: Path, chat_id: str, user_id: str) -> str:
        saved = self._save_copy(path)
        text = self.extract_text(saved)
        with self.db.connect() as conn:
            conn.execute(
                "INSERT INTO files(chat_id, user_id, file_path, file_type, extracted_text, created_at) "
                "VALUES(?, ?, ?, ?, ?, ?)",
                (chat_id, user_id, str(saved), saved.suffix.lower().lstrip("."), text, utc_now()),
            )
        return text

    def _save_copy(self, path: Path) -> Path:
        target = self.files_dir / path.name
        if path.resolve() != target.resolve():
            shutil.copy2(path, target)
        return target

    @staticmethod
    def _extract_pdf(path: Path) -> str:
        try:
            from pypdf import PdfReader
        except Exception as exc:
            raise RuntimeError("解析 PDF 需要安装 pypdf") from exc
        reader = PdfReader(str(path))
        pages = [(page.extract_text() or "") for page in reader.pages]
        return "\n\n".join(pages).strip()

    @staticmethod
    def _extract_docx(path: Path) -> str:
        try:
            import docx
        except Exception as exc:
            raise RuntimeError("解析 DOCX 需要安装 python-docx") from exc
        document = docx.Document(str(path))
        return "\n".join(p.text for p in document.paragraphs if p.text).strip()
