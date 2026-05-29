# AGENTS

## Scope

This file defines repository-specific working instructions for `grip-lab`, a
React + TypeScript front-end built on `@owebeeone/grip-react`.

## Agent requests: review vs edit

- When the user asks to review, verify, analyze, assess, report, or check,
  respond with read-only analysis only.
- Do not change files or implement fixes unless the user explicitly asks for
  edits, fixes, implementation, or an update.
- If analysis surfaces a problem, describe it and wait for direction rather
  than patching the tree unprompted.

## Start here

- Read `dev-docs/` for active design notes and working docs.
- This is a Vite + React 19 + TypeScript app. State and data flow are modeled
  with GRIP (grips, taps, contexts) via `@owebeeone/grip-react`.

## Project layout

- `src/runtime.ts` — the shared `GripRegistry` and `Grok` runtime instances.
- `src/grips.ts` — grip (typed value handle) definitions.
- `src/taps.ts` — taps (data producers) and the `registerAllTaps()` helper.
- `src/bootstrap.tsx` — registers taps and mounts the app under `GripProvider`.
- `src/App.tsx` — the root React component.

## Design rules

- Do not introduce enums without explicit project-owner approval. Do not work
  around this with magic strings, magic integers, sentinel strings, or other
  passive tags when the concept has semantics. Semantic concepts should be
  represented by objects/classes that can own behavior, validation, and
  documentation.
- Prefer modeling new reactive state as grips + taps rather than ad-hoc React
  state when the value is shared, derived, or context-dependent.

## Dependency policy

- Do not add any npm or PyPI package version that was published less than one
  week ago. The window right after publish is the highest-risk period for
  supply-chain malware; let versions age before adopting them.
- Before installing, check the candidate version's publish date and pin to a
  specific version that is at least a week old.
- Prefer mature, widely used packages with a stable release history, and keep
  the dependency footprint small. Be mindful of large transitive trees, not just
  the direct dependency.

## Roll-build method

- When the user asks for a phased rollout using the roll-build method, start
  from a clean git tree and tag that point before implementation begins.
- Use the requested start tag name when one is given. If none is given, ask or
  use a clearly scoped phase-start tag name.
- An unqualified `roll-build` means: run all phases for that plan in sequence,
  committing and tagging each completed phase, and continue into the next phase
  without stopping unless the guardrails below require a pause.
- Run the roll-build in the current owning checkout and current branch. Do not
  create git worktrees, sibling checkouts, or parallel rollout branches unless
  the user explicitly asks for them in that request.
- Do not split phases or adjacent roll-build requests into parallel branches.
  If one roll-build has already produced commits, the next roll-build starts on
  top of those commits after they are integrated into the current branch.
- If the current branch is not the intended integration branch, stop and ask
  before creating or switching branches. Do not invent a branch/worktree
  strategy from the tag prefix.
- Implement one phase at a time.
- After a phase is complete, only commit and tag it if:
  - the phase goal is actually met
  - focused verification passes
  - the remaining ambiguities are minor and non-blocking
- If there are no more phases, or if confidence drops because of material
  ambiguity or instability, stop and wait instead of forcing the next phase.
- If work starts cycling on the same persistent bug or bug family, stop, report
  the cycle clearly, and ask for direction.

## When to push back on roll-build

- Push back when the next phase has too many unresolved ambiguities to produce a
  trustworthy checkpoint.
- Push back when the requested phase is too large or too coupled to complete
  safely as one checkpoint.
- Push back when implementation reveals facts that materially break the current
  design or plan assumptions.
- Push back when the resulting checkpoint would be misleadingly partial,
  unstable, or hard to recover from.

## Verification commands

- Dev server: `npm run dev`
- Type-check + build: `npm run build`
- Lint: `npm run lint`
