"""DAG Core — Node, topological sort, cycle detection, parallel‑ready resolution."""

import uuid
from enum import Enum


class NodeStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class DAGNode:
    """A single task node in a DAG."""

    __slots__ = ("id", "description", "teammate", "deps", "status",
                 "result", "error", "execution_id",
                 "max_retry", "retry_count", "strategy",
                 "require_approval", "required_skills",
                 "selected_teammate_id", "assigned_at")

    def __init__(self, description: str = "", teammate: str = "",
                 deps: list[str] | None = None,
                 max_retry: int = 0, strategy: str = "linear",
                 require_approval: bool = False,
                 required_skills: list[str] | None = None,
                 selected_teammate_id: str = ""):
        self.id = f"node_{uuid.uuid4().hex[:12]}"
        self.description = description
        self.teammate = teammate or ""
        self.deps = deps or []
        self.status = NodeStatus.PENDING
        self.result = ""
        self.error = ""
        self.execution_id = ""
        self.max_retry = max_retry
        self.retry_count = 0
        self.strategy = strategy
        self.require_approval = require_approval
        self.required_skills = required_skills or []
        self.selected_teammate_id = selected_teammate_id or ""
        self.assigned_at = 0.0

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "description": self.description[:200],
            "teammate": self.teammate,
            "deps": self.deps,
            "status": self.status.value,
            "result": self.result[:500] if self.result else "",
            "error": self.error[:200] if self.error else "",
            "execution_id": self.execution_id[:16] if self.execution_id else "",
            "max_retry": self.max_retry,
            "retry_count": self.retry_count,
            "strategy": self.strategy,
            "require_approval": self.require_approval,
            "required_skills": list(self.required_skills),
            "selected_teammate_id": self.selected_teammate_id,
            "assigned_at": self.assigned_at,
        }


class DAGDefinition:
    """A directed acyclic graph of task nodes."""

    def __init__(self, name: str = ""):
        self.id = f"dag_{uuid.uuid4().hex[:12]}"
        self.name = name or self.id
        self.nodes: dict[str, DAGNode] = {}

    def add_node(self, node: DAGNode) -> None:
        self.nodes[node.id] = node

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "nodes": {nid: n.to_dict() for nid, n in self.nodes.items()},
            "node_count": len(self.nodes),
        }


def topological_sort(dag: DAGDefinition) -> list[str]:
    """Kahn's algorithm. Returns node IDs in topological order. Raises ValueError on cycle."""
    in_degree = {nid: len(n.deps) for nid, n in dag.nodes.items()}
    queue = [nid for nid, deg in in_degree.items() if deg == 0]
    sorted_ids: list[str] = []

    while queue:
        nid = queue.pop(0)
        sorted_ids.append(nid)
        for other_nid, other_node in dag.nodes.items():
            if nid in other_node.deps and nid != other_nid:
                in_degree[other_nid] -= 1
                if in_degree[other_nid] == 0:
                    queue.append(other_nid)

    if len(sorted_ids) != len(dag.nodes):
        raise ValueError("Cycle detected in DAG")
    return sorted_ids


def detect_cycle(dag: DAGDefinition) -> bool:
    """Returns True if the DAG contains a cycle."""
    try:
        topological_sort(dag)
        return False
    except ValueError:
        return True


def get_ready_nodes(dag: DAGDefinition) -> list[DAGNode]:
    """Nodes whose deps are all COMPLETED."""
    ready: list[DAGNode] = []
    for node in dag.nodes.values():
        if node.status != NodeStatus.PENDING:
            continue
        if all(
            dag.nodes[did].status == NodeStatus.COMPLETED
            for did in node.deps
            if did in dag.nodes
        ):
            ready.append(node)
    return ready
