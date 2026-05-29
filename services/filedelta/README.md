# filedelta

Pure Python file snapshot, byte-delta, and text-window projection primitives for
grip-lab.

The package is intentionally excisable. It must not import grip-lab service
code, websocket transports, watchdog, git adapters, or UI modules.

## What It Provides

- Structured byte ops: `insert`, `delete`, `replace`
- Full-file snapshots and deltas
- Text-window snapshots and deltas over complete logical lines
- Hash-validated apply helpers
- Async `FileConnection` / `FileWindowSubscription` runtime driven by external
  file-change notifications
- Python-generated fixtures consumed by the TypeScript reassembler

## Verify

From the repo root:

```sh
PYTHONPATH=services/filedelta/src python3 -m unittest discover -s services/filedelta/tests
npm test --prefix services/filedelta-ts
```

Regenerate cross-language fixtures:

```sh
PYTHONPATH=services/filedelta/src python3 -m filedelta.testing.gen_fixtures
```

## Minimal Use

```python
from filedelta import LineWindow, make_text_window_snapshot, make_text_window_update

data = b"alpha\nbeta\ngamma\n"
snapshot = make_text_window_snapshot(
    "file:demo",
    "win:demo",
    data,
    LineWindow(0, 2),
    file_version="fv000001",
    window_version="wv000001",
)

event = make_text_window_update(
    snapshot,
    b"alpha\nBETA\ngamma\n",
    LineWindow(0, 2),
    seq=1,
    result_file_version="fv000002",
    result_window_version="wv000002",
)
```
