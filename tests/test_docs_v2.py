from datetime import datetime, timedelta, timezone as dt_timezone
from pathlib import Path

from foxstar_bot.persistence import Database
from foxstar_bot.router import _looks_like_document_prompt
from foxstar_bot.tool_docs import DocumentTool


def _docs(tmp_path):
    db = Database(tmp_path / "bot.sqlite3")
    return DocumentTool(db, tmp_path / "files")


def test_docx_tables_extracted(tmp_path):
    import docx

    path = tmp_path / "t.docx"
    document = docx.Document()
    document.add_paragraph("结算总览")
    table = document.add_table(rows=2, cols=3)
    table.cell(0, 0).text = "区服"
    table.cell(0, 1).text = "数量"
    table.cell(0, 2).text = "应付"
    table.cell(1, 0).text = "沧海"
    table.cell(1, 1).text = "38"
    table.cell(1, 2).text = "58.46"
    document.add_paragraph("结尾段")
    document.save(str(path))

    docs = _docs(tmp_path)
    text = docs.extract_text(path)
    assert "结算总览" in text and "结尾段" in text
    assert "区服 | 数量 | 应付" in text
    assert "沧海 | 38 | 58.46" in text


def test_txt_gb18030_decoded(tmp_path):
    path = tmp_path / "gbk.txt"
    path.write_bytes("沧海结算 38 元，共两笔".encode("gb18030"))
    docs = _docs(tmp_path)
    assert "沧海结算 38 元" in docs.extract_text(path)


def test_latest_doc_24h_window(tmp_path):
    docs = _docs(tmp_path)
    old = tmp_path / "old.txt"
    old.write_text("旧文档内容", encoding="utf-8")
    with docs.db.connect() as conn:
        conn.execute(
            "INSERT INTO files(chat_id, user_id, file_path, file_type, extracted_text, created_at) VALUES(?,?,?,?,?,?)",
            ("room", "u", str(old), "txt", "旧文档内容",
             (datetime.now(dt_timezone.utc) - timedelta(hours=48)).isoformat(timespec="seconds")),
        )
    assert docs.latest_for_prompt("room") == ""

    fresh = tmp_path / "new.txt"
    fresh.write_text("新文档内容", encoding="utf-8")
    with docs.db.connect() as conn:
        conn.execute(
            "INSERT INTO files(chat_id, user_id, file_path, file_type, extracted_text, created_at) VALUES(?,?,?,?,?,?)",
            ("room", "u", str(fresh), "txt", "新文档内容", datetime.now(dt_timezone.utc).isoformat(timespec="seconds")),
        )
    block = docs.latest_for_prompt("room")
    assert "新文档内容" in block


def test_document_trigger_requires_reference_or_action():
    assert _looks_like_document_prompt("帮会材料交了没") is False
    assert _looks_like_document_prompt("给个报告") is False
    assert _looks_like_document_prompt("这个材料帮我算一下") is True
    assert _looks_like_document_prompt("总结一下这份文档") is True
    assert _looks_like_document_prompt("分析一下刚才那个pdf") is True
    assert _looks_like_document_prompt("今天天气怎么样") is False


def test_query_document_keyword_chunks(tmp_path):
    docs = _docs(tmp_path)
    long_text = "\n".join(
        [f"第{i}段：{'填充' * 30}" for i in range(1, 15)] + ["关键数据：沧海应付 5846.15 元", "尾部填充" * 10]
    )
    path = tmp_path / "long.txt"
    path.write_text(long_text, encoding="utf-8")
    with docs.db.connect() as conn:
        conn.execute(
            "INSERT INTO files(chat_id, user_id, file_path, file_type, extracted_text, created_at) VALUES(?,?,?,?,?,?)",
            ("room", "u", str(path), "txt", long_text, datetime.now(dt_timezone.utc).isoformat(timespec="seconds")),
        )
    result = docs.query_document("room", "沧海应付")
    assert "5846.15" in result
    assert "命中" in result
    assert docs.query_document("room", "不存在的词").startswith("query_document: keyword")


def test_truncation_note_mentions_query_document():
    block = DocumentTool.summarize_for_prompt("x" * 9000, limit=6000)
    assert "query_document" in block and "已截断" in block


def test_file_size_stable_and_format_checks(tmp_path):
    import time as _time

    from foxstar_bot.file_checks import _file_format_complete, _file_size_stable


    pdf = tmp_path / "ok.pdf"
    pdf.write_bytes(b"%PDF-1.4 ...body... %%EOF")
    assert _file_size_stable(pdf, samples=2, interval=0.05, timeout=2.0) is True
    assert _file_format_complete(pdf) is True


    trunc = tmp_path / "trunc.pdf"
    trunc.write_bytes(b"%PDF-1.4 half-downloaded body without")
    assert _file_size_stable(trunc, samples=2, interval=0.05, timeout=2.0) is True
    assert _file_format_complete(trunc) is False


    growing = tmp_path / "growing.docx"
    growing.write_bytes(b"x" * 100)
    import threading
    stop = threading.Event()

    def grow():
        i = 0
        while not stop.is_set() and i < 30:
            with growing.open("ab") as f:
                f.write(b"y" * 500)
            _time.sleep(0.05)
            i += 1

    t = threading.Thread(target=grow, daemon=True)
    t.start()
    try:
        assert _file_size_stable(growing, samples=2, interval=0.08, timeout=1.2) is False
    finally:
        stop.set()
        t.join(timeout=2)
