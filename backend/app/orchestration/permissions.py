"""
Which role may use which agent (SCRUM-21: "Only permitted agents can be
accessed by each role").

The backend decides this from the roles stored for the logged-in user,
never from anything the client sends (BRD §9).

    CLIENT  -> client agent only
    LAWYER  -> lawyer agent, plus the client agent (plain-language
               explanations a lawyer can share with a client)
    JUDGE   -> judge support agent only
    ADMIN   -> every agent (testing and evaluation)

The same table governs handoffs: an agent can hand work to another agent
only if the current user may use that agent.
"""

from __future__ import annotations

from app.agents.base import CLIENT_AGENT, JUDGE_SUPPORT_AGENT, LAWYER_AGENT

AGENT_PERMISSIONS: dict[str, frozenset[str]] = {
    "CLIENT": frozenset({CLIENT_AGENT}),
    "LAWYER": frozenset({LAWYER_AGENT, CLIENT_AGENT}),
    "JUDGE": frozenset({JUDGE_SUPPORT_AGENT}),
    "ADMIN": frozenset({CLIENT_AGENT, LAWYER_AGENT, JUDGE_SUPPORT_AGENT}),
}

# Agent used when nothing else decides, by role (first match wins).
DEFAULT_AGENT_BY_ROLE: tuple[tuple[str, str], ...] = (
    ("JUDGE", JUDGE_SUPPORT_AGENT),
    ("LAWYER", LAWYER_AGENT),
    ("CLIENT", CLIENT_AGENT),
    ("ADMIN", LAWYER_AGENT),
)


def normalise_roles(roles) -> frozenset[str]:
    return frozenset(str(r).upper() for r in roles if r)


def roles_of(user) -> frozenset[str]:
    """Role codes of a User model (or a test double with role_assignments)."""
    return normalise_roles(
        a.role.code for a in getattr(user, "role_assignments", []) if a.role is not None
    )


def permitted_agents(roles) -> frozenset[str]:
    allowed: set[str] = set()
    for role in normalise_roles(roles):
        allowed |= AGENT_PERMISSIONS.get(role, frozenset())
    return frozenset(allowed)


def can_use(roles, agent: str) -> bool:
    return agent in permitted_agents(roles)


def default_agent(roles) -> str | None:
    roles = normalise_roles(roles)
    for role, agent in DEFAULT_AGENT_BY_ROLE:
        if role in roles and can_use(roles, agent):
            return agent
    return None
