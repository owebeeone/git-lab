# grip-lab

A React + TypeScript front-end for a new tool, built on GRIP
(`@owebeeone/grip-react`). This is a minimal "hello world" starting point we can
build on collaboratively.

## Getting Started

### Prerequisites

- Node.js 20+
- npm

### Installation

```bash
npm install
```

This installs `@owebeeone/grip-react` from npm (version 0.2.0 or higher).

### Development

```bash
npm run dev
```

The app will be available at `http://localhost:5173` (or the next free port).

### Build

```bash
npm run build
```

### Lint

```bash
npm run lint
```

## Project structure

- `src/runtime.ts` — shared `GripRegistry` and `Grok` runtime.
- `src/grips.ts` — grip (typed value handle) definitions.
- `src/taps.ts` — taps (data producers) and `registerAllTaps()`.
- `src/bootstrap.tsx` — registers taps and mounts the app under `GripProvider`.
- `src/App.tsx` — root component (a greeting + a counter wired to a grip tap).
- `dev-docs/` — collaboration space for design notes.

## Notes

- `scratch/` is git-ignored; use it to dump things you don't want in the repo.
