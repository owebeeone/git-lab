import json
from pathlib import Path

from griplab_service.collaborators import (
    CollaboratorRecord,
    configured_presence,
    health_for_presence,
    load_collaborators,
    remove_collaborator,
    upsert_collaborator,
)


def test_collaborator_store_round_trip_and_presence(tmp_path: Path) -> None:
    path = tmp_path / "collaborators.json"
    record = CollaboratorRecord(
        peer_id="weftpi",
        name="Weftpi",
        ssh_address="gianni@example.invalid",
        location="~/gitlab/grip-dev",
    )

    assert upsert_collaborator(path, record) == [record]
    assert load_collaborators(path) == [record]

    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw[0]["peerId"] == "weftpi"
    assert raw[0]["location"] == "~/gitlab/grip-dev"

    presence = configured_presence(record)
    assert presence["id"] == "weftpi"
    assert presence["status"] == "configured"
    assert presence["online"] is False

    health = health_for_presence(presence)
    assert health["peerId"] == "weftpi"
    assert health["checks"][1]["id"] == "bootstrap"

    assert remove_collaborator(path, "weftpi") == []
    assert load_collaborators(path) == []
