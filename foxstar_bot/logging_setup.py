import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path


def configure_logging(level: str) -> None:
    log_level = getattr(logging, level.upper(), logging.INFO)
    log_dir = Path("logs")
    log_dir.mkdir(parents=True, exist_ok=True)
    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    root.handlers.clear()

    console = logging.StreamHandler()
    console.setFormatter(formatter)
    console.setLevel(log_level)

    debug_file = RotatingFileHandler(log_dir / "bot-debug.log", maxBytes=2_000_000, backupCount=5, encoding="utf-8")
    debug_file.setFormatter(formatter)
    debug_file.setLevel(logging.DEBUG)

    error_file = RotatingFileHandler(log_dir / "error.log", maxBytes=2_000_000, backupCount=5, encoding="utf-8")
    error_file.setFormatter(formatter)
    error_file.setLevel(logging.ERROR)

    reply_gate_file = RotatingFileHandler(log_dir / "reply-gate.log", maxBytes=2_000_000, backupCount=5, encoding="utf-8")
    reply_gate_file.setFormatter(logging.Formatter("%(message)s"))
    reply_gate_file.setLevel(logging.INFO)

    decision_shadow_file = RotatingFileHandler(log_dir / "decision-shadow.log", maxBytes=2_000_000, backupCount=5, encoding="utf-8")
    decision_shadow_file.setFormatter(logging.Formatter("%(message)s"))
    decision_shadow_file.setLevel(logging.INFO)

    tool_trace_file = RotatingFileHandler(log_dir / "tool-trace.log", maxBytes=5_000_000, backupCount=5, encoding="utf-8")
    tool_trace_file.setFormatter(logging.Formatter("%(message)s"))
    tool_trace_file.setLevel(logging.INFO)

    testing_mode_file = RotatingFileHandler(log_dir / "testing-mode.log", maxBytes=5_000_000, backupCount=5, encoding="utf-8")
    testing_mode_file.setFormatter(logging.Formatter("%(message)s"))
    testing_mode_file.setLevel(logging.INFO)

    game_file = RotatingFileHandler(log_dir / "game.log", maxBytes=5_000_000, backupCount=5, encoding="utf-8")
    game_file.setFormatter(formatter)
    game_file.setLevel(logging.INFO)

    root.addHandler(console)
    root.addHandler(debug_file)
    root.addHandler(error_file)
    root.addHandler(game_file)

    reply_gate_logger = logging.getLogger("foxstar_bot.reply_gate")
    reply_gate_logger.handlers.clear()
    reply_gate_logger.setLevel(logging.INFO)
    reply_gate_logger.addHandler(reply_gate_file)
    decision_shadow_logger = logging.getLogger("foxstar_bot.decision_shadow")
    decision_shadow_logger.propagate = False
    decision_shadow_logger.setLevel(logging.INFO)
    decision_shadow_logger.addHandler(decision_shadow_file)
    reply_gate_logger.propagate = False

    tool_trace_logger = logging.getLogger("foxstar_bot.tool_trace")
    tool_trace_logger.handlers.clear()
    tool_trace_logger.setLevel(logging.INFO)
    tool_trace_logger.addHandler(tool_trace_file)
    tool_trace_logger.propagate = False

    testing_mode_logger = logging.getLogger("foxstar_bot.testing_mode")
    testing_mode_logger.handlers.clear()
    testing_mode_logger.setLevel(logging.INFO)
    testing_mode_logger.addHandler(testing_mode_file)
    testing_mode_logger.propagate = False

    game_logger = logging.getLogger("foxstar_bot.game")
    game_logger.handlers.clear()
    game_logger.setLevel(logging.INFO)
    game_logger.addHandler(game_file)
    game_logger.propagate = False

    # Keep our bot traces verbose while preventing SDK wire logs from flooding
    # bot-debug.log with full request payloads.
    for noisy_logger in ("openai", "httpx", "httpcore", "urllib3"):
        logging.getLogger(noisy_logger).setLevel(logging.INFO)

    logging.getLogger(__name__).debug(
        "logging configured level=%s debug_file=%s",
        logging.getLevelName(log_level),
        log_dir / "bot-debug.log",
    )
