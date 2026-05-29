import type { AtomTapHandle } from '@owebeeone/grip-react';
import { defineGrip } from '../runtime';
import type {
  ViewId, Peer, ChatMessage, DiffEndpoint, ThemeId,
  ChatLink, FileRef, OnboardingForm, ComposerDrag, ResizeDrag, GraphRenderNode, EditorGroup,
} from './types';
import { INITIAL_PEERS, INITIAL_CHAT, SELF_ID } from './fakeData';

// Navigation
export const CURRENT_VIEW = defineGrip<ViewId>('Lab.CurrentView', 'status');
export const CURRENT_VIEW_TAP = defineGrip<AtomTapHandle<ViewId>>('Lab.CurrentView.Tap');

// Appearance
export const THEME = defineGrip<ThemeId>('Lab.Theme', 'dark');
export const THEME_TAP = defineGrip<AtomTapHandle<ThemeId>>('Lab.Theme.Tap');

// Workspace presentation: tiled cards vs. animated graph
export const WORKSPACE_LAYOUT = defineGrip<'tiles' | 'graph'>('Lab.WorkspaceLayout', 'graph');
export const WORKSPACE_LAYOUT_TAP = defineGrip<AtomTapHandle<'tiles' | 'graph'>>('Lab.WorkspaceLayout.Tap');

// Which repo card's tools menu is open (repo path key), or null.
export const WORKSPACE_MENU = defineGrip<string | null>('Lab.WorkspaceMenu', null);
export const WORKSPACE_MENU_TAP = defineGrip<AtomTapHandle<string | null>>('Lab.WorkspaceMenu.Tap');

// Collaborators
export const PEERS = defineGrip<Peer[]>('Lab.Peers', INITIAL_PEERS);
export const PEERS_TAP = defineGrip<AtomTapHandle<Peer[]>>('Lab.Peers.Tap');

// The peer whose workspace is currently focused (status / file / diff views)
export const SELECTED_PEER_ID = defineGrip<string>('Lab.SelectedPeerId', SELF_ID);
export const SELECTED_PEER_ID_TAP = defineGrip<AtomTapHandle<string>>('Lab.SelectedPeerId.Tap');

// File viewer selection: "repoPath::path" or null (the active editor tab)
export const SELECTED_FILE = defineGrip<string | null>('Lab.SelectedFile', null);
export const SELECTED_FILE_TAP = defineGrip<AtomTapHandle<string | null>>('Lab.SelectedFile.Tap');

// Editor columns (split view) in the Files view + which column is focused.
export const EDITOR_GROUPS = defineGrip<EditorGroup[]>('Lab.EditorGroups', [{ id: 'g0', open: [], active: null }]);
export const EDITOR_GROUPS_TAP = defineGrip<AtomTapHandle<EditorGroup[]>>('Lab.EditorGroups.Tap');
export const ACTIVE_GROUP = defineGrip<string>('Lab.ActiveGroup', 'g0');
export const ACTIVE_GROUP_TAP = defineGrip<AtomTapHandle<string>>('Lab.ActiveGroup.Tap');

// Line to scroll to / highlight in the active file or diff view (1-based) or null.
export const FOCUS_LINE = defineGrip<number | null>('Lab.FocusLine', null);
export const FOCUS_LINE_TAP = defineGrip<AtomTapHandle<number | null>>('Lab.FocusLine.Tap');

// Diff viewer endpoints
export const DIFF_LEFT = defineGrip<DiffEndpoint>('Lab.DiffLeft', { peerId: SELF_ID, ref: 'head' });
export const DIFF_LEFT_TAP = defineGrip<AtomTapHandle<DiffEndpoint>>('Lab.DiffLeft.Tap');
export const DIFF_RIGHT = defineGrip<DiffEndpoint>('Lab.DiffRight', { peerId: SELF_ID, ref: 'working' });
export const DIFF_RIGHT_TAP = defineGrip<AtomTapHandle<DiffEndpoint>>('Lab.DiffRight.Tap');

