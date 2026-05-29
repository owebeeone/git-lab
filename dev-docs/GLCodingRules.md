# grip-lab coding rules

Repository-specific coding rules for `grip-lab`. See also `AGENTS.md`.

## State management: no React local state

- **Do not use `useState` or `useEffect`** (nor `useRef`/`useReducer`/
  `useMemo`/`useCallback`/`useLayoutEffect`) for application or UI state. All
  state lives in **grips** (atom taps) so it is shared, inspectable, and
  reproducible via state links.
- Patterns to use instead:
  - **UI state** (selections, toggles, widths, open/collapsed, form fields,
    drag-in-progress): a grip + atom tap. Read with `useGrip`, write with the
    tap handle's `set`/`update`.
  - **DOM side effects** (scroll-into-view): a **ref callback**
    (`ref={el => el?.scrollIntoView(...)}`), keyed so it re-mounts when the
    target changes — never `useEffect`.
  - **Drag with global movement** (panel/composer resize): render a full-window
    `.drag-overlay` that captures `onMouseMove`/`onMouseUp` as React events while
    a `*Dragging` grip is set — never `window.addEventListener` in an effect.
  - **Animation / timers** (the workspace graph physics): a **tap** that owns
    the loop and publishes to a grip (see `graphEngine.ts` + `GraphSimTap`,
    modeled on grip-react's `TickTap`). The component stays pure.
- This is enforced: `npm run lint` bans `useState`/`useEffect`, and
  `npm test` (`scripts/no-react-state.test.mjs`) scans `src/` and fails the
  build if either appears.

## Workspace graph = dependency hierarchy

- The workspace graph shows the **dependency hierarchy** between repos, not the
  filesystem layout. Edges mean "source depends on target".
- Dependencies are **discovered by an infrequent, cached scan** (cf.
  `submodule_info_server.py`, which reads `.gitmodules` + a relationship table to
  derive `depends_on`/`used_by`). Discovery must **not** run on every render or
  status poll — compute once, store, and reuse. In the mock the stored result is
  `DEPENDENCIES` in `fakeData.ts`.

## General

- Prefer modeling new reactive state as grips + taps (see `AGENTS.md`).
- Keep the dependency footprint small and honor the dependency-age policy.
