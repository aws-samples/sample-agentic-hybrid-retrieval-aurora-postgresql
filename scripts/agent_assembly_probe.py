"""Bound the lab-status check without loading participant code into the API.

Prints `agent assembly ready`, or `problem: ` and the first part of the Lab 3
contract the participant's `create_agent` misses, as a key the caller words.
"""

from __future__ import annotations

import sys


def problem(result, calls, model, tools, instructions, hooks) -> str | None:
    """The first contract part `create_agent`'s result misses, or None."""
    if len(calls) != 1 or result is not calls[0]:
        return "not_returned"
    if result.get("model") is not model:
        return "model"
    if result.get("tools") != tools:
        return "tools"
    prompt = result.get("system_prompt")
    if not isinstance(prompt, str) or instructions not in prompt:
        return "instructions"
    if result.get("hooks") != hooks:
        return "hooks"
    return None


def main() -> int:
    calls = []

    def constructor(**kwargs):
        calls.append(kwargs)
        return kwargs

    namespace = {"Agent": constructor}
    model, tools, hooks = object(), [object(), object()], [object()]
    instructions = "Use retrieved product records and report missing evidence."
    try:
        exec(  # noqa: S102 — isolated participant function, bounded by the caller
            compile(
                "from __future__ import annotations\n" + sys.stdin.read(),
                "<agent-assembly>",
                "exec",
            ),
            namespace,
        )
        result = namespace["create_agent"](
            model=model, tools=list(tools), instructions=instructions, hooks=list(hooks)
        )
    except NotImplementedError:
        print("problem: not_built")
        return 1
    except (Exception, SystemExit) as error:  # noqa: BLE001 — participant code is isolated and bounded by the caller
        detail = " ".join(str(error).split())[:120]
        print(
            f"problem: raised {type(error).__name__}"
            + (f": {detail}" if detail else "")
        )
        return 1
    missing = problem(result, calls, model, tools, instructions, hooks)
    if missing:
        print(f"problem: {missing}")
        return 1
    print("agent assembly ready")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
