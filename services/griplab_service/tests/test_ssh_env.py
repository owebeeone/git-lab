from pathlib import Path
import socket

import pytest

from fixtures.repo_env import CLASSIC, RepoDefinition, pyproj_repo, react_repo
from fixtures.ssh_env import SshTestEnvironment, SshTestPeer, find_ssh_tooling, shell_quote


pytestmark = pytest.mark.skipif(
    find_ssh_tooling() is None,
    reason="sshd, ssh, ssh-keygen, and git are required for SSH integration tests",
)


def test_private_sshd_runs_git_command(
    ssh_test_env: tuple[SshTestEnvironment, SshTestPeer],
) -> None:
    env, peer = ssh_test_env
    result = env.run_ssh(f"git -C {shell_quote(peer.root_repo)} rev-parse --show-toplevel")

    assert result.returncode == 0
    assert result.stdout.strip() == str(peer.root_repo)
    assert peer.root_repo == peer.repos["test-grip-core"]


def test_private_sshd_rejects_wrong_key(
    tmp_path: Path,
    ssh_test_env: tuple[SshTestEnvironment, SshTestPeer],
) -> None:
    env, _peer = ssh_test_env
    wrong_key = tmp_path / "wrong_ed25519"
    env._keygen(wrong_key)
    result = env.run_ssh("true", identity_file=wrong_key)

    assert result.returncode != 0


def test_private_sshd_requires_pinned_known_host(
    tmp_path: Path,
    ssh_test_env: tuple[SshTestEnvironment, SshTestPeer],
) -> None:
    env, _peer = ssh_test_env
    empty_known_hosts = tmp_path / "empty_known_hosts"
    empty_known_hosts.write_text("", encoding="utf-8")
    result = env.run_ssh("true", known_hosts_file=empty_known_hosts)

    assert result.returncode != 0


def test_private_sshd_reports_dirty_git_status(
    ssh_test_env: tuple[SshTestEnvironment, SshTestPeer],
) -> None:
    env, peer = ssh_test_env
    (peer.root_repo / "README.md").write_text("changed\n", encoding="utf-8")
    result = env.run_ssh(f"git -C {shell_quote(peer.root_repo)} status --porcelain=v1")

    assert result.returncode == 0
    assert "M README.md" in result.stdout


def test_repo_definition_builds_project_manifests(tmp_path: Path) -> None:
    definition = RepoDefinition(
        react_repo("ui-core"),
        react_repo("ui-app").dep("ui-core").dirty("src/index.ts", "export const changed = true;\n"),
        pyproj_repo("py-tool").untracked("tests/test_smoke.py", "def test_smoke():\n    assert True\n"),
    )

    built = definition.build(tmp_path / "workspace")

    assert built.root_repo == built.repos["ui-core"]
    assert (built.repos["ui-app"] / "package.json").read_text(encoding="utf-8")
    assert "file:../ui-core" in (built.repos["ui-app"] / "package.json").read_text(encoding="utf-8")
    assert (built.repos["py-tool"] / "pyproject.toml").exists()
    assert (built.repos["ui-app"] / ".grip-lab" / "deps.json").exists()


def test_classic_definition_has_expected_graph_shape(tmp_path: Path) -> None:
    built = CLASSIC.build(tmp_path / "workspace")

    assert set(built.repos) == {
        "test-grip-core",
        "test-grip-react",
        "test-grip-react-demo",
        "test-grip-py",
    }
    assert "test-grip-core" in (built.repos["test-grip-react"] / ".grip-lab" / "deps.json").read_text(encoding="utf-8")


def test_private_sshd_teardown_closes_port(tmp_path: Path) -> None:
    env = SshTestEnvironment(tmp_path)
    with env as peer:
        port = peer.port

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        assert sock.connect_ex(("127.0.0.1", port)) != 0
