import { createAtomValueTap } from '@owebeeone/grip-react';
import { grok } from '../runtime';
import {
  CURRENT_VIEW, CURRENT_VIEW_TAP,
  THEME, THEME_TAP,
  WORKSPACE_LAYOUT, WORKSPACE_LAYOUT_TAP,
  WORKSPACE_MENU, WORKSPACE_MENU_TAP,
  PEERS, PEERS_TAP,
  SELECTED_PEER_ID, SELECTED_PEER_ID_TAP,
  SELECTED_FILE, SELECTED_FILE_TAP,
  EDITOR_GROUPS, EDITOR_GROUPS_TAP,
  ACTIVE_GROUP, ACTIVE_GROUP_TAP,
  FOCUS_LINE, FOCUS_LINE_TAP,
  DIFF_LEFT, DIFF_LEFT_TAP,
  DIFF_RIGHT, DIFF_RIGHT_TAP,
  CHAT_MESSAGES, CHAT_MESSAGES_TAP,
  CHAT_DRAFT, CHAT_DRAFT_TAP,
  CHAT_PENDING, CHAT_PENDING_TAP,
  CHAT_PANEL_OPEN, CHAT_PANEL_OPEN_TAP,
  CHAT_PANEL_WIDTH, CHAT_PANEL_WIDTH_TAP,
  CHAT_PANEL_DRAGGING, CHAT_PANEL_DRAGGING_TAP,
  CHAT_COMPOSER_H, CHAT_COMPOSER_H_TAP,
  CHAT_COMPOSER_DRAG, CHAT_COMPOSER_DRAG_TAP,
  EXPLORER_COLLAPSED, EXPLORER_COLLAPSED_TAP,
  EXPLORER_OPEN, EXPLORER_OPEN_TAP,
  EXPLORER_WIDTH, EXPLORER_WIDTH_TAP,
  EXPLORER_DRAG, EXPLORER_DRAG_TAP,
  ONBOARDING_FORM, ONBOARDING_FORM_TAP,
  COLLAB_EDIT, COLLAB_EDIT_TAP,
  AVATAR_EDIT, AVATAR_EDIT_TAP,
  SESSIONS, SESSIONS_TAP,
  SELECTED_SESSION, SELECTED_SESSION_TAP,
  SESSION_SEARCH, SESSION_SEARCH_TAP,
  SESSION_FILTERS, SESSION_FILTERS_TAP,
  SESSION_DRAFT, SESSION_DRAFT_TAP,
  SELECTED_TARGET, SELECTED_TARGET_TAP,
  RUN_REPOS, RUN_REPOS_TAP,
  RUN_REPOS_OPEN, RUN_REPOS_OPEN_TAP,
  PURGE_DAYS, PURGE_DAYS_TAP,
  RUN_DIALOG_OPEN, RUN_DIALOG_OPEN_TAP,
} from './grips';
import { registerGraphSimTap } from './graphEngine';
import { registerFileContentTap } from './fileContentTap';
import { registerSessionOutputTap } from './sessionOutputTap';

