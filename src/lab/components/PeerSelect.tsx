import { useGrip } from '@owebeeone/grip-react';
import { PEERS, SELECTED_PEER_ID, SELECTED_PEER_ID_TAP } from '../grips';
import Avatar from './Avatar';

// Compact collaborator selector (replaces the peer tab row).
export default function PeerSelect() {
  const peers = useGrip(PEERS) ?? [];
  const selected = useGrip(SELECTED_PEER_ID) ?? '';
  const tap = useGrip(SELECTED_PEER_ID_TAP);
  const selectedPeer = peers.find((p) => p.id === selected);

  if (peers.length === 0) {
    return (
      <label className="peer-select-wrap">
        <span className="peer-select-label">Collaborator</span>
        <select className="peer-select" value="" disabled>
          <option value="">Loading collaborators...</option>
        </select>
      </label>
    );
  }

  return (
    <label className="peer-select-wrap">
      <span className="peer-select-label">Collaborator</span>
      <Avatar peer={selectedPeer} size={18} />
      <select className="peer-select" value={selectedPeer?.id ?? peers[0]?.id ?? ''} onChange={(e) => tap?.set(e.target.value)}>
        {peers.map((p) => (
          <option key={p.id} value={p.id}>{p.name}{p.isSelf ? ' (you)' : ''}</option>
        ))}
      </select>
    </label>
  );
}
