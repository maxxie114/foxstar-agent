from __future__ import annotations

import logging
import hashlib
import os
from itertools import count
from queue import Full, PriorityQueue
import socket
import time
from pathlib import Path
from threading import Thread

from .auth import AuthService
from .commands import CommandProcessor
from .config import load_config
from .context_store import ContextStore
from .limiter import RateLimiter
from .llm_client import LLMClient
from .logging_setup import configure_logging
from .memory_store import MemoryStore
from .persistence import Database
from .router import MessageRouter
from .skills import SkillRegistry
from .tool_clan import ClanManagementTool
from .tool_code import DaytonaCodeTool
from .tool_docs import DocumentTool
from .tool_research import WebResearchAgent
from .tool_search import SearchTool
from .tool_url import UrlFetchTool
from .tool_vision import VisionTool
from .wcf_adapter import WcfAdapter

LOG = logging.getLogger(__name__)
WORKER_COUNT = 3
WORK_QUEUE_MAXSIZE = 500
STARTUP_DRAIN_SECONDS = 8.0
STARTUP_DRAIN_IDLE_SECONDS = 1.0
INGRESS_DEDUP_TTL_SECONDS = 12.0
INGRESS_FALLBACK_DEDUP_TTL_SECONDS = 4.0
SCHEDULE_POLL_IDLE_SECONDS = 4.0
SCHEDULE_POLL_BUSY_SECONDS = 1.0
# Two bot processes racing for the single-client WCF server inside WeChat
# wedge it and take WeChat down. The lock port is freed by the OS the moment
# the holder dies, so it doubles as a crash-safe single-instance guard.
SINGLE_INSTANCE_LOCK_PORT = 8791
# Distinctive exit code for "lock held elsewhere"; the auto-restart wrapper
# stops instead of tight-looping when it sees this.
EXIT_SINGLE_INSTANCE = 42

_instance_lock_socket: socket.socket | None = None


def _acquire_single_instance_lock() -> bool:
    global _instance_lock_socket
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind(("127.0.0.1", SINGLE_INSTANCE_LOCK_PORT))
        sock.listen(1)
    except OSError:
        sock.close()
        return False
    _instance_lock_socket = sock
    return True


