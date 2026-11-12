"""The 100W lookup behind Lab 3's next steps reads a real saved run as completion does.

`follow_up_saved` decides whether `ask_agent.py` and `grade_setup_run.py` ask for the 100W
question again. Offline tests fake the run it reads; this one reads Aurora's newest saved
100W answer, so a renamed column or a changed intent shape fails here instead of reading
as "nothing saved" and asking every participant again.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from service import lab_followup
from service.db import connect
from service.lab_checks import mission_for_lab, same_request


@pytest.mark.aurora
def test_a_saved_100w_answer_counts_only_from_the_code_that_made_it(monkeypatch):
    request = mission_for_lab(3)["changed_requirement"]["query"]
    with connect() as connection:
        rows = connection.execute(
            """SELECT created_at, user_message,
                      extracted_intent ->> 'application_sha256' AS code
               FROM mosaic.agent_turn
               WHERE assistant_message IS NOT NULL
               ORDER BY created_at DESC LIMIT 200"""
        ).fetchall()
        newest = next(
            (r for r in rows if same_request(r["user_message"], request)), None
        )
        if newest is None or not newest["code"]:
            pytest.skip(
                "this database holds no answered 100W run that records its code"
            )
        monkeypatch.setattr("service.agent_deploys.deploy_due", lambda *_a, **_k: False)
        monkeypatch.setattr(
            "service.agent_deploys.lab_3_started_at",
            lambda *_a, **_k: newest["created_at"] - timedelta(seconds=1),
        )
        monkeypatch.setattr(
            "service.lab_validation_receipt.application_digest",
            lambda *_a: newest["code"],
        )
        assert lab_followup.follow_up_saved(connection) is True

        monkeypatch.setattr(
            "service.lab_validation_receipt.application_digest", lambda *_a: "0" * 64
        )
        assert lab_followup.follow_up_saved(connection) is False
