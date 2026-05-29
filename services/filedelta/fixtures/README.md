# Filedelta Fixtures

Regenerate cross-language window fixtures from the repo root:

```sh
PYTHONPATH=services/filedelta/src python3 -m filedelta.testing.gen_fixtures
```

TypeScript consumes `window_cases/*/events.jsonl` and verifies the final window
bytes against `expected-window.bin`.
