"""
Teammate CRUD routes with caching.
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db, async_session
from backend.models import Teammate, TaskExecutionModel
from backend.cache import teammate_cache
from backend.services.cache_warmup_service import invalidate_warmup
from backend.middleware.auth import require_admin, ws_id_of
from backend.services.memory.memory_service import get_memory_service
from backend.services.autonomous.teammate_state import get_state_manager
from backend.services.brain.fragment_store import get_brain_fragment_store

router = APIRouter(prefix="/api/teammates", tags=["teammates"])

LIST_KEY = "all"


def _serialize_teammate(t: Teammate) -> dict:
    return {
        "id": t.id,
        "name": t.name,
        "role": t.role,
        "avatar_emoji": t.avatar_emoji,
        "system_prompt": t.system_prompt,
        "model_provider": t.model_provider,
        "model_name": t.model_name,
        "api_key_ref": t.api_key_ref,
        "skills": t.skills or [],
        "capabilities": t.capabilities or [],
        "success_rate": t.success_rate or 0.0,
        "average_score": t.average_score or 0.0,
        "execution_count": t.execution_count or 0,
    }


@router.get("")
async def list_teammates(request: Request, db: AsyncSession = Depends(get_db)):
    # Try cache first
    cached = teammate_cache.get(LIST_KEY)
    if cached is not None:
        return cached

    ws = ws_id_of(request)
    q = select(Teammate).order_by(Teammate.created_at)
    if ws:
        q = q.where(Teammate.workspace_id == ws)
    result = await db.execute(q)
    teammates = result.scalars().all()
    data = [_serialize_teammate(t) for t in teammates]

    # Populate both list cache and individual caches
    teammate_cache.set(LIST_KEY, data)
    for item in data:
        teammate_cache.set(item["id"], item)

    return data


@router.post("", dependencies=[Depends(require_admin)])
async def create_teammate(data: dict, request: Request, db: AsyncSession = Depends(get_db)):
    ws = ws_id_of(request)
    teammate = Teammate(
        name=data.get("name") or data.get("role") or "AI 队友",
        role=data.get("role", "assistant"),
        avatar_emoji=data.get("avatar_emoji", "🤖"),
        system_prompt=data.get("system_prompt", "You are a helpful AI assistant."),
        model_provider=data["model_provider"],
        model_name=data["model_name"],
        api_key_ref=data.get("api_key_ref"),
        workspace_id=ws or data.get("workspace_id"),
        skills=data.get("skills", []),
        capabilities=data.get("capabilities", []),
    )
    db.add(teammate)
    await db.commit()
    await db.refresh(teammate)

    # Invalidate list cache; cache the new item
    teammate_cache.invalidate(LIST_KEY)
    item = _serialize_teammate(teammate)
    teammate_cache.set(teammate.id, item)

    # B: register as available in the in-memory runtime state so the
    # TASK_CREATED wakeup competition has candidates to claim against.
    # ponytail: ACTIVE = ready to compete; executor flips to WORKING on run.
    try:
        from backend.services.autonomous.teammate_state import get_state_manager
        await get_state_manager().set_active(teammate.id)
    except Exception as e:
        logger.debug("[TEAMMATE] state registration skipped: %s", e)

    return {"id": teammate.id, "name": teammate.name}


@router.get("/{teammate_id}")
async def get_teammate(teammate_id: str, db: AsyncSession = Depends(get_db)):
    # Try cache first
    cached = teammate_cache.get(teammate_id)
    if cached is not None:
        return cached

    result = await db.execute(select(Teammate).where(Teammate.id == teammate_id))
    t = result.scalar_one_or_none()
    if not t:
        raise HTTPException(status_code=404, detail="Teammate not found")

    data = _serialize_teammate(t)
    teammate_cache.set(teammate_id, data)
    # Also invalidate list since it may be stale
    teammate_cache.invalidate(LIST_KEY)
    return data


@router.patch("/{teammate_id}", dependencies=[Depends(require_admin)])
async def update_teammate(teammate_id: str, data: dict, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Teammate).where(Teammate.id == teammate_id))
    t = result.scalar_one_or_none()
    if not t:
        raise HTTPException(status_code=404, detail="Teammate not found")

    for field in ("name", "role", "avatar_emoji", "system_prompt", "model_provider", "model_name", "api_key_ref", "skills", "capabilities"):
        if field in data:
            setattr(t, field, data[field])
    await db.commit()

    # Invalidate caches
    teammate_cache.invalidate(teammate_id)
    teammate_cache.invalidate(LIST_KEY)

    # If system_prompt changed, invalidate all warming + memory for this teammate
    if "system_prompt" in data:
        from backend.services.cache_warmup_service import invalidate_warmup
        invalidate_warmup(teammate_id)

    return {"ok": True}


@router.delete("/{teammate_id}", dependencies=[Depends(require_admin)])
async def delete_teammate(teammate_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Teammate).where(Teammate.id == teammate_id))
    t = result.scalar_one_or_none()
    if not t:
        raise HTTPException(status_code=404, detail="Teammate not found")
    await db.delete(t)
    await db.commit()

    # Invalidate caches
    teammate_cache.invalidate(teammate_id)
    teammate_cache.invalidate(LIST_KEY)

    return {"ok": True}


# ── Phase 7: Teammate Intelligence ──


@router.get("/recommend")
async def recommend_teammate(task_type: str = "general", top_n: int = 3, db: AsyncSession = Depends(get_db)):
    """Recommend teammates for a given task type based on skills + success rate."""
    from backend.services.teammate_intelligence import TeammateSelector
    profiles = await TeammateSelector.recommend(task_type, top_n=top_n, db=db)
    return {"task_type": task_type, "recommendations": [p.to_dict() for p in profiles]}


# ── Phase 14: Teammate Evolution Memory ──


@router.get("/{teammate_id}/memory")
async def get_teammate_memory(teammate_id: str, db: AsyncSession = Depends(get_db)):
    """Return the evolution memory for a teammate."""
    result = await db.execute(select(Teammate).where(Teammate.id == teammate_id))
    t = result.scalar_one_or_none()
    if not t:
        raise HTTPException(status_code=404, detail="Teammate not found")
    return {
        "teammate_id": t.id,
        "name": t.name,
        "strengths": t.strengths or [],
        "weaknesses": t.weaknesses or [],
        "learned_patterns": t.learned_patterns or [],
        "failed_patterns": t.failed_patterns or [],
        "preferred_tools": t.preferred_tools or [],
    }


# ── Phase 22: Teammate Profile Aggregator ──


@router.get("/{teammate_id}/profile")
async def get_teammate_profile(teammate_id: str, db: AsyncSession = Depends(get_db)):
    """Aggregate teammate profile: stats, brain, memory, task history, state."""
    # 1. Teammate record
    result = await db.execute(select(Teammate).where(Teammate.id == teammate_id))
    t = result.scalar_one_or_none()
    if not t:
        raise HTTPException(status_code=404, detail="Teammate not found")

    profile = _serialize_teammate(t)

    # 2. Brain fragments → version / fragment count
    try:
        frags = await get_brain_fragment_store().get_all_by_teammate(teammate_id)
        profile["brain_fragments_count"] = len(frags)
        latest_ver = max((f.version for f in frags), default=0)
        profile["brain_version"] = latest_ver
    except Exception:
        profile["brain_fragments_count"] = 0
        profile["brain_version"] = 0

    # 3. Memory count (source_id = teammate_id)
    try:
        mem_svc = get_memory_service()
        mem_items = await mem_svc.query(source_id=teammate_id)
        profile["memory_count"] = len(mem_items)
    except Exception:
        profile["memory_count"] = 0

    # 4. Task execution stats (from TaskExecutionModel)
    try:
        count_q = (
            select(func.count(TaskExecutionModel.id))
            .where(TaskExecutionModel.teammate_id == teammate_id)
        )
        success_q = (
            select(func.count(TaskExecutionModel.id))
            .where(TaskExecutionModel.teammate_id == teammate_id, TaskExecutionModel.error == "")
        )
        total = (await db.execute(count_q)).scalar() or 0
        success = (await db.execute(success_q)).scalar() or 0
        profile["task_executions"] = {
            "total": total,
            "success": success,
            "failed": total - success,
            "success_rate": round(success / total, 4) if total > 0 else 0.0,
        }
    except Exception:
        profile["task_executions"] = {"total": 0, "success": 0, "failed": 0, "success_rate": 0.0}

    # 5. Current autonomous state
    try:
        mgr = get_state_manager()
        state = mgr.get_state(teammate_id)
        profile["current_state"] = state.state if state else "unknown"
    except Exception:
        profile["current_state"] = "unknown"

    return profile


# ═══════════════════════════════════════════════════════════
# Teammate Blueprint Templates
# ═══════════════════════════════════════════════════════════

PRESET_TEMPLATES = [
    # ── Engineering ──
    {
        "name": "CTO",
        "category": "engineering",
        "description": "首席技术官，制定技术战略与架构决策",
        "identity": "cto",
        "avatar_emoji": "🧑‍💼",
        "system_prompt": "你是一个经验丰富的 CTO。能俯瞰全局技术架构，做出正确的技术选型决策。直接说结论，不用铺垫。回复控制在 50-150 字。",
        "skills": ["architecture", "system-design", "tech-strategy", "leadership"],
        "tools": [],
        "memory_schema": {},
        "automation_defaults": {},
    },
    {
        "name": "Backend Engineer",
        "category": "engineering",
        "description": "后端开发工程师，构建 API 和数据库",
        "identity": "backend-engineer",
        "avatar_emoji": "👨‍💻",
        "system_prompt": "你是一个有 15 年经验的高级后端工程师。直接给答案，代码能短就短，可以吐槽烂代码。回复控制在 50-150 字。",
        "skills": ["python", "api-design", "database", "backend"],
        "tools": [],
        "memory_schema": {},
        "automation_defaults": {},
    },
    {
        "name": "Frontend Engineer",
        "category": "engineering",
        "description": "前端开发工程师，构建用户界面与交互",
        "identity": "frontend-engineer",
        "avatar_emoji": "👩‍💻",
        "system_prompt": "你是一个高级前端工程师。React/TypeScript 精通，关注用户体验和性能。直接说问题，给具体代码。回复控制在 50-150 字。",
        "skills": ["react", "typescript", "css", "frontend"],
        "tools": [],
        "memory_schema": {},
        "automation_defaults": {},
    },
    {
        "name": "QA Engineer",
        "category": "engineering",
        "description": "质量保证工程师，自动化测试与质量把控",
        "identity": "qa-engineer",
        "avatar_emoji": "🧪",
        "system_prompt": "你是一个 QA 工程师。关注测试覆盖率和代码质量。直接指出问题，给具体修复建议。可以开玩笑但结论要明确。回复控制在 50-150 字。",
        "skills": ["testing", "qa", "automation", "ci-cd"],
        "tools": [],
        "memory_schema": {},
        "automation_defaults": {},
    },
    {
        "name": "Security Engineer",
        "category": "engineering",
        "description": "安全工程师，保障系统安全与合规",
        "identity": "security-engineer",
        "avatar_emoji": "🛡️",
        "system_prompt": "你是一个安全工程师。用白话讲安全漏洞，给具体修复建议。可以吐槽烂代码的安全问题。回复控制在 50-150 字。",
        "skills": ["security", "penetration-testing", "audit", "compliance"],
        "tools": [],
        "memory_schema": {},
        "automation_defaults": {},
    },
    # ── Business ──
    {
        "name": "Product Manager",
        "category": "business",
        "description": "产品经理，定义需求与产品方向",
        "identity": "pm",
        "avatar_emoji": "🧠",
        "system_prompt": "你是一个产品经理。直接说重点，用口语不用书面语，可以有自己的观点。回复控制在 50-150 字。",
        "skills": ["product-strategy", "user-research", "requirements", "roadmap"],
        "tools": [],
        "memory_schema": {},
        "automation_defaults": {},
    },
    {
        "name": "Marketing Manager",
        "category": "business",
        "description": "市场经理，制定营销策略与品牌推广",
        "identity": "marketing-manager",
        "avatar_emoji": "📈",
        "system_prompt": "你是一个市场经理。关注增长和 ROI，直接说数据，给可执行的建议。回复控制在 50-150 字。",
        "skills": ["marketing", "growth", "branding", "analytics"],
        "tools": [],
        "memory_schema": {},
        "automation_defaults": {},
    },
    {
        "name": "Sales Assistant",
        "category": "business",
        "description": "销售助理，挖掘商机与客户跟进",
        "identity": "sales-assistant",
        "avatar_emoji": "🤝",
        "system_prompt": "你是一个销售助理。善于沟通，关注客户需求和转化。直接给建议，不用废话。回复控制在 50-150 字。",
        "skills": ["sales", "crm", "communication", "negotiation"],
        "tools": [],
        "memory_schema": {},
        "automation_defaults": {},
    },
    {
        "name": "Customer Support",
        "category": "business",
        "description": "客户支持，解答用户问题与技术排障",
        "identity": "customer-support",
        "avatar_emoji": "💬",
        "system_prompt": "你是一个客户支持。耐心、专业、直接解决问题。可以适当幽默但要把事情说清楚。回复控制在 50-150 字。",
        "skills": ["support", "troubleshooting", "documentation", "empathy"],
        "tools": [],
        "memory_schema": {},
        "automation_defaults": {},
    },
]


def _seed_templates_sync(session):
    """Seed preset templates into the DB if empty."""
    from backend.models import TeammateTemplate
    existing = session.query(TeammateTemplate).count()
    if existing > 0:
        return
    for tpl in PRESET_TEMPLATES:
        session.add(TeammateTemplate(**tpl))
    session.commit()


@router.get("/templates")
async def list_templates(db: AsyncSession = Depends(get_db)):
    """Return all blueprint templates, seeding DB on first call."""
    # ponytail: seed lazily on first read — no startup hook needed
    from sqlalchemy import func as sa_func
    cnt = await db.execute(sa_func.count(TeammateTemplate.id))
    if cnt.scalar() == 0:
        for tpl in PRESET_TEMPLATES:
            db.add(TeammateTemplate(**tpl))
        await db.commit()

    result = await db.execute(select(TeammateTemplate).order_by(TeammateTemplate.category, TeammateTemplate.name))
    templates = result.scalars().all()
    return [
        {
            "id": t.id,
            "name": t.name,
            "category": t.category,
            "description": t.description,
            "identity": t.identity,
            "system_prompt": t.system_prompt,
            "skills": t.skills or [],
            "tools": t.tools or [],
            "memory_schema": t.memory_schema or {},
            "automation_defaults": t.automation_defaults or {},
            "avatar_emoji": t.avatar_emoji,
            "model_provider": t.model_provider,
            "model_name": t.model_name,
        }
        for t in templates
    ]


@router.post("/from-template", dependencies=[Depends(require_admin)])
async def create_from_template(data: dict, db: AsyncSession = Depends(get_db)):
    """Create a teammate from a blueprint template."""
    template_id = data.get("template_id")
    if not template_id:
        raise HTTPException(status_code=400, detail="template_id is required")

    result = await db.execute(select(TeammateTemplate).where(TeammateTemplate.id == template_id))
    tpl = result.scalar_one_or_none()
    if not tpl:
        raise HTTPException(status_code=404, detail="Template not found")

    name = data.get("name") or tpl.name

    teammate = Teammate(
        name=name,
        role=data.get("role") or tpl.identity or "assistant",
        avatar_emoji=data.get("avatar_emoji") or tpl.avatar_emoji,
        system_prompt=data.get("system_prompt") or tpl.system_prompt,
        model_provider=data.get("model_provider") or tpl.model_provider,
        model_name=data.get("model_name") or tpl.model_name,
        api_key_ref=data.get("api_key_ref"),
        skills=tpl.skills or [],
        capabilities=data.get("capabilities", []),
    )
    db.add(teammate)
    await db.commit()
    await db.refresh(teammate)

    teammate_cache.invalidate(LIST_KEY)
    try:
        await get_state_manager().set_active(teammate.id)
    except Exception:
        pass

    return {"id": teammate.id, "name": teammate.name}
