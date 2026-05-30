from __future__ import annotations

import json

import pytest

from griplab_service.vm_manger.griplab_vm import (
    StateError,
    StateStore,
    read_project_config,
    resolve_image_alias,
    resolve_network_alias,
)


def test_read_project_config_resolves_profiles_and_aliases(tmp_path) -> None:
    config_dir = tmp_path / "vm_manage"
    config_dir.mkdir()
    (config_dir / "glvm.toml").write_text(
        """
default_profile = "dev"
default_provider = "auto"

[os_aliases]
ubuntu-lts = "ubuntu:24.04"

[network_aliases]
none = { visibility = "localhost", outbound = false, inbound = false }

[[profiles]]
name = "dev"
image = "ubuntu-lts"
network = "none"
tools = ["python", "uv"]
""".strip()
        + "\n",
        encoding="utf-8",
    )

    config = read_project_config(tmp_path)

    assert config.default_profile == "dev"
    assert config.profiles == [
        {
            "name": "dev",
            "image": "ubuntu-lts",
            "network": "none",
            "tools": ["python", "uv"],
        }
    ]
    assert resolve_image_alias(config, "ubuntu-lts") == "ubuntu:24.04"
    assert resolve_network_alias(config, "none") == {
        "visibility": "localhost",
        "outbound": False,
        "inbound": False,
    }


def test_state_store_writes_atomically_and_reads_json(tmp_path) -> None:
    store = StateStore(tmp_path / "state.json")
    data = {"schema_version": 1, "bases": {"dev-base": {}}, "machines": {}}

    store.write(data)

    assert store.read() == data
    assert json.loads((tmp_path / "state.json").read_text(encoding="utf-8")) == data


def test_state_store_fails_closed_on_corrupt_json(tmp_path) -> None:
    state_path = tmp_path / "state.json"
    state_path.write_text("{not-json", encoding="utf-8")
    store = StateStore(state_path)

    with pytest.raises(StateError, match="state file is corrupt"):
        store.read()


def test_state_store_rejects_existing_lock(tmp_path) -> None:
    state_path = tmp_path / "state.json"
    lock_path = tmp_path / "state.json.lock"
    lock_path.write_text("", encoding="utf-8")
    store = StateStore(state_path)

    with pytest.raises(StateError, match="state is locked"):
        store.write({"schema_version": 1})
