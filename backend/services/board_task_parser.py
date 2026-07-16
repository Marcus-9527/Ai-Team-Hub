"""
board_task_parser.py — Parse AI replies for explicit "create task" directives
and persist them as BoardTasks scoped to the channel's workspace.

Directive protocol (one per line, inside an AI reply):
    [TASK] <title>            → open board task, default priority
    [TASK] <title> | <desc>   → with description
    [TASK] <title> !high      → priority 1 (high); !low → 3; default 2

Ponytail: single regex, no NLP. If a teammate wants a todo on the board it
emits the literal directive; we never guess. Best-effort: a parse failure on
one line does not break the others.
"""
import logging
import re

from backend.database import async_session
from backend.models import BoardTask, Channel

logger = logging.getLogger("board_task_parser")

# [TASK] Title | desc !priority   (priority token optional)
_DIRECTIVE = re.compile(
    r"^\[TASK\]\s*(?P<title>.+?)\s*"
    r"(?:\|\s*(?P<desc>.+?))?\s*"
    r"(?P<prio>!high|!low)?\s*$"
)

_PRIORITY = {"!high": 1, "!low": 3}


def parse_task_directives(text: str) -> list[dict]:
    """Return list of {title, description, priority} parsed from reply text."""
    out = []
    if not text:
        return out
    for line in text.splitlines():
        m = _DIRECTIVE.match(line.strip())
        if not m:
            continue
        title = m.group("title").strip()
        if not title:
            continue
        prio = _PRIORITY.get(m.group("prio"), 2)
        out.append({
            "title": title,
            "description": (m.group("desc") or "").strip(),
            "priority": prio,
        })
    return out


async def create_board_tasks_from_reply(channel_id: str, text: str, created_by: str = "ai") -> int:
    """Parse directives and persist BoardTasks. Returns count created.

    Scopes each task to the channel's workspace_id (never trusts the reply for
    tenancy). No-op if the channel is missing.
    """
    directives = parse_task_directives(text)
    if not directives:
        return 0
    async with async_session() as db:
        ch = (await db.execute(
            __import__("sqlalchemy").select(Channel).where(Channel.id == channel_id)
        )).scalar_one_or_none()
        if ch is None or not ch.workspace_id:
            logger.debug("[board-task] channel %s missing ws, skip", channel_id[:8])
            return 0
        ws = ch.workspace_id
        created = 0
        for d in directives:
            db.add(BoardTask(
                workspace_id=ws,
                channel_id=channel_id,
                title=d["title"],
                description=d["description"],
                priority=d["priority"],
                created_by=created_by,
            ))
            created += 1
        await db.commit()
        if created:
            logger.info("[board-task] created %d task(s) in channel %s", created, channel_id[:8])
    return created
