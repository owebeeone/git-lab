import type { FileImage, FileRef, Peer } from './types';

// Resolve a file's contents for a given collaborator + ref. In the real system
// every (peer, ref) resolves through the delta protocol; in the mock the file
// is the same and we tag non-self peers so cross-user views are distinguishable.
export function resolveContent(file: FileImage, peerId: string, ref: FileRef, peers: Peer[]): string {
  const base = file.contentsByRef[ref] ?? file.contentsByRef.working ?? '';
  const peer = peers.find((p) => p.id === peerId);
  if (peer && !peer.isSelf) {
    return `# ${peer.name}'s ${ref}\n${base}`;
  }
  return base;
}
