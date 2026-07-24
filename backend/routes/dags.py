"""DAG API routes — create, view, execute DAGs (v2, DB-backed)."""

from fastapi import APIRouter, HTTPException, Depends
from backend.middleware.auth import require_admin
from pydantic import BaseModel

from backend.services.dag.core import DAGDefinition, DAGNode, detect_cycle, topological_sort
from backend.services.dag.executor import get_dag_store, execute_dag
from backend.services.runtime.executor import ExecutionRuntime
from backend.routes.maeos import get_runtime

router = APIRouter(prefix="/api/dags", tags=["dags"])


class NodeDef(BaseModel):
    """User-supplied node definition."""
    id: str = ""               # optional — server generates if empty
    description: str = ""
    teammate: str = ""
    deps: list[str] = []
    max_retry: int = 0
    strategy: str = "linear"
    require_approval: bool = False


class CreateDAGRequest(BaseModel):
    name: str = ""
    nodes: list[NodeDef]


@router.post("", dependencies=[Depends(require_admin)])
async def create_dag(req: CreateDAGRequest):
    dag = DAGDefinition(name=req.name)
    id_map: dict[str, str] = {}  # user-provided id → server node id

    # Pass 1: create nodes, register id_map
    for ndef in req.nodes:
        node = DAGNode(
            description=ndef.description,
            teammate=ndef.teammate,
            max_retry=ndef.max_retry,
            strategy=ndef.strategy,
            require_approval=ndef.require_approval,
        )
        if ndef.id:
            node.id = ndef.id
            id_map[ndef.id] = node.id
        dag.add_node(node)

    # Pass 2: remap deps from user ids to node ids
    for ndef, node in zip(req.nodes, dag.nodes.values()):
        node.deps = [id_map.get(d, d) for d in ndef.deps]

    if detect_cycle(dag):
        raise HTTPException(400, "DAG contains a cycle")

    topo = topological_sort(dag)
    await get_dag_store().save(dag)
    return {"dag": dag.to_dict(), "topological_order": topo}


@router.get("")
async def list_dags():
    store = get_dag_store()
    return {"dags": [d.to_dict() for d in await store.list()]}


@router.get("/{dag_id}")
async def get_dag(dag_id: str):
    store = get_dag_store()
    dag = await store.get(dag_id)
    if not dag:
        raise HTTPException(404, "DAG not found")
    return dag.to_dict()

@router.post("/{dag_id}/execute")
async def execute_dag_route(dag_id: str, runtime: ExecutionRuntime = Depends(get_runtime)):
    store = get_dag_store()
    dag = await store.get(dag_id)
    if not dag:
        raise HTTPException(404, "DAG not found")

    try:
        dag = await execute_dag(dag, runtime)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(500, f"DAG execution failed: {e}")

    return dag.to_dict()
