# @grip-lab/filedelta

TypeScript runtime validators, byte-op apply helpers, and text-window
reassembler for `services/filedelta` fixture streams.

## Verify

From this package:

```sh
npm test
```

From the repo root:

```sh
npm test --prefix services/filedelta-ts
```

The test command compiles TypeScript and runs:

- hand-written parser/reassembler tests
- Python-generated fixture streams from `services/filedelta/fixtures/window_cases`

The browser client should consume these modules rather than reimplementing
window apply semantics.
