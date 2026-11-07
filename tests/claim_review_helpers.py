"""A positive protocol response for tests of synthesis's other boundaries.

This double does not judge meaning. test_claim_review supplies negative decisions
and malformed responses independently; live probes assess the model's judgments.
"""

import json
import re


def supported_review(request):
    tool = (
        request.get("toolConfig", {})
        .get("tools", [{}])[0]
        .get("toolSpec", {})
        .get("name")
    )
    if tool != "record_claim_support":
        return None
    payload = json.loads(request["messages"][0]["content"][0]["text"])
    records = {e["number"]: e for e in payload["evidence"]}
    decisions = []
    for part in payload["passages"]:
        cited = sorted({int(n) for n in re.findall(r"\[(\d+)\]", part["text"])})
        decisions.append(
            {
                "id": part["id"],
                "verdict": "supported" if cited else "non_claim",
                "support": [
                    {"number": n, "quote": records[n]["text"][:1500]} for n in cited
                ],
                "reason": "Scripted protocol witness for a different boundary.",
            }
        )
    return {
        "stopReason": "tool_use",
        "output": {
            "message": {
                "content": [
                    {
                        "toolUse": {
                            "name": tool,
                            "input": {"passages": decisions},
                        }
                    }
                ]
            }
        },
        "usage": {},
    }
