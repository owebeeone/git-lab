import type { DragEvent } from 'react';
import type { ChatLink, DiffEndpoint, Peer } from './types';
import { buildStateUrl } from './stateUrl';

function fileKey(repoPath: string, path: string) {
  return `${repoPath}::${path}`;
}

// A state link reproduces a focused line in the diff viewer.
export function diffLineLink(
  repoPath: string, path: string, left: DiffEndpoint, right: DiffEndpoint, line: number,
): ChatLink {
  return {
    kind: 'state',
    label: `${repoPath}/${path}:L${line} (diff)`,
    target: buildStateUrl({ view: 'diff', file: fileKey(repoPath, path), diffLeft: left, diffRight: right, line }),
  };
}

// A state link reproduces a focused line in the file viewer for a collaborator.
export function fileLineLink(repoPath: string, path: string, peer: Peer | undefined, line: number): ChatLink {
  const peerTag = peer && !peer.isSelf ? ` @${peer.name}` : '';
  return {
    kind: 'state',
    label: `${repoPath}/${path}:L${line}${peerTag}`,
    target: buildStateUrl({ view: 'file', file: fileKey(repoPath, path), peerId: peer?.id, line }),
  };
}

// Build a chat link for a file reference, optionally scoped to a collaborator.
export function fileLink(repoPath: string, path: string, peer?: Peer): ChatLink {
  const base = `${repoPath}/${path}`;
  return {
    kind: 'file',
    label: peer && !peer.isSelf ? `${base} @${peer.name}` : base,
    target: `${repoPath}::${path}`,
    peerId: peer && !peer.isSelf ? peer.id : undefined,
  };
}

// Drag handlers to make any element a chat-droppable reference source. The
// payload matches what the chat composer's drop zone reads.
export function dragProps(link: ChatLink) {
  return {
    draggable: true,
    onDragStart: (e: DragEvent) => {
      e.dataTransfer.setData('application/json', JSON.stringify(link));
      e.dataTransfer.effectAllowed = 'copy';
    },
  };
}
