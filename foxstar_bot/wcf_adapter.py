from __future__ import annotations

import logging
import atexit
import os
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from queue import Empty, Queue
from threading import Event, Lock, Thread
from typing import Any

from .wechat_xml import normalize_wechat_content, wechat_appmsg_type, wechat_image_length, wechat_is_document_appmsg

LOG = logging.getLogger(__name__)
WCF_IMAGE_TIMEOUT_SECONDS = 35.0
WCF_DECRYPT_TIMEOUT_SECONDS = 8.0
WCF_ATTACH_TIMEOUT_SECONDS = 45.0
IMAGE_STORE_POLL_SECONDS = 75.0
IMAGE_STORE_POLL_INTERVAL_SECONDS = 2.0
DOCUMENT_FILE_POLL_SECONDS = 15.0
DOCUMENT_FILE_POLL_INTERVAL_SECONDS = 0.5
IMAGE_SIGNATURES = (
    (".jpg", b"\xff\xd8\xff"),
    (".png", b"\x89PNG\r\n\x1a\n"),
    (".gif", b"GIF8"),
    (".bmp", b"BM"),
)
IMAGE_LOG_DIR = Path("images_log")
DOCUMENT_LOG_DIR = Path("document_log")


@dataclass(frozen=True)
class IncomingMessage:
    id: int
    sender: str
    chat_id: str
    room_id: str
    content: str
    msg_type: int
    is_group: bool
    is_self: bool
    thumb: str = ""
    extra: str = ""
    raw: Any = None


@dataclass(frozen=True)
class PendingRevoke:
    receiver: str
    content: str
    revoke_after_seconds: float
    expires_at: float


@dataclass(frozen=True)
class SentMessage:
    receiver: str
    content: str
    msg_id: int
    created_at: float
    revoke_ids: tuple[int, ...] = ()


