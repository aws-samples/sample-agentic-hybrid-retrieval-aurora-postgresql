"""The built-in Memory strategies and actor/session boundaries Mosaic uses."""

STRATEGY_TYPES = {
    "semanticMemoryStrategy": "SEMANTIC",
    "userPreferenceMemoryStrategy": "USER_PREFERENCE",
    "summaryMemoryStrategy": "SUMMARIZATION",
    "episodicMemoryStrategy": "EPISODIC",
}


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


def configuration_issues(configuration: dict) -> list[str]:
    """Reject missing, inactive or differently scoped strategies before reporting ready.

    Falsifier: any required strategy is absent, inactive, of the wrong type, or
    has a namespace that differs from the actor/session contract.
    """
    issues = []
    if configuration.get("status") != "ACTIVE":
        issues.append(
            f"Memory status is {configuration.get('status')!r}; wait for ACTIVE or inspect the resource failure."
        )
    strategies = configuration.get("strategies", [])
    for definition in strategy_definitions():
        kind, expected = next(iter(definition.items()))
        matches = [s for s in strategies if s.get("name") == expected["name"]]
        if len(matches) != 1:
            issues.append(
                f"Strategy {expected['name']} has {len(matches)} matches; deploy exactly one Mosaic built-in strategy with this name."
            )
            continue
        actual = matches[0]
        checks = {
            "type": STRATEGY_TYPES[kind],
            "status": "ACTIVE",
            "namespaces": expected["namespaceTemplates"],
            "reflection_namespaces": expected.get("reflectionConfiguration", {}).get(
                "namespaceTemplates", []
            ),
        }
        for field, value in checks.items():
            if actual.get(field, [] if field.endswith("namespaces") else None) != value:
                issues.append(
                    f"Strategy {expected['name']} {field} is {actual.get(field)!r}; restore {value!r} in the Memory resource."
                )
    expected_names = {next(iter(d.values()))["name"] for d in strategy_definitions()}
    unexpected = [
        s.get("name") for s in strategies if s.get("name") not in expected_names
    ]
    if unexpected:
        issues.append(
            f"Unexpected strategies {unexpected!r}; use the dedicated Mosaic Memory resource."
        )
    return issues


def describe_memory(memory: dict) -> dict:
    """Normalize AWS configuration for readiness, provisioning and the UI."""
    return {
        "memory_id": memory["id"],
        "status": memory["status"],
        "event_expiry_days": memory["eventExpiryDuration"],
        "strategies": [
            {
                "id": item["strategyId"],
                "name": item["name"],
                "type": item["type"],
                "status": item["status"],
                "namespaces": item.get("namespaceTemplates")
                or item.get("namespaces", []),
                "reflection_namespaces": (
                    item.get("configuration", {})
                    .get("reflection", {})
                    .get("episodicReflectionConfiguration", {})
                    .get("namespaceTemplates")
                    or item.get("configuration", {})
                    .get("reflection", {})
                    .get("episodicReflectionConfiguration", {})
                    .get("namespaces", [])
                ),
            }
            for item in memory.get("strategies", [])
        ],
    }