def build_router(
    config_path: str = "config.yaml",
    *,
    adapter: WcfAdapter | None = None,
    llm: LLMClient | None = None,
) -> tuple[MessageRouter, WcfAdapter]:
    """Assemble the agent; callers can inject a transport and model client."""
    # .env first: CLAN_JIELONG_API_KEY and friends must be in os.environ
    # before load_config() reads them (agent_api's own load_dotenv runs too
    # late for config parsing).
    try:
        from dotenv import load_dotenv

        load_dotenv()
    except Exception:
        pass
    config = load_config(config_path)
    configure_logging(config.log_level)

    db = Database(config.storage.sqlite_path)
    context = ContextStore(db)
    memory = MemoryStore(db)
    auth = AuthService(config, db=db, config_path=config_path)
    limiter = RateLimiter(db, config.rate_limits)
    def record_usage(event: dict[str, object]) -> None:
        db.record_token_usage(
            chat_id=str(event.get("chat_id") or ""),
            feature=str(event.get("feature") or "unknown"),
            provider=str(event.get("provider") or "unknown"),
            model=str(event.get("model") or "unknown"),
            api=str(event.get("api") or "unknown"),
            input_tokens=int(event.get("input_tokens") or 0),
            output_tokens=int(event.get("output_tokens") or 0),
            cached_tokens=int(event.get("cached_tokens") or 0),
        )
    llm = llm if llm is not None else LLMClient(
        config.openai_api_key,
        config.model,
        gemini_api_key=config.gemini_api_key,
        openrouter_api_key=config.openrouter_api_key,
        deepseek_api_key=config.deepseek_api_key,
        together_api_key=config.together_api_key,
        lightning_api_key=config.lightning_api_key,
        minimax_api_key=config.minimax_api_key,
        bedrock_api_key=config.bedrock_api_key,
        sambanova_api_key=config.sambanova_api_key,
        cerebras_api_key=config.cerebras_api_key,
        fireworks_api_key=config.fireworks_api_key,
        zai_api_key=config.zai_api_key,
        zai_base_url=config.zai_base_url,
        telnyx_api_key=config.telnyx_api_key,
        telnyx_base_url=config.telnyx_base_url,
        kimi_api_key=config.kimi_api_key,
        kimi_base_url=config.kimi_base_url,
        usage_recorder=record_usage,
    )
    skills = SkillRegistry(Path("skills"))
    commands = CommandProcessor(config, db, memory, config_path=config_path, llm=llm, skills=skills, auth=auth)
    commands.apply_deployed_bug_fixes()  # close reports fixed in code; assign group short codes
    search = SearchTool(config)
    url_fetch = UrlFetchTool()
    research = WebResearchAgent(search, url_fetch, llm)
    code = DaytonaCodeTool(config)
    clan = ClanManagementTool(
        db,
        api_base=config.clan.api_base,
        api_key=config.clan.api_key,
        enabled_groups=config.clan.enabled_groups,
        attendance_api_base=config.clan.attendance_api_base,
        import_groups=config.clan.import_groups,
    )
    docs = DocumentTool(db, config.storage.files_dir)
    vision = VisionTool(db, config.storage.images_dir, llm)
    adapter = adapter if adapter is not None else WcfAdapter(
        config.storage.images_dir,
        config.storage.files_dir,
        host=config.wcf_host,
        port=config.wcf_port,
    )

    router = MessageRouter(
        config=config,
        db=db,
        auth=auth,
        limiter=limiter,
        context=context,
        memory=memory,
        commands=commands,
        search=search,
        url_fetch=url_fetch,
        research=research,
        code=code,
        docs=docs,
        vision=vision,
        clan=clan,
        llm=llm,
        prompt_path=Path("PROMPT.md"),
        skills=skills,
    )
    return router, adapter


def main() -> None:
    if not _acquire_single_instance_lock():
        print(
            f"another FoxStar instance holds the single-instance lock "
            f"(port {SINGLE_INSTANCE_LOCK_PORT}); exiting",
            flush=True,
        )
        raise SystemExit(EXIT_SINGLE_INSTANCE)
    router, adapter = build_router()
    try:
        _run(router, adapter)
    finally:
        try:
            adapter.shutdown_wcf()
        except Exception:
            pass
        router.close()


