from pathlib import Path

from fixtures.repo_env import RepoDefinition, pyproj_repo, react_repo
from griplab_service.local_client.deps import get_dependency_graph
from griplab_service.local_client.workspace import collect_workspace_status


def test_collect_workspace_status_for_classic_repos(tmp_path: Path) -> None:
    built = RepoDefinition(
        react_repo("core"),
        react_repo("react").dep("core").dirty("src/index.ts", "export const dirty = true;\n"),
        pyproj_repo("py"),
    ).build(tmp_path / "workspace")

    statuses = collect_workspace_status(built.workspace_root)

    by_path = {status.path: status for status in statuses}
    assert set(by_path) == {"core", "react", "py"}
    assert by_path["core"].dirty is False
    assert by_path["react"].dirty is True
    assert by_path["react"].changed_files[0].path == "src/index.ts"
    assert by_path["react"].changed_files[0].change == "modified"


def test_dependency_graph_reads_repo_definitions(tmp_path: Path) -> None:
    built = RepoDefinition(
        react_repo("core"),
        react_repo("react").dep("core"),
        react_repo("demo").dep("react"),
        pyproj_repo("py"),
    ).build(tmp_path / "workspace")

    graph = get_dependency_graph(built.workspace_root)

    assert graph.repos == ["core", "demo", "py", "react"]
    assert {(edge.source, edge.target) for edge in graph.edges} == {
        ("react", "core"),
        ("demo", "react"),
    }
    assert graph.errors == {}


def test_dependency_graph_reports_unknown_dependency(tmp_path: Path) -> None:
    built = RepoDefinition(
        react_repo("app").dep("missing"),
    ).build(tmp_path / "workspace")

    graph = get_dependency_graph(built.workspace_root)

    assert graph.edges == []
    assert graph.errors == {"app": "unknown dependency: missing"}
