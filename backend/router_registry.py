"""Centralized, grouped router registration (replaces hand-listed includes)."""
from fastapi import FastAPI


def register_routers(app: FastAPI) -> None:
    _register_core(app)
    _register_public_api(app)
    _register_automation(app)
    _register_observability(app)
    _register_system(app)


def _register_core(app: FastAPI):
    from backend.routes import channels, teammates, apikeys, messages, models, files, query, team_files, tasks, board_tasks
    from backend.routes.auth import router as auth_router
    for router in (channels.router, teammates.router, apikeys.router, messages.router,
                   models.router, files.router, query.router, team_files.router,
                   tasks.router, board_tasks.router, auth_router):
        app.include_router(router)


def _register_public_api(app: FastAPI):
    from backend.routes.v1 import router as v1_router
    app.include_router(v1_router)


def _register_automation(app: FastAPI):
    from backend.routes.autonomous import router as autonomous_router
    from backend.routes.brain import router as brain_router
    from backend.routes.automation import router as automation_router
    from backend.routes.automation_v2 import router as automation_v2_router
    from backend.routes.demo import router as demo_router
    for router in (autonomous_router, brain_router, automation_router, automation_v2_router, demo_router):
        app.include_router(router)


def _register_observability(app: FastAPI):
    from backend.routes.v1_observability import router as v1_observability_router
    from backend.routes.semantic_cache import router as semantic_cache_router
    from backend.routes.traces import router as traces_router
    from backend.routes.executions import router as executions_router
    from backend.routes.artifacts import router as artifacts_router
    from backend.routes.evaluations import router as evaluations_router
    from backend.routes.dags import router as dags_router
    from backend.routes.approvals import router as approvals_router
    from backend.routes.dashboard import router as dashboard_router
    from backend.routes.policy import router as policy_router
    for router in (v1_observability_router, semantic_cache_router, traces_router,
                   executions_router, artifacts_router, evaluations_router,
                   dags_router, approvals_router, dashboard_router, policy_router):
        app.include_router(router)


def _register_system(app: FastAPI):
    from backend.routes.system import router as system_router
    app.include_router(system_router)
