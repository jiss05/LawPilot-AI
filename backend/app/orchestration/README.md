# LangGraph orchestrator (SCRUM-21)

```
START → classify → route ─┬→ retrieve → run_agent ⇄ handoff → finalize → END
                          └→ reject (out of scope / forbidden agent)  → END
          any unexpected error → fail_safe (safe message, partial answer kept) → END
```

| File | Purpose |
|---|---|
| `graph.py` | `LegalOrchestrator`, which holds the nodes and edges |
| `state.py` | `OrchestratorState`, the shared state that every node reads and updates |
| `classifier.py` | Classifies intent with keyword rules first and asks the model only when the rules aren't sure |
| `permissions.py` | Which role may use which agent |
| `../agents/base.py` | The `Agent` interface: `AgentContext` in, `AgentResult` out |
| `../agents/default_agents.py` | Baseline Client, Lawyer and Judge Support agents |
| `../agents/registry.py` | Where agents are registered by name |

## API

```http
GET  /api/v1/assistant/agents          → agents the logged-in user may use
POST /api/v1/assistant/chat
{ "message": "Can my landlord evict me without notice?",
  "agent": null,                       // optional: "client" | "lawyer" | "judge_support"
  "conversation_id": null,             // optional: continue a conversation
  "use_knowledge_base": true }
```

The response contains `answer`, `answered_by`, `intent`, `route_reason`, `citations`,
`handoffs`, `status` (`completed | degraded | rejected | failed`), `warnings`, `trace`
and `request_id`. If you ask for an agent your role may not use, you get a **403**.

## Intents and routing

| Intent | Preferred agents (first permitted wins) |
|---|---|
| `legal_information` | client, lawyer, judge_support |
| `legal_research` | lawyer, judge_support, client |
| `document_drafting` | lawyer, client |
| `case_analysis` | judge_support, lawyer |
| `out_of_scope` | rejected; no model call is made |

## Permissions

| Role | Agents |
|---|---|
| CLIENT | client |
| LAWYER | lawyer, client |
| JUDGE | judge_support |
| ADMIN | all |

Roles always come from the database, never from the request body.

## Handoffs

An agent requests a handoff by returning `AgentResult(handoff_to="lawyer", handoff_reason=...)`.
The orchestrator accepts the handoff only when all of these hold:
* the user's role may use the target agent,
* the target agent hasn't already run (this prevents loops),
* fewer than `MAX_HANDOFFS` (2) handoffs have happened so far.

The next agent receives the earlier agent's draft in `previous_outputs`. Every handoff is recorded
in `handoffs`, whether it was accepted or refused, along with the reason.

Example: a client asks for a legal notice to be drafted. The client agent asks to hand off to the
lawyer agent, but clients may not use that agent. The client gets general information and a note
to consult an advocate.

## Failures

| What fails | Result |
|---|---|
| Retrieval (Qdrant or database down) | The answer is given without sources. Status `degraded`, warning `retrieval_unavailable` |
| Model unavailable or timed out | A safe "temporarily unavailable" message, or the earlier agent's answer if a handoff was in progress |
| Unexpected exception in a node | `fail_safe` returns a safe message. The error type is logged; the user sees no internal details |

## Plugging in the full agents (SCRUM-22/23/25)

Implement `run(context, gateway) -> AgentResult` and register the agent under the same name in
`app/agents/registry.py`. The routing, permissions and API need no change.
