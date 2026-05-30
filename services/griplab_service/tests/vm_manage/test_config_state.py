from __future__ import annotations

import json
import sys

import pytest

from griplab_service.vm_manger.griplab_vm import (
    CommandResult,
    StateError,
    StateStore,
    base_fingerprint,
    main,
    read_project_config,
    resolve_image_alias,
    resolve_network_alias,
    resolved_profile_inputs,
)


class FakeRunner:
    def __init__(self) -> None:
        self.commands: list[list[str]] = []

    def run(self, command: list[str]) -> CommandResult:
        self.commands.append(command)
        return CommandResult(0, "", "")


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
    runner = FakeRunner()

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
        ],
        command_runner=runner,
    )
    state_after_build = json.loads(state_file.read_text(encoding="utf-8"))
    list_exit = main(["--state-file", str(state_file), "image", "list"])
    delete_exit = main(
        ["--state-file", str(state_file), "image", "delete", "dev-base"],
        command_runner=runner,
    )

    captured = capsys.readouterr()

    assert build_exit == 0
    assert list_exit == 0
    assert delete_exit == 0
    assert "built base dev-base (orbstack)" in captured.out
    assert "dev-base: orbstack profile=dev" in captured.out
    assert "deleted base dev-base" in captured.out
    assert state_after_build["bases"]["dev-base"]["resolved_image"] == "ubuntu:24.04"
    assert runner.commands == [
        ["orbctl", "create", "ubuntu:24.04", "glvm-base-dev-base"],
        ["orbctl", "delete", "glvm-base-dev-base"],
    ]


def test_native_host_create_info_list_destroy(tmp_path, capsys) -> None:
    config_dir = tmp_path / "vm_manage"
    config_dir.mkdir()
    (config_dir / "glvm.toml").write_text(
        """
[[profiles]]
name = "pi"
image = "ubuntu-lts"
network = "none"
""".strip()
        + "\n",
        encoding="utf-8",
    )
    state_file = tmp_path / "state.json"

    create_exit = main(
        [
            "--project-root",
            str(tmp_path),
            "--state-file",
            str(state_file),
            "create",
            "--provider",
            "native-host",
            "--profile",
            "pi",
            "--name",
            "rpi",
        ]
    )
    list_exit = main(["--state-file", str(state_file), "list"])
    info_exit = main(["--state-file", str(state_file), "info", "rpi"])
    destroy_exit = main(["--state-file", str(state_file), "destroy", "rpi"])

    captured = capsys.readouterr()
    state = json.loads(state_file.read_text(encoding="utf-8"))

    assert create_exit == 0
    assert list_exit == 0
    assert info_exit == 0
    assert destroy_exit == 0
    assert "created machine rpi (native-host)" in captured.out
    assert "rpi: native-host profile=pi state=registered" in captured.out
    assert '"provider": "native-host"' in captured.out
    assert "destroyed machine rpi" in captured.out
    assert state["machines"] == {}


def test_native_host_exec_runs_command(tmp_path, capfd) -> None:
    config_dir = tmp_path / "vm_manage"
    config_dir.mkdir()
    (config_dir / "glvm.toml").write_text(
        """
[[profiles]]
name = "local"
image = "ubuntu-lts"
network = "none"
""".strip()
        + "\n",
        encoding="utf-8",
    )
    state_file = tmp_path / "state.json"
    main(
        [
            "--project-root",
            str(tmp_path),
            "--state-file",
            str(state_file),
            "create",
            "--provider",
            "native-host",
            "--profile",
            "local",
            "--name",
            "local",
        ]
    )

    exit_code = main(
        [
            "--state-file",
            str(state_file),
            "exec",
            "local",
            "--",
            sys.executable,
            "-c",
            "print('native-ok')",
        ]
    )

    captured = capfd.readouterr()

    assert exit_code == 0
    assert "native-ok" in captured.out