// Chat
export const CHAT_MESSAGES = defineGrip<ChatMessage[]>('Lab.ChatMessages', INITIAL_CHAT);
export const CHAT_MESSAGES_TAP = defineGrip<AtomTapHandle<ChatMessage[]>>('Lab.ChatMessages.Tap');
export const CHAT_DRAFT = defineGrip<string>('Lab.ChatDraft', '');
export const CHAT_DRAFT_TAP = defineGrip<AtomTapHandle<string>>('Lab.ChatDraft.Tap');
export const CHAT_PENDING = defineGrip<ChatLink[]>('Lab.ChatPending', []);
export const CHAT_PENDING_TAP = defineGrip<AtomTapHandle<ChatLink[]>>('Lab.ChatPending.Tap');

// Chat panel (collapsible/resizable) + composer resize — all in grips, no React state.
export const CHAT_PANEL_OPEN = defineGrip<boolean>('Lab.ChatPanelOpen', true);
export const CHAT_PANEL_OPEN_TAP = defineGrip<AtomTapHandle<boolean>>('Lab.ChatPanelOpen.Tap');
export const CHAT_PANEL_WIDTH = defineGrip<number>('Lab.ChatPanelWidth', 360);
export const CHAT_PANEL_WIDTH_TAP = defineGrip<AtomTapHandle<number>>('Lab.ChatPanelWidth.Tap');
export const CHAT_PANEL_DRAGGING = defineGrip<boolean>('Lab.ChatPanelDragging', false);
export const CHAT_PANEL_DRAGGING_TAP = defineGrip<AtomTapHandle<boolean>>('Lab.ChatPanelDragging.Tap');
export const CHAT_COMPOSER_H = defineGrip<number>('Lab.ChatComposerH', 64);
export const CHAT_COMPOSER_H_TAP = defineGrip<AtomTapHandle<number>>('Lab.ChatComposerH.Tap');
export const CHAT_COMPOSER_DRAG = defineGrip<ComposerDrag | null>('Lab.ChatComposerDrag', null);
export const CHAT_COMPOSER_DRAG_TAP = defineGrip<AtomTapHandle<ComposerDrag | null>>('Lab.ChatComposerDrag.Tap');

// File viewer ref toggle + explorer collapsed folders
export const FILE_REF = defineGrip<FileRef>('Lab.FileRef', 'working');
export const FILE_REF_TAP = defineGrip<AtomTapHandle<FileRef>>('Lab.FileRef.Tap');
export const EXPLORER_COLLAPSED = defineGrip<string[]>('Lab.ExplorerCollapsed', []);
export const EXPLORER_COLLAPSED_TAP = defineGrip<AtomTapHandle<string[]>>('Lab.ExplorerCollapsed.Tap');

// File explorer panel: collapsible + resizable (like the chat panel).
export const EXPLORER_OPEN = defineGrip<boolean>('Lab.ExplorerOpen', true);
export const EXPLORER_OPEN_TAP = defineGrip<AtomTapHandle<boolean>>('Lab.ExplorerOpen.Tap');
export const EXPLORER_WIDTH = defineGrip<number>('Lab.ExplorerWidth', 240);
export const EXPLORER_WIDTH_TAP = defineGrip<AtomTapHandle<number>>('Lab.ExplorerWidth.Tap');
export const EXPLORER_DRAG = defineGrip<ResizeDrag | null>('Lab.ExplorerDrag', null);
export const EXPLORER_DRAG_TAP = defineGrip<AtomTapHandle<ResizeDrag | null>>('Lab.ExplorerDrag.Tap');

// Onboarding add-collaborator form + per-row check-in-progress
export const ONBOARDING_FORM = defineGrip<OnboardingForm>('Lab.OnboardingForm', { name: '', ssh: '', location: '', conn: { status: 'idle' } });
export const ONBOARDING_FORM_TAP = defineGrip<AtomTapHandle<OnboardingForm>>('Lab.OnboardingForm.Tap');

// Workspace graph nodes (published by the GraphSim tap engine)
export const GRAPH_NODES = defineGrip<GraphRenderNode[]>('Lab.GraphNodes', []);
