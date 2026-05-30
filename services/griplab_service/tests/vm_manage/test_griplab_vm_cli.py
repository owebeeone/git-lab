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
    assert "orbstack:" in captured.out
    assert "lima:" in captured.out
    assert "wsl2:" in captured.out
    assert "native-host:" in captured.out


def test_declared_provider_order_matches_plan() -> None:
    provider_names = tuple(provider.name for provider in griplab_vm.provider_definitions())

    assert provider_names == griplab_vm.PROVIDER_NAMES
    assert provider_names[:4] == (
        "orbstack",
        "lima",
        "wsl2",
        "native-host",
    )


def test_provider_capabilities_identify_non_vm_providers() -> None:
    providers = {provider.name: provider for provider in griplab_vm.provider_definitions()}

    assert providers["wsl2"].capabilities.true_vm_boundary is False
    assert providers["native-host"].capabilities.true_vm_boundary is False
    assert providers["lima"].capabilities.true_vm_boundary is True


def test_provider_detection_reports_missing_command(monkeypatch) -> None:
    monkeypatch.setattr(griplab_vm.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(griplab_vm.shutil, "which", lambda command: None)

    statuses = {status.name: status for status in griplab_vm.provider_statuses()}

    assert statuses["orbstack"].available is False
    assert statuses["orbstack"].detail == "missing command: orb"
    assert statuses["native-host"].available is True


def test_checkpoint_has_no_sudo_shellouts() -> None:
    source = griplab_vm.__loader__.get_source(griplab_vm.__name__)

    assert source is not None
    assert "sudo" not in source
