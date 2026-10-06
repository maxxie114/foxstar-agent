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

    def latest_for_prompt(self, chat_id: str, limit: int = 6000, max_age_hours: int = 24) -> str:
        from datetime import datetime, timedelta, timezone as dt_timezone

        cutoff = (datetime.now(dt_timezone.utc) - timedelta(hours=max_age_hours)).isoformat(timespec="seconds")
        with self.db.connect() as conn:
            row = conn.execute(
                """
                SELECT file_path, file_type, extracted_text, created_at
                FROM files
                WHERE chat_id = ? AND COALESCE(extracted_text, '') != ''
                  AND created_at >= ?
                ORDER BY id DESC
                LIMIT 1
                """,
                (chat_id, cutoff),
            ).fetchone()
        if row is None:
            return ""
        name = Path(str(row["file_path"])).name
        header = f"最近上传文档：{name} ({row['file_type']}, {row['created_at']})\n"
        return header + self.summarize_for_prompt(str(row["extracted_text"] or ""), limit=limit)

    def extract_text(self, path: Path) -> str:
        suffix = path.suffix.lower()
        if suffix in {".txt", ".md", ".markdown"}:
            raw = path.read_bytes()
            for encoding in ("utf-8", "gb18030"):
                try:
                    return raw.decode(encoding)
                except UnicodeDecodeError:
                    continue
            return raw.decode("utf-8", errors="replace")
        if suffix == ".pdf":
            return self._extract_pdf(path)
        if suffix == ".docx":
            return self._extract_docx(path)
        raise ValueError(f"暂不支持这种文档格式：{suffix or 'unknown'}")

    def _save_copy(self, path: Path) -> Path:


        import hashlib
        import os as _os
        import re as _re
        import stat as _stat
        safe = _re.sub(r"[^0-9A-Za-z_.\-一-鿿]+", "_", path.stem).strip("_")[:60]
        suffix = path.suffix.lower()
        if not safe:
            safe = hashlib.sha1(str(path).encode("utf-8", "ignore")).hexdigest()[:16]
        target = self.files_dir / (safe + suffix)
        if path.resolve() != target.resolve():


            if target.exists():
                _os.chmod(target, _stat.S_IWRITE)
            shutil.copy2(path, target)
            _os.chmod(target, _stat.S_IWRITE)
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
            from docx.table import Table
            from docx.text.paragraph import Paragraph
        except Exception as exc:
            raise RuntimeError("解析 DOCX 需要安装 python-docx") from exc
        document = docx.Document(str(path))
        parts: list[str] = []


        for child in document.element.body.iterchildren():
            tag = child.tag.rsplit("}", 1)[-1]
            if tag == "p":
                text = Paragraph(child, document).text
                if text and text.strip():
                    parts.append(text.strip())
            elif tag == "tbl":
                try:
                    table = Table(child, document)
                    rows = []
                    for row in table.rows:
                        cells = [cell.text.strip() for cell in row.cells]
                        if any(cells):
                            rows.append(" | ".join(cells))
                    if rows:
                        parts.append("[表格]\n" + "\n".join(rows))
                except Exception:
                    continue
        return "\n".join(parts).strip()

    @staticmethod
    def summarize_for_prompt(text: str, limit: int = 6000) -> str:
        text = (text or "").strip()
        if not text:
            return "文档没有提取到可读文本。"
        if len(text) <= limit:
            return "文档提取文本：\n" + text
        return (
            f"文档提取文本（全文共{len(text)}字符，已截断展示前{limit}字符；"
            "其余内容请用 query_document 工具按关键词检索）：\n" + text[:limit]
        )

    def query_document(self, chat_id: str, keyword: str, file_id: int | None = None, *, max_chunks: int = 3) -> str:
        keyword = (keyword or "").strip()
        if not keyword:
            return "query_document: keyword is required"
        with self.db.connect() as conn:
            if file_id:
                row = conn.execute(
                    "SELECT id, file_path, extracted_text FROM files WHERE id = ? AND chat_id = ?",
                    (int(file_id), chat_id),
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT id, file_path, extracted_text FROM files "
                    "WHERE chat_id = ? AND COALESCE(extracted_text, '') != '' ORDER BY id DESC LIMIT 1",
                    (chat_id,),
                ).fetchone()
        if row is None:
            return "query_document: no stored document for this chat"
        text = str(row["extracted_text"] or "")
        name = Path(str(row["file_path"])).name
        if not text:
            return f"query_document: {name} has no extracted text"
        terms = [t for t in keyword.split() if t] or [keyword]
        chunks = _split_chunks(text, chunk_size=800)
        scored = []
        for index, chunk in enumerate(chunks):
            score = sum(chunk.count(term) for term in terms)
            if score > 0:
                scored.append((score, index, chunk))
        if not scored:
            return f"query_document: keyword {keyword!r} not found in {name} (全文{len(text)}字符)"
        scored.sort(key=lambda item: (-item[0], item[1]))
        picked = scored[:max_chunks]
        parts = [f"query_document: {name} 全文{len(text)}字符，命中{len(scored)}个片段，返回{len(picked)}个："]
        for score, index, chunk in picked:
            parts.append(f"[片段{index + 1}/{len(chunks)} 命中{score}] {chunk}")
        return "\n".join(parts)


def _split_chunks(text: str, chunk_size: int = 800) -> list[str]:
    paragraphs = [p.strip() for p in (text or "").split("\n") if p.strip()]
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0
    for paragraph in paragraphs:
        if current and current_len + len(paragraph) > chunk_size:
            chunks.append("\n".join(current))
            current, current_len = [], 0
        current.append(paragraph)
        current_len += len(paragraph)

        while current_len > chunk_size * 2:
            chunks.append("\n".join(current)[: chunk_size * 2])
            rest = "\n".join(current)[chunk_size * 2 :]
            current = [rest]
            current_len = len(rest)
    if current:
        chunks.append("\n".join(current))
    return chunks
