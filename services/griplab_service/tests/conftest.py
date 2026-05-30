from collections.abc import Iterator

import pytest

from fixtures.ssh_env import SshTestEnvironment, SshTestPeer, find_ssh_tooling


@pytest.fixture
def ssh_test_env(tmp_path) -> Iterator[tuple[SshTestEnvironment, SshTestPeer]]:
    tooling = find_ssh_tooling()
    if tooling is None:
        pytest.skip("sshd, ssh, ssh-keygen, and git are required for SSH integration tests")
    env = SshTestEnvironment(tmp_path, tooling=tooling)
    with env as peer:
        yield env, peer
