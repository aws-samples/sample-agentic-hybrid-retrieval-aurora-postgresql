"""Bound the lab-status check without loading participant code into the API."""

from __future__ import annotations

import sys


def main() -> int:
    calls = []

    def constructor(**kwargs):
        calls.append(kwargs)
        return kwargs

    namespace = {"Agent": constructor}
    model, first, second, hook = object(), object(), object(), object()
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
            model=model, tools=[first, second], instructions=instructions, hooks=[hook]
        )
        valid = len(calls) == 1 and result is calls[0]
        valid = (
            valid
            and result.get("model") is model
            and result.get("tools") == [first, second]
        )
        valid = (
            valid
            and instructions in result.get("system_prompt", "")
            and result.get("hooks") == [hook]
        )
        if valid:
            print("agent assembly ready")
            return 0
    except (Exception, SystemExit):  # noqa: BLE001 — participant code is isolated and bounded by the caller
        return 1
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
