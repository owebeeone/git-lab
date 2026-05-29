# State links (`griplab://` URL scheme)

A **link** in grip-lab is a URL that encodes the UI state needed to reproduce a
view. Sharing a link (e.g. dropping it into chat) and later clicking it restores
that exact state. Because the app's state lives in grips, a link is literally a
map of **grip name => value**.

## URL shape

```
griplab://state?<gripName>=<value>&<gripName>=<value>...
```

- Keys are real grip ids (e.g. `Lab.CurrentView`, `Lab.SelectedFile`).
- String-valued grips are stored verbatim (URL-encoded).
- Structured grips (e.g. `Lab.DiffLeft`, a `{ peerId, ref }` endpoint) are
  JSON-encoded.

### Example: a diff line link

Dragging line 7 in the diff viewer produces:

```
griplab://state?Lab.CurrentView=diff&Lab.SelectedFile=yidl%3A%3Asrc%2Fyidl%2Fcli.py&Lab.DiffLeft=%7B%22peerId%22%3A%22me%22%2C%22ref%22%3A%22head%22%7D&Lab.DiffRight=%7B%22peerId%22%3A%22alice%22%2C%22ref%22%3A%22working%22%7D&Lab.FocusLine=7
```

Clicking it: switches to the diff view, selects the file, sets both diff
endpoints, and scrolls to / highlights line 7.

## Grips currently carried by a link

| Key (grip id)        | Meaning                                   |
| -------------------- | ----------------------------------------- |
| `Lab.CurrentView`    | which view to show                        |
| `Lab.SelectedFile`   | `repoPath::path` of the focused file      |
| `Lab.SelectedPeerId` | which collaborator's copy to show         |
| `Lab.DiffLeft`       | diff left endpoint `{ peerId, ref }`      |
| `Lab.DiffRight`      | diff right endpoint `{ peerId, ref }`     |
| `Lab.FocusLine`      | 1-based line to scroll to / highlight     |

## Implementation

- `stateUrl.ts` — `buildStateUrl` / `parseStateUrl` codec.
- `dnd.ts` — `diffLineLink` / `fileLineLink` build state links for a line.
- `ChatView.openLink` — applies a parsed link by setting the corresponding tap
  handles (the single place that "navigates").
- `FOCUS_LINE` is cleared-then-set on apply so re-clicking the same line
  re-triggers the scroll.

## Notes / future

- This is the generalization of all links: file/peer/repo/session links are
  special cases that could eventually be expressed as `griplab://state?...`
  too. They are kept as distinct kinds for now for readable chat chips.
- Only grips listed above are encoded. As shareable state grows (e.g. file
  `ref`, scroll offset, search query), add the grip to the codec table.
- The scheme is transport-agnostic: the same string works as a chat link today
  and could back real `griplab://` deep links / browser query params later.
