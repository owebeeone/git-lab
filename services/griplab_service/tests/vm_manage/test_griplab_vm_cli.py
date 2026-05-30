from __future__ import annotations

from griplab_service.vm_manger import griplab_vm


def test_help_lists_core_commands(capsys) -> None:
    exit_code = griplab_vm.main(["--help"])

    captured = capsys.readouterr()

    assert exit_code == 0
    assert "doctor" in captured.out
    assert "providers" in captured.out
    assert "image" in captured.out
    assert "agent" in captured.out


def test_providers_lists_declared_adapters(capsys) -> None:
    exit_code = griplab_vm.main(["providers"])

    captured = capsys.readouterr()

    assert exit_code == 0
    assert "orbstack: unavailable" in captured.out
    assert "lima: unavailable" in captured.out
    assert "wsl2: unavailable" in captured.out
    assert "native-host: unavailable" in captured.out


def test_declared_provider_order_matches_plan() -> None:
    assert griplab_vm.PROVIDER_NAMES[:4] == (
        "orbstack",
        "lima",
        "wsl2",
        "native-host",
    )


def test_checkpoint_has_no_sudo_shellouts() -> None:
    source = griplab_vm.__loader__.get_source(griplab_vm.__name__)

    assert source is not None
    assert "sudo" not in source
