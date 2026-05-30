from __future__ import annotations

import json

import pytest

from griplab_service.vm_manger.griplab_vm import (
    StateError,
    StateStore,
    base_fingerprint,
    main,
    read_project_config,
    resolve_image_alias,
    resolve_network_alias,
    resolved_profile_inputs,
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


def test_base_fingerprint_changes_when_inputs_change(tmp_path) -> None:
    config_dir = tmp_path / "vm_manage"
    config_dir.mkdir()
    (config_dir / "glvm.toml").write_text(
        """
[os_aliases]
ubuntu-lts = "ubuntu:24.04"

[[profiles]]
name = "dev"
image = "ubuntu-lts"
network = "none"
tools = ["python"]
""".strip()
        + "\n",
        encoding="utf-8",
    )
    config = read_project_config(tmp_path)
    profile = config.profiles[0]

    first = resolved_profile_inputs(config, profile, "orbstack")
    second = dict(first)
    second["tools"] = ["python", "uv"]

    assert base_fingerprint(first) != base_fingerprint(second)


def test_image_build_list_delete_roundtrip(tmp_path, capsys) -> None:
    config_dir = tmp_path / "vm_manage"
    config_dir.mkdir()
    (config_dir / "glvm.toml").write_text(
        """
default_provider = "orbstack"

[os_aliases]
ubuntu-lts = "ubuntu:24.04"

[[profiles]]
name = "dev"
image = "ubuntu-lts"
network = "none"
tools = ["python", "uv"]
""".strip()
        + "\n",
        encoding="utf-8",
    )
    state_file = tmp_path / "state.json"

    build_exit = main(
        [
            "--project-root",
            str(tmp_path),
            "--state-file",
            str(state_file),
            "image",
            "build",
            "--profile",
            "dev",
            "--name",
            "dev-base",
        ]
    )
    state_after_build = json.loads(state_file.read_text(encoding="utf-8"))
    list_exit = main(["--state-file", str(state_file), "image", "list"])
    delete_exit = main(["--state-file", str(state_file), "image", "delete", "dev-base"])

    captured = capsys.readouterr()

    assert build_exit == 0
    assert list_exit == 0
    assert delete_exit == 0
    assert "built base dev-base (orbstack)" in captured.out
    assert "dev-base: orbstack profile=dev" in captured.out
    assert "deleted base dev-base" in captured.out
    assert state_after_build["bases"]["dev-base"]["resolved_image"] == "ubuntu:24.04"
