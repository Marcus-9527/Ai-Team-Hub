"""
agent_context.py — AgentContext data structures.
"""

from dataclasses import dataclass, field
from typing import Optional
from enum import Enum


class AgentRole(Enum):
    ANALYSIS = "analysis"
    CODE = "code"
    REASONING = "reasoning"
    JUDGE = "judge"
    COORDINATOR = "coordinator"


@dataclass
class AgentContext:
    agent_id: str
    role: AgentRole
    system_prompt: str
    memory_namespace: str
    history_namespace: str
    retrieval_namespace: str
    tools_subset: list[str] = field(default_factory=list)
    identity_lock: str = ""

    def __post_init__(self):
        if not self.identity_lock:
            self.identity_lock = f"[IDENTITY LOCK]\nYou are Agent {self.agent_id} only.\nRole: {self.role.value}"


@dataclass
class AgentOutput:
    agent_id: str
    result: str
    confidence: float = 0.5
    tokens_used: int = 0
    cache_hit: bool = False
    metadata: dict = field(default_factory=dict)


@dataclass
class CoordinatorRequest:
    task_id: str
    user_input: str
    intent: str = ""
    selected_agents: list[str] = field(default_factory=list)
    context_snapshot: dict = field(default_factory=dict)


@dataclass
class CoordinatorResponse:
    task_id: str
    agent_outputs: list[AgentOutput] = field(default_factory=list)
    final_result: str = ""
    merged: bool = False
    metadata: dict = field(default_factory=dict)
