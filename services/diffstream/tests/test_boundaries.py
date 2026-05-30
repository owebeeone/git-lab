from __future__ import annotations

from pathlib import Path


def test_diffstream_has_no_service_runtime_imports() -> None:
    src_root = Path(__file__).parents[1] / "src" / "diffstream"
    forbidden = [
        "griplab_service",
        "aiohttp",
        "watchdog",
        "import git",
        "from git",
        "from grip",
        "import grip",
    ]

    for path in src_root.rglob("*.py"):
        text = path.read_text()
        for token in forbidden:
            assert token not in text, f"{path.relative_to(src_root)} imports {token}"
