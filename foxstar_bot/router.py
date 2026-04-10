from __future__ import annotations

import json
import re

from .llm_client import TERMINAL_REJECT_TOOL_NAME
from .reply_style import split_reply_messages
from .style_profiles import parse_stored_style

import logging
from concurrent.futures import ThreadPoolExecutor
from threading import Lock
from .context_store import CONTEXT_COMPRESSION_MESSAGES, ContextStore, normalize_context_messages
from .persistence import utc_now
from .privacy import redact_private_ids

LOG = logging.getLogger(__name__)

from typing import Any
