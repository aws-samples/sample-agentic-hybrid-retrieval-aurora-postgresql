# Strands Harness workshop evaluation

Evaluated on September 23–24, 2026 against the workshop Aurora catalog and
Amazon Bedrock, using `global.anthropic.claude-sonnet-5`. This is the open-source
**Strands Harness SDK** (`strands_harness.create_harness`), not the separate
Amazon Bedrock AgentCore managed service.

## Model selection

Yes: `create_harness(model=...)` accepts an explicit model ID or a configured
Strands model instance. The experiment uses Mosaic's configured Bedrock model
instance so its region, retry settings, timeouts and token limit stay explicit:

```python
from strands_harness import create_harness
from service import agent, agent_tools
from service.config import get_settings

settings = get_settings()
retrieval_agent = create_harness(
    model=agent._bedrock_model(settings.agent_model_id, settings.aws_region),
    instructions=agent.catalog_system_prompt(),
    tools=list(agent_tools.TOOL_FUNCTIONS),
    builtin_tools=[],
    builtin_plugins=[],
    background_tasks=False,
    session=False,
    memory=False,
    skills=False,
    context_manager=False,
    hooks=[agent._ToolCallBudget(10)],
    callback_handler=None,
)
```

`BEDROCK_AGENT_MODEL_ID` selects the retrieval model; it falls back to
`BEDROCK_CHAT_MODEL_ID`. `BEDROCK_SYNTHESIS_MODEL_ID` independently selects the
answer-writing model. Changing an ID still requires model access and a new run
of the tool, decline and citation checks. The tested model is Sonnet 5; this
report does not claim that every provider/model combination passed.

This fragment shows the tested factory configuration, not a drop-in replacement
for Mosaic's request lifecycle. Keep the existing request state, tool limits,
answer-of-record selection, citation checks and saved-run handling around it.

## Retrieval agent

The current application pins Strands Agents 1.48.0. Harness 0.1.2 requires a
newer SDK, so the trial installed Harness 0.1.2 with Strands Agents 1.57.0 in an
isolated environment. It compared the current agent, the current factory with
the newer SDK, and the Harness factory with that same newer SDK. Production
dependency pins were not changed.

| Configuration | Lab 1 | Lab 2 | Lab 3 | Saved-run recheck |
|---|---:|---:|---:|---:|
| Strands Agents 1.48.0 | 10 passed | 15 passed | 19 passed | 31 passed |
| Strands Agents 1.57.0 | 10 passed | 15 passed | 19 passed | 31 passed |
| Harness 0.1.2 + Agents 1.57.0 | 10 passed | 15 passed | 19 passed | 31 passed |

All three used the same real SQL, production HTTP validators, catalog, model
settings and application tools. Each registered exactly five Mosaic tools.
The Harness run recovered from one rejected synthesis result within the existing
bounded application path. A broken Lab 3 evidence handoff still returned HTTP
503, and a saved receipt was rejected after the source changed. That negative
case also logged async context-cleanup errors after the tool limit was reached;
these need investigation before a runtime migration, even though the request
remained closed to unsupported answers. Another 212
selected tests passed on SDK 1.57.0, covering tool scopes, evidence snapshots,
follow-ups, claim checks, model requests, eligibility and unsupported requests.

The serial Lab 3 checks took 77, 126 and 98 seconds respectively. These are one
small trial per configuration, not a speed comparison or reliability estimate.

Harness adds built-in tools and plugins by default. Supplying `tools=` alone
does not remove those defaults. This trial explicitly disabled shell/file/web
tools, delegation, persistence, memory and background work. The workshop needs
only its catalog tools; adding a general-purpose tool set would change the
exercise and its access boundaries.

## Participant coding assistant

The coding trial uses the actual Harness loop with three restricted tools:
read an allowed lab file, replace the contents of an allowed lab marker pair,
and run the real lab checks. It edits an isolated checkout. The checker applies
SQL to the authorized Aurora cluster and restores the participant's original
SQL on exit. Existing participant files are preserved.

The assistant receives a repair contract and the file/marker names, not the
reference repair. The Lab 3 test file is the participant's existing work and
cannot be edited by the assistant. Arbitrary shell commands, extra file writes,
solution actions and access to credentials are unavailable.

| Successful repair attempt | Production HTTP checks | Time including checks |
|---|---:|---:|
| Lab 1: reconnect spelling search | 10 passed | 70 seconds |
| Lab 2: restore rank contributions | 15 passed | 40 seconds |
| Lab 3: register retrieved evidence | 19 passed | 181 seconds |

Lab 3 also passed the three existing participant contract tests. These are the
successful attempts after the setup corrections below, not an all-first-try
success rate. Each started from that lab's deliberate fault.

The trial uncovered a workshop defect: Lab 3's source check compared Python
structure with the reference answer and rejected a correct repair that moved
`setdefault` outside the loop. The source checker now executes the edited
registration function against independent records, repeated calls and two
products in a separate process with a two-second deadline. It accepts equivalent
repairs while rejecting missing registration, duplicate IDs, replaced state and
wrong product mappings. Saved-run checks also include this probe in their source
hash. The regression failed before the fix; weakened product-map checks and an
omitted receipt dependency each failed their permanent tests, followed by
byte-identical restoration. End-to-end validation remains required.

Two initial runs exhausted the tool budget because the read tool's refusal did
not list the permitted source paths. Listing those paths fixed file discovery.
A later edit included the surrounding marker lines; the edit tool now rejects
those before writing. One trial also encountered a Bedrock read timeout. These
are reasons to provide clear scoped tools and real check feedback; a general
coding prompt alone is insufficient.

This trial assesses repairs to the three marked functions. It does not claim
that Harness authored and completed every participant SQL exercise, wrote the
Lab 3 tests, or can replace an interactive coding editor without more work.

## Recommendation for this release

Keep the existing Strands agent and Claude Code participant path as the defaults.
Harness is a viable optional experiment with a selectable model, but the
retrieval trial does not establish a benefit that warrants a dependency upgrade
and new default capabilities. The coding trial requires a purpose-built, scoped
tool interface and clearer failure handling before becoming a workshop path.

The downloadable [Hybrid Agentic Search skill](../skills/mosaic-hybrid-retrieval/SKILL.md)
is independent of that choice. Its package passed Strands' strict skill loader
and the skill-format validator. Loading instructions does not grant tools or
backend access; connect the declared HTTP operations and keep the application's
citation validator, or use Mosaic's complete agent-answer endpoint as described
in the skill. Avoid nesting two agents that both try to own the same tool loop.

Configuration and defaults were checked against the official
[Harness configuration reference](https://strandsagents.com/docs/user-guide/harness/reference/configuration/)
and [skill configuration guide](https://strandsagents.com/docs/user-guide/harness/configure/skills/).