class WcfAdapter:
    def __init__(
        self,
        images_dir: Path,
        files_dir: Path,
        host: str | None = None,
        port: int = 10086,
        debug: bool = False,
    ) -> None:
        if host is None and os.name == "nt":
            from .wcf_runtime import ensure_windows_local_wcf_binaries

            ensure_windows_local_wcf_binaries()
        try:
            from wcferry import Wcf
        except Exception as exc:
            raise RuntimeError("需要安装 wcferry，并确保 WeChatFerry 服务可用") from exc
        self.wcf = Wcf(host=host, port=port, debug=debug)
        # Wcf uses one PAIR command socket for every RPC. Its send/recv pair
        # is not atomic, while several bot workers share this adapter. Keep
        # the entire request/response exchange together so SQL results cannot
        # be consumed by a different worker's request.
        self._wcf_rpc_lock = Lock()
        send_request = self.wcf._send_request

        def serialized_send_request(request: Any) -> Any:
            with self._wcf_rpc_lock:
                return send_request(request)

        self.wcf._send_request = serialized_send_request
        if host is not None:
            self._disable_remote_shutdown_cleanup()
        # WCF download/decrypt RPCs execute inside WeChat.exe and resolve
        # paths against WeChat's CWD (System32 when launched via schtasks),
        # so a relative images_dir writes images to System32\data\images.
        # Always resolve both dirs to absolute paths.
        self.images_dir = images_dir.resolve()
        self.files_dir = files_dir.resolve()
        self.images_dir.mkdir(parents=True, exist_ok=True)
        self.files_dir.mkdir(parents=True, exist_ok=True)
        self._contacts_cache: list[dict[str, str]] | None = None
        self._room_members_cache: dict[str, dict[str, str]] = {}
        self._pending_revokes: list[PendingRevoke] = []
        self._pending_revokes_lock = Lock()
        self._sent_messages: list[SentMessage] = []
        self._msg_db_names: list[str] | None = None

    def self_wxid(self) -> str:
        return self.wcf.get_self_wxid()

    def start_receiving(self) -> None:
        if not self._enable_receiving_msg_with_retry():
            raise RuntimeError("WeChatFerry enable_receiving_msg 失败")

    def get_message(self) -> IncomingMessage | None:
        try:
            msg = self.wcf.get_msg()
        except Empty:
            return None
        room_id = msg.roomid or ""
        chat_id = room_id or msg.sender
        msg_content = msg.content or ""
        incoming = IncomingMessage(
            id=int(msg.id),
            sender=msg.sender,
            chat_id=chat_id,
            room_id=room_id,
            content=normalize_wechat_content(msg_content, int(msg.type)),
            msg_type=int(msg.type),
            is_group=bool(msg.from_group() or room_id.endswith("@chatroom")),
            is_self=bool(msg.from_self()),
            thumb=msg.thumb or "",
            extra=msg.extra or "",
            raw=msg,
        )
        self._maybe_schedule_revoke(incoming)
        if incoming.is_self:
            LOG.debug(
                "self_message_echo id=%s sender=%s room_id=%s chat_id=%s is_group=%s type=%s content=%r",
                incoming.id,
                incoming.sender,
                incoming.room_id,
                incoming.chat_id,
                incoming.is_group,
                incoming.msg_type,
                incoming.content[:120],
            )
        return incoming

    def is_at_me(self, incoming: IncomingMessage, self_wxid: str) -> bool:
        if not incoming.raw:
            return False
        try:
            return bool(incoming.raw.is_at(self_wxid))
        except Exception:
            return False

    def send_text(self, receiver: str, text: str, revoke_after_seconds: float | None = None) -> bool:
        ret = self.wcf.send_text(text, receiver)
        if ret != 0:
            LOG.warning("send_text failed: receiver=%s ret=%s", receiver, ret)
            ret = self.wcf.send_text(text, receiver)
        ok = ret == 0
        if ok and revoke_after_seconds and revoke_after_seconds > 0:
            self._remember_pending_revoke(receiver, text, revoke_after_seconds)
        return ok

    def revoke_message(self, msg_id: int) -> bool:
        try:
            from wcferry import wcf_pb2

            req = wcf_pb2.Request()
            req.func = wcf_pb2.FUNC_REVOKE_MSG
            req.ui64 = int(msg_id)
            rsp = self.wcf._send_request(req)
            ok = rsp.status in {0, 1}
            LOG.debug("revoke_msg result msg=%s status=%s ok=%s", msg_id, rsp.status, ok)
            if not ok:
                LOG.warning("revoke_msg failed: msg=%s status=%s", msg_id, rsp.status)
            return ok
        except Exception as exc:
            LOG.warning("revoke_msg unavailable: msg=%s reason=%s", msg_id, exc)
            return False

    def display_name(self, wxid: str, room_id: str = "") -> str:
        if not wxid:
            return ""
        if room_id:
            name = self.room_member_name(wxid, room_id)
            if name:
                return name
        contact = self.contact_info(wxid)
        for key in ("remark", "name", "code"):
            value = str(contact.get(key, "") or "").strip()
            if value:
                return value
        return wxid

    def room_member_name(self, wxid: str, room_id: str) -> str:
        if not wxid or not room_id:
            return ""
        members = self._room_members_cache.get(room_id)
        if members is None:
            try:
                members = {str(key): str(value) for key, value in self.wcf.get_chatroom_members(room_id).items()}
            except Exception as exc:
                LOG.debug("get_chatroom_members failed room=%s reason=%s", room_id, exc)
                members = {}
            self._room_members_cache[room_id] = members
        return members.get(wxid, "").strip()

    def get_chatroom_members(self, room_id: str, *, refresh: bool = False) -> dict[str, str]:
        if not room_id:
            return {}
        if refresh or room_id not in self._room_members_cache:
            try:
                members = {str(key): str(value) for key, value in self.wcf.get_chatroom_members(room_id).items()}
            except Exception as exc:
                LOG.debug("get_chatroom_members failed room=%s reason=%s", room_id, exc)
                members = {}
            self._room_members_cache[room_id] = members
        return dict(self._room_members_cache.get(room_id, {}))

    def contact_info(self, wxid: str) -> dict[str, str]:
        if not wxid:
            return {}
        if self._contacts_cache is None:
            try:
                self._contacts_cache = self.wcf.get_contacts()
            except Exception as exc:
                LOG.debug("get_contacts failed reason=%s", exc)
                self._contacts_cache = []
        for contact in self._contacts_cache:
            if contact.get("wxid") == wxid:
                return {str(key): str(value) for key, value in contact.items()}
        return {}

    def _remember_pending_revoke(self, receiver: str, content: str, revoke_after_seconds: float) -> None:
        pending = PendingRevoke(
            receiver=receiver,
            content=content,
            revoke_after_seconds=float(revoke_after_seconds),
            expires_at=time.monotonic() + 60.0,
        )
        with self._pending_revokes_lock:
            now = time.monotonic()
            self._pending_revokes = [item for item in self._pending_revokes if item.expires_at > now]
            self._pending_revokes.append(pending)

    def _maybe_schedule_revoke(self, incoming: IncomingMessage) -> None:
        if not incoming.is_self:
            return
        match: PendingRevoke | None = None
        with self._pending_revokes_lock:
            now = time.monotonic()
            remaining: list[PendingRevoke] = []
            for item in self._pending_revokes:
                if item.expires_at <= now:
                    LOG.debug("pending_revoke_expired receiver=%s content=%r", item.receiver, item.content[:80])
                    continue
                if match is None and incoming.chat_id == item.receiver and incoming.content.strip() == item.content.strip():
                    match = item
                    continue
                remaining.append(item)
            self._pending_revokes = remaining
        if match is None:
            LOG.debug(
                "pending_revoke_no_match receiver=%s msg=%s content=%r",
                incoming.chat_id,
                incoming.id,
                incoming.content[:80],
            )
            self._remember_sent_message(incoming)
            return

        LOG.debug(
            "pending_revoke_matched receiver=%s msg=%s delay=%s content=%r",
            incoming.chat_id,
            incoming.id,
            match.revoke_after_seconds,
            incoming.content[:80],
        )
        self._remember_sent_message(incoming)

        def revoke_later() -> None:
            time.sleep(match.revoke_after_seconds)
            self.revoke_message(incoming.id)

        Thread(target=revoke_later, name=f"RevokeMessage-{incoming.id}", daemon=True).start()

    def _remember_sent_message(self, incoming: IncomingMessage) -> None:
        now = time.monotonic()
        with self._pending_revokes_lock:
            self._sent_messages = [item for item in self._sent_messages if now - item.created_at <= 600.0]
            self._sent_messages.append(
                SentMessage(
                    receiver=incoming.chat_id,
                    content=incoming.content,
                    msg_id=incoming.id,
                    created_at=now,
                )
            )
            self._sent_messages = self._sent_messages[-50:]
        LOG.debug("remember_sent_message receiver=%s msg=%s content=%r", incoming.chat_id, incoming.id, incoming.content[:80])

    def recall_recent_messages(self, receiver: str, count: int = 4, max_age_seconds: float = 115.0) -> int:
        count = max(1, min(int(count), 20))
        now = time.monotonic()
        with self._pending_revokes_lock:
            candidates = [
                item
                for item in self._sent_messages
                if item.receiver == receiver and now - item.created_at <= max_age_seconds
            ][-count:]
        if not candidates:
            candidates = self._recent_sent_messages_from_wechat_db(receiver, count, max_age_seconds)
        LOG.info(
            "recall_recent_messages receiver=%s requested=%s candidates=%s known_sent=%s",
            receiver,
            count,
            len(candidates),
            len(self._sent_messages),
        )
        recalled = 0
        for item in reversed(candidates):
            age = now - item.created_at
            LOG.debug(
                "recall_candidate receiver=%s msg=%s extra_ids=%s age=%.2fs content=%r",
                item.receiver,
                item.msg_id,
                item.revoke_ids,
                age,
                item.content[:80],
            )
            ok = False
            for revoke_id in _unique_ints((item.msg_id, *item.revoke_ids)):
                ok = self.revoke_message(revoke_id)
                LOG.info("recall_attempt receiver=%s msg=%s age=%.2fs ok=%s", item.receiver, revoke_id, age, ok)
                if ok:
                    break
            if ok:
                recalled += 1
        LOG.info("recall_recent_messages receiver=%s recalled=%s", receiver, recalled)
        return recalled

    def _recent_sent_messages_from_wechat_db(
        self,
        receiver: str,
        count: int,
        max_age_seconds: float,
    ) -> list[SentMessage]:
        db_names = self._message_db_names()
        if not db_names:
            LOG.info("recall_db_fallback unavailable receiver=%s reason=no_msg_dbs", receiver)
            return []
        escaped_receiver = receiver.replace("'", "''")
        query_limit = max(20, count * 4)
        found: list[SentMessage] = []
        now = time.monotonic()
        wall_now = time.time()
        for db_name in db_names:
            sql = (
                "SELECT * FROM MSG "
                f"WHERE IsSender = 1 AND StrTalker = '{escaped_receiver}' "
                f"ORDER BY CreateTime DESC LIMIT {query_limit}"
            )
            try:
                rows = self.wcf.query_sql(db_name, sql)
            except Exception as exc:
                LOG.debug("recall_db_query_failed db=%s receiver=%s reason=%s", db_name, receiver, exc)
                continue
            LOG.debug("recall_db_query db=%s receiver=%s rows=%s keys=%s", db_name, receiver, len(rows), list(rows[0].keys()) if rows else [])
            for row in rows:
                revoke_ids = _row_revoke_id_candidates(row)
                msg_id = revoke_ids[0] if revoke_ids else 0
                created_wall = _wechat_create_time_to_seconds(_row_float(row, "CreateTime"))
                if not msg_id or not created_wall:
                    continue
                age = wall_now - created_wall
                if age < 0 or age > max_age_seconds:
                    continue
                found.append(
                    SentMessage(
                        receiver=receiver,
                        content=str(row.get("StrContent", "") or ""),
                        msg_id=msg_id,
                        created_at=now - age,
                        revoke_ids=revoke_ids[1:],
                    )
                )
        found.sort(key=lambda item: item.created_at)
        if found:
            LOG.info("recall_db_fallback receiver=%s found=%s dbs=%s", receiver, len(found), db_names)
        else:
            LOG.info("recall_db_fallback receiver=%s found=0 dbs=%s", receiver, db_names)
        return found[-count:]

    def _message_db_names(self) -> list[str]:
        if self._msg_db_names is not None:
            return self._msg_db_names
        try:
            dbs = [str(name) for name in self.wcf.get_dbs()]
        except Exception as exc:
            LOG.warning("get_dbs failed for recall fallback: %s", exc)
            self._msg_db_names = []
            return []
        self._msg_db_names = [name for name in dbs if name.lower().startswith("msg") and name.lower().endswith(".db")]
        LOG.debug("recall message dbs=%s", self._msg_db_names)
        return self._msg_db_names

    def download_image(self, incoming: IncomingMessage) -> Path | None:
        fallback = self._download_image_from_local_candidate(incoming)
        if fallback is not None:
            LOG.warning("download_image used local fallback: msg=%s path=%s", incoming.id, fallback)
            _copy_to_debug_log(fallback, IMAGE_LOG_DIR, incoming.id)
            return fallback

        path = self._call_wcf_with_timeout(
            "download_image",
            WCF_IMAGE_TIMEOUT_SECONDS,
            self.wcf.download_image,
            incoming.id,
            incoming.extra,
            str(self.images_dir),
        )
        if path:
            downloaded = Path(path)
            _copy_to_debug_log(downloaded, IMAGE_LOG_DIR, incoming.id)
            return downloaded

        image_store = self._download_image_from_image_store(incoming)
        if image_store is not None:
            LOG.warning("download_image used image-store fallback: msg=%s path=%s", incoming.id, image_store)
            _copy_to_debug_log(image_store, IMAGE_LOG_DIR, incoming.id)
            return image_store

        delayed_image_store = self._wait_for_image_store_image(incoming)
        if delayed_image_store is not None:
            LOG.warning("download_image used delayed image-store fallback: msg=%s path=%s", incoming.id, delayed_image_store)
            _copy_to_debug_log(delayed_image_store, IMAGE_LOG_DIR, incoming.id)
            return delayed_image_store

        thumb = self._decrypt_existing_image_file(incoming.thumb)
        if thumb is not None:
            LOG.warning("download_image rejected thumb fallback for vision: msg=%s path=%s", incoming.id, thumb)
            _copy_to_debug_log(thumb, IMAGE_LOG_DIR, incoming.id)
            return None

        if not path:
            LOG.warning(
                "download_image failed: msg=%s extra=%r thumb=%r content=%r",
                incoming.id,
                incoming.extra,
                incoming.thumb,
                incoming.content[:120],
            )
            return None

        return Path(path)


    def download_file(self, incoming: IncomingMessage) -> Path | None:
        LOG.info(
            "download_file start msg=%s type=%s extra=%r thumb=%r content=%r",
            incoming.id,
            incoming.msg_type,
            incoming.extra,
            incoming.thumb,
            incoming.content[:120],
        )
        if incoming.extra and Path(incoming.extra).exists():
            path = Path(incoming.extra)
            complete = _await_complete_file(path, incoming.id)
            if complete is None:
                return None
            _copy_to_debug_log(path, DOCUMENT_LOG_DIR, incoming.id)
            LOG.info("download_file used existing extra msg=%s path=%s size=%s", incoming.id, path, _safe_size(path))
            return path
        ret = self._call_wcf_with_timeout(
            "download_attach",
            WCF_ATTACH_TIMEOUT_SECONDS,
            self.wcf.download_attach,
            incoming.id,
            incoming.thumb,
            incoming.extra,
        )
        if ret is None:
            LOG.warning("download_attach unavailable: msg=%s", incoming.id)
            path = self._wait_for_file_candidates(incoming, [incoming.extra, incoming.thumb])
            if path is not None:
                _copy_to_debug_log(path, DOCUMENT_LOG_DIR, incoming.id)
                LOG.info("download_file delayed success after unavailable attach msg=%s path=%s size=%s", incoming.id, path, _safe_size(path))
                return path
            return None
        if ret != 0:
            LOG.warning("download_attach failed: msg=%s ret=%s", incoming.id, ret)
            path = self._wait_for_file_candidates(incoming, [incoming.extra, incoming.thumb])
            if path is not None:
                _copy_to_debug_log(path, DOCUMENT_LOG_DIR, incoming.id)
                LOG.info("download_file delayed success after failed attach msg=%s ret=%s path=%s size=%s", incoming.id, ret, path, _safe_size(path))
                return path
            return None
        candidates = [incoming.extra, incoming.thumb]
        path = _first_existing_file(candidates)
        if path is not None:
            complete = _await_complete_file(path, incoming.id)
            if complete is None:
                return None
            _copy_to_debug_log(path, DOCUMENT_LOG_DIR, incoming.id)
            LOG.info("download_file success msg=%s path=%s size=%s", incoming.id, path, _safe_size(path))
            return path
        path = self._wait_for_file_candidates(incoming, candidates)
        if path is not None:
            _copy_to_debug_log(path, DOCUMENT_LOG_DIR, incoming.id)
            LOG.info("download_file delayed success msg=%s path=%s size=%s", incoming.id, path, _safe_size(path))
            return path
        LOG.warning(
            "download_file missing local file after attach: msg=%s extra=%r thumb=%r content=%r",
            incoming.id,
            incoming.extra,
            incoming.thumb,
            incoming.content[:120],
        )
        return None

    def _wait_for_file_candidates(self, incoming: IncomingMessage, candidates: list[str]) -> Path | None:
        deadline = time.monotonic() + DOCUMENT_FILE_POLL_SECONDS
        while time.monotonic() < deadline:
            path = _first_existing_file(candidates)
            if path is not None:
                complete = _await_complete_file(path, incoming.id, timeout=8.0)
                if complete is not None:
                    return complete
                return None  # exists but never becomes complete - stop waiting
            time.sleep(DOCUMENT_FILE_POLL_INTERVAL_SECONDS)
        LOG.warning(
            "download_file delayed poll timed out: msg=%s waited=%.1fs candidates=%s",
            incoming.id,
            DOCUMENT_FILE_POLL_SECONDS,
            [item for item in candidates if item],
        )
        return None

    @staticmethod
    def is_image_message(incoming: IncomingMessage) -> bool:
        return incoming.msg_type == 3

    @staticmethod
    def is_file_message(incoming: IncomingMessage) -> bool:
        if incoming.msg_type == 49:
            if incoming.content.startswith("[引用消息]") or incoming.content == "[动画表情]":
                return False
            raw_content = getattr(incoming.raw, "content", "") if incoming.raw else ""
            if not wechat_is_document_appmsg(raw_content):
                suffix = Path(incoming.content).suffix.lower()
                return suffix in {".pdf", ".docx", ".txt", ".md", ".markdown"}
            return True
        suffix = Path(incoming.content).suffix.lower()
        return suffix in {".pdf", ".docx", ".txt", ".md", ".markdown"}

    def _enable_receiving_msg_with_retry(self, pyq: bool = False) -> bool:
        from wcferry import wcf_pb2
        from wcferry.wxmsg import WxMsg

        if self.wcf.is_receiving_msg():
            return True

        req = wcf_pb2.Request()
        req.func = wcf_pb2.FUNC_ENABLE_RECV_TXT
        req.flag = pyq
        rsp = self.wcf._send_request(req)
        if rsp.func != wcf_pb2.FUNC_ENABLE_RECV_TXT or rsp.status != 0:
            return False

        self.wcf._is_receiving_msg = True
        ready = Event()
        result = {"connected": False}

        def listening_msg() -> None:
            rsp_msg = wcf_pb2.Response()
            last_error: Exception | None = None
            for _ in range(30):
                try:
                    self.wcf.msg_socket.dial(self.wcf.msg_url, block=True)
                    last_error = None
                    result["connected"] = True
                    ready.set()
                    break
                except Exception as exc:
                    last_error = exc
                    time.sleep(0.2)
            if last_error is not None:
                LOG.error("message socket dial failed after retries: %s", last_error)
                self.wcf._is_receiving_msg = False
                ready.set()
                return

            while self.wcf._is_receiving_msg:
                try:
                    rsp_msg.ParseFromString(self.wcf.msg_socket.recv_msg().bytes)
                except Exception:
                    continue
                self.wcf.msgQ.put(WxMsg(rsp_msg.wxmsg))

        Thread(target=listening_msg, name="GetMessage", daemon=True).start()
        ready.wait(timeout=8)
        return result["connected"]

    def _disable_remote_shutdown_cleanup(self) -> None:
        try:
            atexit.unregister(self.wcf.cleanup)
        except Exception:
            pass

        def noop_cleanup() -> None:
            self.wcf._is_receiving_msg = False
            self.wcf._is_running = False

        self.wcf.cleanup = noop_cleanup

    def shutdown_wcf(self) -> None:
        """Close the WCF connection gracefully before process exit.

        A hard process kill (Stop-Process / os._exit) leaves the nng sockets
        abruptly dead; the WCF server inside WeChat never sees a disconnect,
        wedges, and the next client's ENABLE_RECV_TXT hangs until WeChat
        itself dies. Deliberately does NOT send FUNC_SHUTDOWN and does NOT
        unload the injected DLL (wcf.cleanup's WxDestroySDK) - tearing out
        injected code from a live WeChat risks crashing it, which is why the
        remote cleanup was disabled in the first place.
        """
        try:
            self.wcf.disable_recv_msg()
        except Exception as exc:
            LOG.debug("disable_recv_msg during shutdown failed: %s", exc)
        for socket_name in ("cmd_socket", "msg_socket"):
            try:
                getattr(self.wcf, socket_name).close()
            except Exception as exc:
                LOG.debug("close %s during shutdown failed: %s", socket_name, exc)
        self.wcf._is_receiving_msg = False
        self.wcf._is_running = False
        LOG.info("WCF shut down gracefully (recv disabled, sockets closed)")

    def _download_image_from_local_candidate(self, incoming: IncomingMessage) -> Path | None:
        raw_content = getattr(incoming.raw, "content", "") if incoming.raw else ""
        expected_length = wechat_image_length(raw_content)
        extra = Path(incoming.extra) if incoming.extra else None
        if extra is None or expected_length is None or not extra.parent.exists():
            return None

        try:
            candidates = [
                item
                for item in extra.parent.glob("*.dat")
                if item.is_file() and item.stat().st_size == expected_length
            ]
        except OSError:
            return None
        candidates.sort(key=lambda item: item.stat().st_mtime, reverse=True)
        for candidate in candidates[:3]:
            decrypted = self._decrypt_existing_image_file(str(candidate))
            if decrypted is not None:
                return decrypted
        return None

    def _download_image_from_image_store(self, incoming: IncomingMessage) -> Path | None:
        for candidate in self._image_store_candidates(incoming)[:5]:
            decrypted = self._decrypt_existing_image_file(str(candidate))
            if decrypted is not None:
                return decrypted
        return None

    def _wait_for_image_store_image(self, incoming: IncomingMessage) -> Path | None:
        deadline = time.monotonic() + IMAGE_STORE_POLL_SECONDS
        last_sizes: dict[Path, int] = {}
        attempted_sizes: set[tuple[Path, int]] = set()
        while time.monotonic() < deadline:
            candidates = self._image_store_candidates(incoming)
            for candidate in candidates[:8]:
                try:
                    size = candidate.stat().st_size
                except OSError:
                    continue
                if size <= 0:
                    continue
                if last_sizes.get(candidate) != size:
                    last_sizes[candidate] = size
                    continue
                marker = (candidate, size)
                if marker in attempted_sizes:
                    continue
                attempted_sizes.add(marker)
                decrypted = self._decrypt_existing_image_file(str(candidate))
                if decrypted is not None:
                    return decrypted
            time.sleep(IMAGE_STORE_POLL_INTERVAL_SECONDS)
        LOG.warning("delayed image-store fallback timed out: msg=%s waited=%.1fs", incoming.id, IMAGE_STORE_POLL_SECONDS)
        return None

    def _image_store_candidates(self, incoming: IncomingMessage) -> list[Path]:
        exact = Path(incoming.extra) if incoming.extra else None
        thumb = Path(incoming.thumb) if incoming.thumb else None
        candidate_dirs: list[Path] = []
        sort_time = time.time()
        thumb_size = 0
        if exact is not None:
            candidate_dirs.append(exact.parent)
            try:
                sort_time = exact.stat().st_mtime if exact.exists() else exact.parent.stat().st_mtime
            except OSError:
                pass
        try:
            if thumb is not None and "Thumb" in thumb.parts:
                thumb_index = thumb.parts.index("Thumb")
                month = thumb.parent.name
                candidate_dirs.append(Path(*thumb.parts[:thumb_index]) / "Image" / month)
                thumb_size = thumb.stat().st_size if thumb.exists() else 0
                if thumb.exists():
                    sort_time = thumb.stat().st_mtime
            seen: set[Path] = set()
            candidates: list[Path] = []
            if exact is not None and exact.exists() and exact.is_file():
                candidates.append(exact)
                seen.add(exact)
            for image_dir in candidate_dirs:
                if image_dir in seen or not image_dir.exists():
                    continue
                seen.add(image_dir)
                for item in image_dir.iterdir():
                    if item in seen or not item.is_file():
                        continue
                    item_stat = item.stat()
                    if item_stat.st_size > thumb_size and abs(item_stat.st_mtime - sort_time) <= 900:
                        candidates.append(item)
                        seen.add(item)
        except (OSError, ValueError):
            return []
        candidates.sort(key=lambda item: (0 if exact is not None and item == exact else 1, abs(item.stat().st_mtime - sort_time), -item.stat().st_size))
        return candidates

    def _decrypt_existing_image_file(self, path: str) -> Path | None:
        if not path or not Path(path).exists():
            return None
        local = self._decrypt_wechat_dat_xor(Path(path))
        if local is not None:
            return local
        decrypted = self._call_wcf_with_timeout(
            "decrypt_image",
            WCF_DECRYPT_TIMEOUT_SECONDS,
            self.wcf.decrypt_image,
            path,
            str(self.images_dir),
        )
        return Path(decrypted) if decrypted else None

    def _call_wcf_with_timeout(self, label: str, timeout: float, func: Any, *args: Any) -> Any | None:
        result: Queue[tuple[bool, Any]] = Queue(maxsize=1)

        def run() -> None:
            try:
                result.put((True, func(*args)))
            except Exception as exc:
                result.put((False, exc))

        Thread(target=run, name=f"WCF-{label}", daemon=True).start()
        try:
            ok, value = result.get(timeout=timeout)
        except Empty:
            LOG.warning("%s timed out after %.1fs", label, timeout)
            return None
        if ok:
            return value
        LOG.error("%s failed", label, exc_info=(type(value), value, value.__traceback__))
        return None

    def _decrypt_wechat_dat_xor(self, path: Path) -> Path | None:
        try:
            data = path.read_bytes()
        except OSError:
            return None
        if not data:
            return None

        for suffix, signature in IMAGE_SIGNATURES:
            if len(data) < len(signature):
                continue
            key = data[0] ^ signature[0]
            if bytes(byte ^ key for byte in data[: len(signature)]) != signature:
                continue
            decrypted_data = bytes(byte ^ key for byte in data)
            if not _looks_like_complete_image(suffix, decrypted_data):
                LOG.debug(
                    "xor image decrypt skipped incomplete image: path=%s suffix=%s size=%s",
                    path,
                    suffix,
                    len(data),
                )
                return None
            output = self.images_dir / f"{path.stem}{suffix}"
            try:
                if (
                    not output.exists()
                    or output.stat().st_size != len(data)
                    or output.stat().st_mtime < path.stat().st_mtime
                ):
                    output.write_bytes(decrypted_data)
            except OSError:
                LOG.exception("xor image decrypt failed: path=%r output=%r", str(path), str(output))
                return None
            LOG.warning("decrypt_image used xor fallback: path=%s output=%s", path, output)
            return output
        return None


