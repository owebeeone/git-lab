import { useGrip } from '@owebeeone/grip-react';
import { PEERS, SELECTED_PEER_ID, SELECTED_PEER_ID_TAP } from '../grips';

// Compact collaborator selector (replaces the peer tab row).
export default function PeerSelect() {
  const peers = useGrip(PEERS) ?? [];
  const selected = useGrip(SELECTED_PEER_ID) ?? '';
  const tap = useGrip(SELECTED_PEER_ID_TAP);

  return (
    <label className="peer-select-wrap">
      <span className="peer-select-label">Collaborator</span>
      <select className="peer-select" value={selected} onChange={(e) => tap?.set(e.target.value)}>
        {peers.map((p) => (
          <option key={p.id} value={p.id}>{p.name}{p.isSelf ? ' (you)' : ''}</option>
        ))}
      </select>
    </label>
  );
}