def _run(router: MessageRouter, adapter: WcfAdapter) -> None:
    self_wxid = adapter.self_wxid()
    adapter.start_receiving()
    _drain_startup_backlog(adapter)
    LOG.info("FoxStar started. self_wxid=%s", self_wxid)
    work_queue: PriorityQueue = PriorityQueue(maxsize=WORK_QUEUE_MAXSIZE)
    sequence = count()
    recent_ingress: dict[str, float] = {}

    def worker(worker_id: int) -> None:
        LOG.info("worker started id=%s", worker_id)
        while True:
            priority, _seq, msg = work_queue.get()
            try:
                LOG.debug(
                    "dequeue worker=%s priority=%s chat=%s sender=%s type=%s queue_size=%s",
                    worker_id,
                    priority,
                    msg.chat_id,
                    msg.sender,
                    msg.msg_type,
                    work_queue.qsize(),
                )
                router.handle(adapter, msg, self_wxid)
            except Exception:
                LOG.exception("worker failed id=%s", worker_id)
            finally:
                work_queue.task_done()

    for idx in range(WORKER_COUNT):
        Thread(target=worker, name=f"BotWorker-{idx + 1}", args=(idx + 1,), daemon=True).start()

    def schedule_worker() -> None:
        LOG.info("scheduler started")
        while True:
            try:
                if router._check_restart_flag():
                    LOG.info("RESTART_REQUESTED detected by scheduler - graceful shutdown for hot deploy")
                    adapter.shutdown_wcf()
                    os._exit(0)
                ran = router.run_due_scheduled_tasks(adapter)
                router.kick_agent_tasks(adapter)
                time.sleep(SCHEDULE_POLL_BUSY_SECONDS if ran else SCHEDULE_POLL_IDLE_SECONDS)
            except Exception:
                LOG.exception("scheduler failed")
                time.sleep(SCHEDULE_POLL_IDLE_SECONDS)

    Thread(target=schedule_worker, name="BotScheduler", daemon=True).start()

    while True:
        msg = adapter.get_message()
        if msg is None:
            time.sleep(0.1)
            continue
        try:
            if _drop_duplicate_ingress_message(recent_ingress, msg):
                LOG.debug(
                    "ingress_dedup drop chat=%s sender=%s type=%s msg_id=%s",
                    msg.chat_id,
                    msg.sender,
                    msg.msg_type,
                    getattr(msg, "id", 0),
                )
                continue
            if router.handle_fast_command(adapter, msg, self_wxid):
                LOG.debug(
                    "fast_command chat=%s sender=%s type=%s queue_size=%s",
                    msg.chat_id,
                    msg.sender,
                    msg.msg_type,
                    work_queue.qsize(),
                )
                continue
            priority = 0 if router.auth.is_whitelist_user(msg.sender) else 1
            _enqueue_message(work_queue, (priority, next(sequence), msg))
            LOG.debug(
                "enqueue priority=%s chat=%s sender=%s type=%s queue_size=%s",
                priority,
                msg.chat_id,
                msg.sender,
                msg.msg_type,
                work_queue.qsize(),
            )
        except Full:
            LOG.warning(
                "message queue full, dropped message chat=%s sender=%s type=%s priority=%s",
                msg.chat_id,
                msg.sender,
                msg.msg_type,
                priority,
            )
        except Exception:
            LOG.exception("message queue full or unavailable")


def _drain_startup_backlog(adapter: WcfAdapter) -> None:
    deadline = time.monotonic() + STARTUP_DRAIN_SECONDS
    idle_deadline = time.monotonic() + STARTUP_DRAIN_IDLE_SECONDS
    drained = 0
    while time.monotonic() < deadline and time.monotonic() < idle_deadline:
        msg = adapter.get_message()
        if msg is None:
            time.sleep(0.05)
            continue
        drained += 1
        idle_deadline = time.monotonic() + STARTUP_DRAIN_IDLE_SECONDS
    if drained:
        LOG.warning("drained startup WeChat message backlog count=%s", drained)


def _enqueue_message(work_queue: PriorityQueue, item: tuple[int, int, object]) -> None:
    priority, _seq, _msg = item
    try:
        work_queue.put(item, block=False)
        return
    except Full:
        if priority != 0:
            raise
    work_queue.put(item, timeout=2)


def _drop_duplicate_ingress_message(recent: dict[str, float], msg: object) -> bool:
    now = time.monotonic()
    expired = [key for key, expires_at in recent.items() if expires_at <= now]
    for key in expired:
        recent.pop(key, None)
    msg_id = int(getattr(msg, "id", 0) or 0)
    chat_id = str(getattr(msg, "chat_id", "") or "")
    sender = str(getattr(msg, "sender", "") or "")
    msg_type = str(getattr(msg, "msg_type", "") or "")
    content = " ".join(str(getattr(msg, "content", "") or "").split())
    keys: list[tuple[str, float]] = []
    if msg_id:
        keys.append((f"id:{chat_id}:{msg_id}", INGRESS_DEDUP_TTL_SECONDS))
    if sender and content:
        digest = hashlib.sha1(f"{chat_id}|{sender}|{msg_type}|{content}".encode("utf-8", errors="ignore")).hexdigest()
        keys.append((f"body:{digest}", INGRESS_FALLBACK_DEDUP_TTL_SECONDS))
    if any(key in recent for key, _ttl in keys):
        return True
    for key, ttl in keys:
        recent[key] = now + ttl
    return False