def _looks_like_complete_image(suffix: str, data: bytes) -> bool:
    if suffix == ".jpg":
        end_marker_index = data.rfind(b"\xff\xd9")
        return end_marker_index >= 0 and len(data) - end_marker_index <= 64
    if suffix == ".png":
        return b"IEND\xaeB`\x82" in data[-64:]
    if suffix == ".gif":
        return data.endswith(b";")
    return True


def _file_size_stable(path: Path, samples: int = 2, interval: float = 0.6, timeout: float = 15.0) -> bool:
    """True once the file size holds steady across consecutive samples and is
    non-zero - WeChat writes attachments progressively, so existence alone
    means 'partially downloaded'."""
    deadline = time.monotonic() + timeout
    stable_count = 0
    last_size = -1
    while time.monotonic() < deadline:
        try:
            size = path.stat().st_size
        except OSError:
            return False
        if size <= 0:
            stable_count = 0
        elif size == last_size:
            stable_count += 1
            if stable_count >= samples:
                return True
        else:
            stable_count = 0
        last_size = size
        time.sleep(interval)
    return False


def _file_format_complete(path: Path) -> bool:
    """Cheap format-level completeness checks: a finished PDF ends with
    %%EOF near the tail; a finished docx is a valid zip."""
    try:
        suffix = path.suffix.lower()
        if suffix == ".pdf":
            size = path.stat().st_size
            with path.open("rb") as handle:
                handle.seek(max(0, size - 2048))
                tail = handle.read()
            return b"%%EOF" in tail
        if suffix == ".docx":
            import zipfile

            return zipfile.ZipFile(str(path)).testzip() is None
    except Exception:
        return False
    return True  # unknown formats: size stability is all we can check