// All mock state is held in simple settable atom taps. When the backend lands,
// these get replaced by taps that subscribe to the delta protocol; the
// component tree and grips stay the same.
export function registerLabTaps() {
  grok.registerTap(createAtomValueTap(CURRENT_VIEW, { initial: CURRENT_VIEW.defaultValue!, handleGrip: CURRENT_VIEW_TAP }));
  grok.registerTap(createAtomValueTap(THEME, { initial: THEME.defaultValue!, handleGrip: THEME_TAP }));
  grok.registerTap(createAtomValueTap(WORKSPACE_LAYOUT, { initial: WORKSPACE_LAYOUT.defaultValue!, handleGrip: WORKSPACE_LAYOUT_TAP }));
  grok.registerTap(createAtomValueTap(WORKSPACE_MENU, { initial: WORKSPACE_MENU.defaultValue ?? null, handleGrip: WORKSPACE_MENU_TAP }));
  grok.registerTap(createAtomValueTap(PEERS, { initial: PEERS.defaultValue!, handleGrip: PEERS_TAP }));
  grok.registerTap(createAtomValueTap(SELECTED_PEER_ID, { initial: SELECTED_PEER_ID.defaultValue!, handleGrip: SELECTED_PEER_ID_TAP }));
  grok.registerTap(createAtomValueTap(SELECTED_FILE, { initial: SELECTED_FILE.defaultValue ?? null, handleGrip: SELECTED_FILE_TAP }));
  grok.registerTap(createAtomValueTap(EDITOR_GROUPS, { initial: EDITOR_GROUPS.defaultValue!, handleGrip: EDITOR_GROUPS_TAP }));
  grok.registerTap(createAtomValueTap(ACTIVE_GROUP, { initial: ACTIVE_GROUP.defaultValue!, handleGrip: ACTIVE_GROUP_TAP }));
  grok.registerTap(createAtomValueTap(FOCUS_LINE, { initial: FOCUS_LINE.defaultValue ?? null, handleGrip: FOCUS_LINE_TAP }));
  grok.registerTap(createAtomValueTap(DIFF_LEFT, { initial: DIFF_LEFT.defaultValue!, handleGrip: DIFF_LEFT_TAP }));
  grok.registerTap(createAtomValueTap(DIFF_RIGHT, { initial: DIFF_RIGHT.defaultValue!, handleGrip: DIFF_RIGHT_TAP }));
  grok.registerTap(createAtomValueTap(CHAT_MESSAGES, { initial: CHAT_MESSAGES.defaultValue!, handleGrip: CHAT_MESSAGES_TAP }));
  grok.registerTap(createAtomValueTap(CHAT_DRAFT, { initial: CHAT_DRAFT.defaultValue!, handleGrip: CHAT_DRAFT_TAP }));
  grok.registerTap(createAtomValueTap(CHAT_PENDING, { initial: CHAT_PENDING.defaultValue!, handleGrip: CHAT_PENDING_TAP }));
  grok.registerTap(createAtomValueTap(CHAT_PANEL_OPEN, { initial: CHAT_PANEL_OPEN.defaultValue!, handleGrip: CHAT_PANEL_OPEN_TAP }));
  grok.registerTap(createAtomValueTap(CHAT_PANEL_WIDTH, { initial: CHAT_PANEL_WIDTH.defaultValue!, handleGrip: CHAT_PANEL_WIDTH_TAP }));
  grok.registerTap(createAtomValueTap(CHAT_PANEL_DRAGGING, { initial: CHAT_PANEL_DRAGGING.defaultValue!, handleGrip: CHAT_PANEL_DRAGGING_TAP }));
  grok.registerTap(createAtomValueTap(CHAT_COMPOSER_H, { initial: CHAT_COMPOSER_H.defaultValue!, handleGrip: CHAT_COMPOSER_H_TAP }));
  grok.registerTap(createAtomValueTap(CHAT_COMPOSER_DRAG, { initial: CHAT_COMPOSER_DRAG.defaultValue ?? null, handleGrip: CHAT_COMPOSER_DRAG_TAP }));
  grok.registerTap(createAtomValueTap(EXPLORER_COLLAPSED, { initial: EXPLORER_COLLAPSED.defaultValue!, handleGrip: EXPLORER_COLLAPSED_TAP }));
  grok.registerTap(createAtomValueTap(EXPLORER_OPEN, { initial: EXPLORER_OPEN.defaultValue!, handleGrip: EXPLORER_OPEN_TAP }));
  grok.registerTap(createAtomValueTap(EXPLORER_WIDTH, { initial: EXPLORER_WIDTH.defaultValue!, handleGrip: EXPLORER_WIDTH_TAP }));
  grok.registerTap(createAtomValueTap(EXPLORER_DRAG, { initial: EXPLORER_DRAG.defaultValue ?? null, handleGrip: EXPLORER_DRAG_TAP }));
  grok.registerTap(createAtomValueTap(ONBOARDING_FORM, { initial: ONBOARDING_FORM.defaultValue!, handleGrip: ONBOARDING_FORM_TAP }));
  grok.registerTap(createAtomValueTap(COLLAB_EDIT, { initial: COLLAB_EDIT.defaultValue ?? null, handleGrip: COLLAB_EDIT_TAP }));
  grok.registerTap(createAtomValueTap(AVATAR_EDIT, { initial: AVATAR_EDIT.defaultValue ?? null, handleGrip: AVATAR_EDIT_TAP }));
  grok.registerTap(createAtomValueTap(SESSIONS, { initial: SESSIONS.defaultValue!, handleGrip: SESSIONS_TAP }));
  grok.registerTap(createAtomValueTap(SELECTED_SESSION, { initial: SELECTED_SESSION.defaultValue ?? null, handleGrip: SELECTED_SESSION_TAP }));
  grok.registerTap(createAtomValueTap(SESSION_SEARCH, { initial: SESSION_SEARCH.defaultValue!, handleGrip: SESSION_SEARCH_TAP }));
  grok.registerTap(createAtomValueTap(SESSION_FILTERS, { initial: SESSION_FILTERS.defaultValue!, handleGrip: SESSION_FILTERS_TAP }));
  grok.registerTap(createAtomValueTap(SESSION_DRAFT, { initial: SESSION_DRAFT.defaultValue!, handleGrip: SESSION_DRAFT_TAP }));
  grok.registerTap(createAtomValueTap(SELECTED_TARGET, { initial: SELECTED_TARGET.defaultValue ?? null, handleGrip: SELECTED_TARGET_TAP }));
  grok.registerTap(createAtomValueTap(RUN_REPOS, { initial: RUN_REPOS.defaultValue!, handleGrip: RUN_REPOS_TAP }));
  grok.registerTap(createAtomValueTap(RUN_REPOS_OPEN, { initial: RUN_REPOS_OPEN.defaultValue!, handleGrip: RUN_REPOS_OPEN_TAP }));
  grok.registerTap(createAtomValueTap(PURGE_DAYS, { initial: PURGE_DAYS.defaultValue!, handleGrip: PURGE_DAYS_TAP }));
  grok.registerTap(createAtomValueTap(RUN_DIALOG_OPEN, { initial: RUN_DIALOG_OPEN.defaultValue!, handleGrip: RUN_DIALOG_OPEN_TAP }));
  registerGraphSimTap();
  registerFileContentTap();
  registerSessionOutputTap();
}
