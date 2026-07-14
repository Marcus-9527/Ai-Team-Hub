"""routes/teams.py — Team template API.

POST /api/teams/template — one-click AI team creation.
"""
from fastapi import APIRouter, Depends, HTTPException
from backend.middleware.auth import require_admin
from sqlalchemy.ext.asyncio import AsyncSession
from backend.database import get_db
from backend.models import Channel, Teammate, gen_uuid

router = APIRouter(prefix="/api/teams", tags=["teams"])


_TEMPLATES = {
    "default": {
        "channel_name": "General",
        "channel_desc": "Main collaboration channel",
        "teammates": [
            {"name": "高级工程师", "role": "engineer", "avatar_emoji": "👨‍💻",
             "system_prompt": "You are a Senior Engineer. Write clean, efficient, well-tested code."},
            {"name": "产品经理", "role": "pm", "avatar_emoji": "🧠",
             "system_prompt": "You are a Product Manager. Focus on user needs, strategy, and priorities."},
            {"name": "设计师", "role": "designer", "avatar_emoji": "🎨",
             "system_prompt": "You are a UI/UX Designer. Create intuitive, beautiful interfaces."},
        ],
    },
    "devops": {
        "channel_name": "DevOps",
        "channel_desc": "Infrastructure & deployment operations",
        "teammates": [
            {"name": "DevOps工程师", "role": "engineer", "avatar_emoji": "🔧",
             "system_prompt": "You are a DevOps Engineer. Manage infrastructure, CI/CD, monitoring."},
            {"name": "安全审查员", "role": "reviewer", "avatar_emoji": "🛡️",
             "system_prompt": "You are a Security Reviewer. Audit deployments and flag risks."},
        ],
    },
}


@router.post("/template", dependencies=[Depends(require_admin)])
async def create_team_from_template(data: dict, db: AsyncSession = Depends(get_db)):
    """Create a channel + teammates from a named template."""
    template_name = data.get("template", "default")
    tmpl = _TEMPLATES.get(template_name)
    if not tmpl:
        raise HTTPException(404, f"Unknown template: {template_name}")

    api_key_ref = data.get("api_key_ref", "")
    provider = data.get("provider", "openrouter")
    model = data.get("model", "openrouter/auto")

    # 1. Create channel
    channel = Channel(
        name=tmpl["channel_name"],
        description=tmpl["channel_desc"],
    )
    db.add(channel)
    await db.flush()

    # 2. Create teammates
    teammate_ids = []
    for spec in tmpl["teammates"]:
        tm = Teammate(
            name=spec["name"],
            role=spec["role"],
            avatar_emoji=spec["avatar_emoji"],
            system_prompt=spec["system_prompt"],
            model_provider=provider,
            model_name=model,
            api_key_ref=api_key_ref or None,
        )
        db.add(tm)
        await db.flush()
        teammate_ids.append(tm.id)

    # 3. Wire teammates into channel
    channel.teammate_ids = teammate_ids

    await db.commit()
    await db.refresh(channel)

    return {
        "channel_id": channel.id,
        "channel_name": channel.name,
        "teammate_ids": teammate_ids,
        "teammates": [{
            "id": tid,
            "name": t["name"],
            "role": t["role"],
            "avatar_emoji": t["avatar_emoji"],
        } for tid, t in zip(teammate_ids, tmpl["teammates"])],
    }
