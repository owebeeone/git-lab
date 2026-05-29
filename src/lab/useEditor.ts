import { useGrip } from '@owebeeone/grip-react';
import {
  EDITOR_GROUPS, EDITOR_GROUPS_TAP,
  ACTIVE_GROUP, ACTIVE_GROUP_TAP,
  SELECTED_FILE_TAP, CURRENT_VIEW_TAP,
} from './grips';
import type { EditorGroup } from './types';

// Shared editor-group controller for the split Files view. Everything lives in
// grips (no React state); any component can open a file into the focused column.
export function useEditor() {
  const groups = useGrip(EDITOR_GROUPS) ?? [];
  const groupsTap = useGrip(EDITOR_GROUPS_TAP);
  const activeGroupRaw = useGrip(ACTIVE_GROUP) ?? 'g0';
  const activeGroupTap = useGrip(ACTIVE_GROUP_TAP);
  const selTap = useGrip(SELECTED_FILE_TAP);
  const viewTap = useGrip(CURRENT_VIEW_TAP);

  const focusedId = groups.some((g) => g.id === activeGroupRaw) ? activeGroupRaw : (groups[0]?.id ?? 'g0');

  const setGroups = (gs: EditorGroup[]) => groupsTap?.set(gs);

  // Open a file as a tab in the focused column and switch to the Files view.
  const openInFiles = (key: string) => {
    let found = false;
    const gs = groups.map((g) => {
      if (g.id !== focusedId) return g;
      found = true;
      return { ...g, open: g.open.includes(key) ? g.open : [...g.open, key], active: key };
    });
    if (!found) gs.push({ id: focusedId, open: [key], active: key });
    setGroups(gs);
    activeGroupTap?.set(focusedId);
    selTap?.set(key);
    viewTap?.set('file');
  };

  return { groups, setGroups, activeGroup: focusedId, activeGroupTap, selTap, openInFiles };
}