def _await_complete_file(path: Path, incoming_id, timeout: float = 15.0) -> Path | None:
    """Block until the downloaded file looks complete; None on timeout."""
    if _file_size_stable(path, timeout=timeout) and _file_format_complete(path):
        return path
    if _file_size_stable(path, samples=1, interval=0.3, timeout=2.0) and not _file_format_complete(path):
        # stable size but format check fails -> likely corrupt/truncated
        LOG.warning(
            "download_file incomplete format msg=%s path=%s size=%s (size stable but format check failed)",
            incoming_id,
            path,
            _safe_size(path),
        )
        return None
    LOG.warning(
        "download_file still transferring msg=%s path=%s waited=%.0fs",
        incoming_id,
        path,
        timeout,
    )
    return None

def _copy_to_debug_log(source: Path, log_dir: Path, msg_id: int) -> Path | None:
    try:
        if not source.exists() or not source.is_file():
            return None
        log_dir.mkdir(parents=True, exist_ok=True)
        suffix = source.suffix or ".bin"
        target = log_dir / f"{msg_id}_{int(time.time() * 1000)}_{source.stem}{suffix}"
        if source.resolve() == target.resolve():
            return target
        shutil.copy2(source, target)
        LOG.debug("download debug copy saved: source=%s target=%s", source, target)
        return target
    except OSError:
        LOG.exception("download debug copy failed: source=%s log_dir=%s", source, log_dir)
        return None


