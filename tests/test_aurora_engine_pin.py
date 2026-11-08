"""The Aurora engine pin is exact, every copy of it agrees, and the vocabulary cache matches it.

The vocabulary cache records the `server_version_num` it was exported on, and its restore refuses
any other server. A template pin that moves without a re-export therefore stops every fresh
bootstrap at the restore step, long after a green offline run; these checks fail first.
"""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "deploy/cloudformation/hybrid-retrieval-database.yml"
VOCABULARY_CONTRACT = ROOT / "db/config/corpus-vocabulary-cache.json"


class CloudFormationLoader(yaml.SafeLoader):
    """Reads CloudFormation's short tags (!Ref, !GetAtt, ...) as their long-form mappings."""


def short_tag(loader, suffix, node):
    name = "Ref" if suffix == "Ref" else f"Fn::{suffix}"
    if isinstance(node, yaml.ScalarNode):
        value = loader.construct_scalar(node)
    elif isinstance(node, yaml.SequenceNode):
        value = loader.construct_sequence(node, deep=True)
    else:
        value = loader.construct_mapping(node, deep=True)
    return {name: value}


CloudFormationLoader.add_multi_constructor("!", short_tag)


def database_template() -> dict:
    return yaml.load(TEMPLATE.read_text(), Loader=CloudFormationLoader)


def vocabulary_contract() -> dict:
    return json.loads(VOCABULARY_CONTRACT.read_text())


def properties_of(template: dict, kind: str) -> list[dict]:
    return [
        resource.get("Properties") or {}
        for resource in template.get("Resources", {}).values()
        if resource.get("Type") == kind
    ]


def engine_pin_problems(template: dict, contract: dict) -> list[str]:
    """Name each way the template's engine pin is inexact, disagrees or drifts from the cache.

    Falsifiers: a major-only or missing `EngineVersion`, an output, description or parameter
    group family naming another version, a writer free to take minor upgrades, and a
    vocabulary cache exported on a different server version.
    """
    clusters = properties_of(template, "AWS::RDS::DBCluster")
    if len(clusters) != 1:
        return [
            (
                f"Engine pin rule: found {len(clusters)} AWS::RDS::DBCluster resources; "
                "fix: keep exactly one cluster in the database template"
            )
        ]
    version = str(clusters[0].get("EngineVersion", ""))
    if not re.fullmatch(r"\d+\.\d+", version):
        return [
            (
                f"Engine pin rule: found EngineVersion {version!r}; fix: pin the full "
                "engine version (major and minor), such as '18.6'"
            )
        ]
    major, minor = (int(part) for part in version.split("."))
    problems = []
    output = template.get("Outputs", {}).get("DBEngineVersion", {}).get("Value")
    if str(output) != version:
        problems.append(
            f"Engine pin rule: the DBEngineVersion output reads {output!r}; "
            f"fix: set it to '{version}'"
        )
    description = template.get("Description", "")
    if f"Aurora PostgreSQL {version} cluster" not in description:
        problems.append(
            f"Engine pin rule: the template description reads {description!r}; "
            f"fix: name 'Aurora PostgreSQL {version} cluster'"
        )
    families = [
        properties.get("Family")
        for kind in ("AWS::RDS::DBClusterParameterGroup", "AWS::RDS::DBParameterGroup")
        for properties in properties_of(template, kind)
    ]
    if not families or any(
        family != f"aurora-postgresql{major}" for family in families
    ):
        problems.append(
            f"Engine pin rule: found parameter group families {families}; "
            f"fix: use aurora-postgresql{major} for every parameter group"
        )
    instances = properties_of(template, "AWS::RDS::DBInstance")
    upgrades = [properties.get("AutoMinorVersionUpgrade") for properties in instances]
    if not instances or any(upgrade is not False for upgrade in upgrades):
        problems.append(
            f"Engine pin rule: found AutoMinorVersionUpgrade {upgrades}; fix: set it to "
            "false on every instance so a maintenance window cannot change the engine"
        )
    wanted = str(major * 10000 + minor)
    exported = contract.get("environment", {}).get("server_version_num")
    if exported != wanted:
        problems.append(
            f"Engine pin rule: the vocabulary cache was exported on server_version_num "
            f"{exported!r}, but the template pins {version} ({wanted}); fix: export the "
            "cache on an Aurora cluster running that engine version (ARTIFACTS.md)"
        )
    return problems


def test_the_engine_pin_is_exact_consistent_and_matches_the_vocabulary_cache():
    assert engine_pin_problems(database_template(), vocabulary_contract()) == []


def mutated(edit) -> list[str]:
    """Apply one violation to a consistent copy, so each case is judged on that edit alone."""
    template, contract = database_template(), copy.deepcopy(vocabulary_contract())
    major, minor = map(
        int, resource_named(template, "AWS::RDS::DBCluster")["EngineVersion"].split(".")
    )
    contract["environment"]["server_version_num"] = str(major * 10000 + minor)
    assert engine_pin_problems(template, contract) == []
    edit(template, contract)
    return engine_pin_problems(template, contract)


def resource_named(template: dict, kind: str) -> dict:
    (properties,) = properties_of(template, kind)
    return properties


@pytest.mark.parametrize(
    ("edit", "found"),
    [
        (
            lambda t, c: resource_named(t, "AWS::RDS::DBCluster").update(
                EngineVersion="18"
            ),
            "found EngineVersion '18'",
        ),
        (
            lambda t, c: resource_named(t, "AWS::RDS::DBCluster").pop("EngineVersion"),
            "found EngineVersion ''",
        ),
        (
            lambda t, c: t["Outputs"]["DBEngineVersion"].update(Value="17.9"),
            "the DBEngineVersion output reads '17.9'",
        ),
        (
            lambda t, c: t.update(
                Description="Mosaic workshop - Aurora PostgreSQL 17.9 cluster"
            ),
            "the template description reads",
        ),
        (
            lambda t, c: resource_named(t, "AWS::RDS::DBParameterGroup").update(
                Family="aurora-postgresql17"
            ),
            "aurora-postgresql17",
        ),
        (
            lambda t, c: resource_named(t, "AWS::RDS::DBInstance").update(
                AutoMinorVersionUpgrade=True
            ),
            "found AutoMinorVersionUpgrade [True]",
        ),
        (
            lambda t, c: c["environment"].update(server_version_num="170009"),
            "exported on server_version_num '170009'",
        ),
    ],
    ids=[
        "major-only",
        "missing",
        "output",
        "description",
        "family",
        "auto-minor-upgrade",
        "vocabulary-cache",
    ],
)
def test_each_violation_names_the_rule_the_value_and_the_fix(edit, found):
    problems = mutated(edit)
    assert len(problems) == 1, problems
    assert "Engine pin rule:" in problems[0]
    assert found in problems[0]
    assert "fix:" in problems[0]