def test_wsl2_attach_exec_and_detach(tmp_path, monkeypatch, capsys) -> None:
    config_dir = tmp_path / "vm_manage"
    config_dir.mkdir()
    (config_dir / "glvm.toml").write_text(
        """
[[profiles]]
name = "win"
image = "ubuntu-lts"
network = "none"
""".strip()
        + "\n",
        encoding="utf-8",
    )
    state_file = tmp_path / "state.json"
    calls: list[list[str]] = []

    class Result:
        returncode = 0

    def fake_run(command, check=False):
        calls.append(command)
        assert check is False
        return Result()

    monkeypatch.setattr("griplab_service.vm_manger.griplab_vm.subprocess.run", fake_run)

    create_exit = main(
        [
            "--project-root",
            str(tmp_path),
            "--state-file",
            str(state_file),
            "create",
            "--provider",
            "wsl2",
            "--profile",
            "win",
            "--name",
            "magenta",
            "--distro",
            "Ubuntu",
        ]
    )
    exec_exit = main(
        [
            "--state-file",
            str(state_file),
            "exec",
            "magenta",
            "--",
            "uname",
            "-a",
        ]
    )
    destroy_exit = main(["--state-file", str(state_file), "destroy", "magenta"])

    captured = capsys.readouterr()
    state = json.loads(state_file.read_text(encoding="utf-8"))

    assert create_exit == 0
    assert exec_exit == 0
    assert destroy_exit == 0
    assert calls == [["wsl", "--distribution", "Ubuntu", "--", "uname", "-a"]]
    assert "attached machine magenta (wsl2:Ubuntu)" in captured.out
    assert "detached machine magenta" in captured.out
    assert state["machines"] == {}


def test_orbstack_create_exec_destroy_from_base(tmp_path, capsys) -> None:
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
tools = ["python"]
""".strip()
        + "\n",
        encoding="utf-8",
    )
    state_file = tmp_path / "state.json"
    runner = FakeRunner()

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
        ],
        command_runner=runner,
    )
    create_exit = main(
        [
            "--project-root",
            str(tmp_path),
            "--state-file",
            str(state_file),
            "create",
            "--profile",
            "dev",
            "--name",
            "dev-one",
            "--base",
            "dev-base",
        ],
        command_runner=runner,
    )
    exec_exit = main(
        [
            "--state-file",
            str(state_file),
            "exec",
            "dev-one",
            "--",
            "uname",
            "-a",
        ],
        command_runner=runner,
    )
    destroy_exit = main(
        ["--state-file", str(state_file), "destroy", "dev-one"],
        command_runner=runner,
    )

    captured = capsys.readouterr()
    state = json.loads(state_file.read_text(encoding="utf-8"))

    assert build_exit == 0
    assert create_exit == 0
    assert exec_exit == 0
    assert destroy_exit == 0
    assert runner.commands == [
        ["orbctl", "create", "ubuntu:24.04", "glvm-base-dev-base"],
        ["orbctl", "clone", "glvm-base-dev-base", "glvm-dev-one"],
        ["orbctl", "run", "--machine", "glvm-dev-one", "uname", "-a"],
        ["orbctl", "delete", "glvm-dev-one"],
    ]
    assert "created machine dev-one (orbstack clone)" in captured.out
    assert "destroyed machine dev-one" in captured.out
    assert state["bases"]["dev-base"]["provider_id"] == "glvm-base-dev-base"
    assert state["machines"] == {}


def test_install_tool_qemu_linux_apt_dry_run(monkeypatch, capsys) -> None:
    monkeypatch.setattr("griplab_service.vm_manger.griplab_vm.platform.system", lambda: "Linux")
    monkeypatch.setattr(
        "griplab_service.vm_manger.griplab_vm.shutil.which",
        lambda command: "/usr/bin/apt-get" if command == "apt-get" else None,
    )

    exit_code = main(["install-tool", "qemu"])

    captured = capsys.readouterr()

    assert exit_code == 0
    assert "install plan: qemu on linux via apt" in captured.out
    assert "$ sudo apt-get update" in captured.out
    assert "qemu-system-aarch64" in captured.out
    assert "dry-run only; pass --execute to run" in captured.out


def test_install_tool_execute_runs_matrix_commands(monkeypatch) -> None:
    monkeypatch.setattr("griplab_service.vm_manger.griplab_vm.platform.system", lambda: "Darwin")
    monkeypatch.setattr(
        "griplab_service.vm_manger.griplab_vm.shutil.which",
        lambda command: "brew" if command == "brew" else None,
    )
    runner = FakeRunner()

    exit_code = main(["install-tool", "lima", "--execute"], command_runner=runner)

    assert exit_code == 0
    assert runner.commands == [["brew", "install", "lima"]]


def test_install_tool_missing_plan_returns_error(monkeypatch) -> None:
    monkeypatch.setattr("griplab_service.vm_manger.griplab_vm.platform.system", lambda: "Linux")
    monkeypatch.setattr("griplab_service.vm_manger.griplab_vm.shutil.which", lambda command: None)

    with pytest.raises(StateError, match="no install plan"):
        main(["install-tool", "qemu"])