def _first_existing_file(candidates: list[str]) -> Path | None:
    for item in candidates:
        if not item:
            continue
        path = Path(item)
        if path.exists() and path.is_file():
            return path
    return None


def _safe_size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


def _row_int(row: dict[str, object], key: str) -> int:
    value = row.get(key)
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _row_float(row: dict[str, object], key: str) -> float:
    value = row.get(key)
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _wechat_create_time_to_seconds(value: float) -> float:
    if value > 10_000_000_000:
        return value / 1000.0
    return value


def _unique_ints(values: tuple[int, ...]) -> tuple[int, ...]:
    seen: set[int] = set()
    result: list[int] = []
    for value in values:
        if value <= 0 or value in seen:
            continue
        seen.add(value)
        result.append(value)
    return tuple(result)


def _row_revoke_id_candidates(row: dict[str, object]) -> tuple[int, ...]:
    priority_keys = ("localId", "MsgLocalId", "MsgSvrID", "msgId", "MsgId", "id", "Id")
    values: list[int] = []
    for key in priority_keys:
        values.append(_row_int(row, key))
    for key, value in row.items():
        if "id" not in str(key).lower():
            continue
        try:
            values.append(int(value))
        except (TypeError, ValueError):
            continue
    return _unique_ints(tuple(values))
