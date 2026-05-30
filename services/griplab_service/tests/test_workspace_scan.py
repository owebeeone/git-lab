from pathlib import Path
import subprocess

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


def test_collect_workspace_status_reports_ignored_files(tmp_path: Path) -> None:
    built = RepoDefinition(react_repo("app")).build(tmp_path / "workspace")
    repo = built.workspace_root / "app"
    (repo / ".gitignore").write_text("scratch.txt\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", ".gitignore"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-q", "-m", "ignore scratch"], check=True)
    (repo / "scratch.txt").write_text("ignored\n", encoding="utf-8")

    statuses = collect_workspace_status(built.workspace_root)

    app = next(status for status in statuses if status.path == "app")
    assert app.dirty is False
    assert {"path": "scratch.txt", "change": "ignored"} in [
        {"path": file.path, "change": file.change}
        for file in app.changed_files
    ]


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


def test_dependency_graph_reads_package_json_dependencies(tmp_path: Path) -> None:
    built = RepoDefinition(
        react_repo("core"),
        react_repo("react").dep("core"),
        react_repo("demo").dep("react"),
    ).build(tmp_path / "workspace")
    remove_explicit_deps(built.workspace_root)

    graph = get_dependency_graph(built.workspace_root)

    assert {(edge.source, edge.target) for edge in graph.edges} == {
        ("react", "core"),
        ("demo", "react"),
    }
    assert graph.errors == {}


def test_dependency_graph_reads_pyproject_dependencies(tmp_path: Path) -> None:
    built = RepoDefinition(
        pyproj_repo("py-core"),
        pyproj_repo("py-app").dep("py-core"),
    ).build(tmp_path / "workspace")
    remove_explicit_deps(built.workspace_root)

    graph = get_dependency_graph(built.workspace_root)

    assert {(edge.source, edge.target) for edge in graph.edges} == {("py-app", "py-core")}
    assert graph.errors == {}


def test_dependency_graph_reports_unknown_dependency(tmp_path: Path) -> None:
    built = RepoDefinition(
        react_repo("app").dep("missing"),
    ).build(tmp_path / "workspace")

    graph = get_dependency_graph(built.workspace_root)

    assert graph.edges == []
    assert graph.errors == {"app": "unknown dependency: missing"}


def remove_explicit_deps(workspace_root: Path) -> None:
    for deps_file in workspace_root.glob("*/.grip-lab/deps.json"):
        deps_file.unlink()
