import { useGrip } from '@owebeeone/grip-react';
import ChatView from './ChatView';
import {
  CHAT_PANEL_OPEN, CHAT_PANEL_OPEN_TAP,
  CHAT_PANEL_WIDTH, CHAT_PANEL_WIDTH_TAP,
  CHAT_PANEL_DRAGGING, CHAT_PANEL_DRAGGING_TAP,
} from '../grips';

const MIN_WIDTH = 280;
const MAX_WIDTH = 720;

export default function ChatPanel() {
  const open = useGrip(CHAT_PANEL_OPEN) ?? true;
  const openTap = useGrip(CHAT_PANEL_OPEN_TAP);
  const width = useGrip(CHAT_PANEL_WIDTH) ?? 360;
  const widthTap = useGrip(CHAT_PANEL_WIDTH_TAP);
  const dragging = useGrip(CHAT_PANEL_DRAGGING) ?? false;
  const draggingTap = useGrip(CHAT_PANEL_DRAGGING_TAP);

  if (!open) {
    return (
      <button className="chat-collapsed-tab" onClick={() => openTap?.set(true)} title="Open chat">
        Chat ›
      </button>
    );
  }

  return (
    <>
      {/* While resizing, a full-window overlay captures the drag (no window listeners). */}
      {dragging && (
        <div
          className="drag-overlay col"
          onMouseMove={(e) => widthTap?.set(Math.max(MIN_WIDTH, Math.min(MAX_WIDTH, window.innerWidth - e.clientX)))}
          onMouseUp={() => draggingTap?.set(false)}
        />
      )}
      <div className="chat-resizer" onMouseDown={() => draggingTap?.set(true)} title="Drag to resize" />
      <aside className="chat-panel" style={{ width }}>
        <div className="chat-panel-head">
          <strong>Chat</strong>
          <button className="ghost" onClick={() => openTap?.set(false)} title="Collapse">›</button>
        </div>
        <div className="chat-panel-body">
          <ChatView embedded />
        </div>
      </aside>
    </>
  );
}
