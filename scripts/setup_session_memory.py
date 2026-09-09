"""Create or update Mosaic's AgentCore Memory with four built-in strategies."""

import argparse
import json
import time

import boto3
from botocore.config import Config


def strategy_definitions() -> list[dict]:
    """Keep every namespace inside a single browser actor's memory."""
    base = "/mosaic/{actorId}/strategies/{memoryStrategyId}/"
    return [
        {
            "semanticMemoryStrategy": {
                "name": "WorkspaceFacts",
                "namespaceTemplates": [base],
            }
        },
        {
            "userPreferenceMemoryStrategy": {
                "name": "WorkspacePreferences",
                "namespaceTemplates": [base],
            }
        },
        {
            "summaryMemoryStrategy": {
                "name": "WorkspaceSummaries",
                "namespaceTemplates": [base + "sessions/{sessionId}/"],
            }
        },
        {
            "episodicMemoryStrategy": {
                "name": "WorkspaceEpisodes",
                "namespaceTemplates": [base + "sessions/{sessionId}/"],
                "reflectionConfiguration": {"namespaceTemplates": [base]},
            }
        },
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--region", default="us-east-1")
    parser.add_argument("--name", default="MosaicWorkspaceMemory")
    parser.add_argument(
        "--create", action="store_true", help="Create the resource if absent"
    )
    parser.add_argument(
        "--configure-strategies",
        action="store_true",
        help="Add missing Mosaic built-in strategies to the existing resource",
    )
    args = parser.parse_args()
    client = boto3.client(
        "bedrock-agentcore-control",
        region_name=args.region,
        config=Config(
            connect_timeout=5,
            read_timeout=20,
            retries={"total_max_attempts": 3, "mode": "standard"},
        ),
    )
    matches = [
        item
        for page in client.get_paginator("list_memories").paginate()
        for item in page.get("memories", [])
        if item["id"].startswith(args.name + "-")
    ]
    if len(matches) > 1:
        raise RuntimeError("More than one matching memory exists; use a unique --name.")
    if matches:
        memory_id = matches[0]["id"]
        memory = client.get_memory(memoryId=memory_id)["memory"]
        existing = {item["name"] for item in memory.get("strategies", [])}
        missing = [
            item
            for item in strategy_definitions()
            if next(iter(item.values()))["name"] not in existing
        ]
        if args.configure_strategies and missing:
            client.update_memory(
                memoryId=memory_id,
                memoryStrategies={"addMemoryStrategies": missing},
                description="Mosaic conversation events, facts, preferences, session summaries and episodes.",
            )
    elif args.create:
        memory_id = client.create_memory(
            name=args.name,
            description="Mosaic conversation events, facts, preferences, session summaries and episodes.",
            eventExpiryDuration=30,
            memoryStrategies=strategy_definitions(),
            tags={"Project": "Mosaic", "Purpose": "SessionMemory"},
        )["memory"]["id"]
    else:
        raise RuntimeError(
            "No matching memory exists. Pass --create to provision Mosaic's dedicated resource."
        )
    deadline = time.monotonic() + 240
    while time.monotonic() < deadline:
        memory = client.get_memory(memoryId=memory_id)["memory"]
        strategies = memory.get("strategies", [])
        if memory["status"] == "ACTIVE" and all(
            s["status"] == "ACTIVE" for s in strategies
        ):
            print(
                json.dumps(
                    {
                        "memory_id": memory_id,
                        "region": args.region,
                        "status": "ACTIVE",
                        "strategies": [
                            {k: s[k] for k in ("strategyId", "type", "status")}
                            for s in strategies
                        ],
                    }
                )
            )
            return
        if memory["status"] not in {"CREATING", "UPDATING", "ACTIVE"} or any(
            s["status"] == "FAILED" for s in strategies
        ):
            raise RuntimeError(
                "Memory or a strategy failed; inspect its AWS status before retrying."
            )
        time.sleep(2)
    raise RuntimeError(
        f"Memory {memory_id} is still starting. Rerun to check it; no duplicate resource is created."
    )


if __name__ == "__main__":
    main()
