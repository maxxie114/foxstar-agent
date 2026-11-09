from foxstar_bot.wcf_adapter import IncomingMessage, WcfAdapter, _copy_to_debug_log


def test_copy_to_debug_log_creates_unique_debug_copy(tmp_path):
    source = tmp_path / "image.png"
    source.write_bytes(b"png data")
    log_dir = tmp_path / "images_log"

    first = _copy_to_debug_log(source, log_dir, 123)
    second = _copy_to_debug_log(source, log_dir, 123)

    assert first is not None
    assert first.exists()
    assert first.read_bytes() == b"png data"
    assert second is not None
    assert second.exists()
    assert second.read_bytes() == b"png data"
    assert first.name.startswith("123_")


def test_download_image_rejects_thumb_fallback(monkeypatch, tmp_path):
    adapter = WcfAdapter.__new__(WcfAdapter)
    adapter.images_dir = tmp_path / "images"
    adapter.images_dir.mkdir()

    class FakeWcf:
        def download_image(self, *args):
            return ""

    adapter.wcf = FakeWcf()
    monkeypatch.setattr(adapter, "_download_image_from_local_candidate", lambda incoming: None)
    monkeypatch.setattr(adapter, "_download_image_from_image_store", lambda incoming: None)
    monkeypatch.setattr(adapter, "_wait_for_image_store_image", lambda incoming: None)
    monkeypatch.setattr(adapter, "_decrypt_existing_image_file", lambda path: tmp_path / "thumb.jpg")
    msg = IncomingMessage(1, "sender", "room", "room", "[图片]", 3, True, False, thumb="thumb.dat", extra="extra.dat")

    assert adapter.download_image(msg) is None


def test_wait_for_image_store_image_returns_late_candidate(monkeypatch, tmp_path):
    adapter = WcfAdapter.__new__(WcfAdapter)
    image_file = tmp_path / "late.dat"
    calls = {"count": 0}

    def fake_candidates(incoming):
        calls["count"] += 1
        if calls["count"] == 1:
            image_file.write_bytes(b"partial")
        else:
            image_file.write_bytes(b"stable complete")
        return [image_file]

    monkeypatch.setattr(adapter, "_image_store_candidates", fake_candidates)
    monkeypatch.setattr(adapter, "_decrypt_existing_image_file", lambda path: tmp_path / "late.jpg" if calls["count"] >= 2 else None)
    monkeypatch.setattr("foxstar_bot.wcf_adapter.IMAGE_STORE_POLL_SECONDS", 5.0)
    monkeypatch.setattr("foxstar_bot.wcf_adapter.IMAGE_STORE_POLL_INTERVAL_SECONDS", 0.0)
    msg = IncomingMessage(1, "sender", "room", "room", "[图片]", 3, True, False)

    assert adapter._wait_for_image_store_image(msg) == tmp_path / "late.jpg"


def test_image_store_candidates_stay_in_current_message_dirs(tmp_path):
    adapter = WcfAdapter.__new__(WcfAdapter)
    month = "2026-04"
    current_dir = tmp_path / "MsgAttach" / "current" / "Image" / month
    old_dir = tmp_path / "MsgAttach" / "old" / "Image" / month
    thumb_dir = tmp_path / "MsgAttach" / "current" / "Thumb" / month
    current_dir.mkdir(parents=True)
    old_dir.mkdir(parents=True)
    thumb_dir.mkdir(parents=True)
    current = current_dir / "current.dat"
    old = old_dir / "old.dat"
    thumb = thumb_dir / "thumb_t.dat"
    current.write_bytes(b"current image")
    old.write_bytes(b"old image that must not be used")
    thumb.write_bytes(b"t")

    msg = IncomingMessage(
        1,
        "sender",
        "room",
        "room",
        "[image]",
        3,
        True,
        False,
        thumb=str(thumb),
        extra=str(current),
    )

    assert adapter._image_store_candidates(msg) == [current]
