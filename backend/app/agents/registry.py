"""
Agent registry: name -> agent instance used by the orchestrator.

When SCRUM-22/23/25 deliver the full agents, register them here under the
same names ("client", "lawyer", "judge_support"); the orchestrator,
permissions and API need no change.
"""

from __future__ import annotations

from app.agents.base import Agent
from app.agents.default_agents import DEFAULT_AGENTS


class AgentRegistry:
    def __init__(self, agents=()) -> None:
        self._agents: dict[str, Agent] = {}
        for agent in agents:
            self.register(agent)

    def register(self, agent: Agent) -> None:
        self._agents[agent.name] = agent

    def get(self, name: str) -> Agent | None:
        return self._agents.get(name)

    def names(self) -> list[str]:
        return list(self._agents)

    def __contains__(self, name: str) -> bool:
        return name in self._agents


def build_default_registry() -> AgentRegistry:
    return AgentRegistry(DEFAULT_AGENTS)
