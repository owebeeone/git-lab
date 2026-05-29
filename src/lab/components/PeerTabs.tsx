import { useGrip } from '@owebeeone/grip-react';
import { PEERS, SELECTED_PEER_ID, SELECTED_PEER_ID_TAP } from '../grips';

export default function PeerTabs() {
  const peers = useGrip(PEERS) ?? [];
  const selected = useGrip(SELECTED_PEER_ID);
  const selectedTap = useGrip(SELECTED_PEER_ID_TAP);

  return (
    <div className="peer-tabs">
      {peers.map((p) => (
        <button
          key={p.id}
          className={`peer-tab${selected === p.id ? ' active' : ''}`}
          onClick={() => selectedTap?.set(p.id)}
        >
          <span className={`dot ${p.online ? 'on' : 'off'}`} />
          {p.name}{p.isSelf ? ' (you)' : ''}
        </button>
      ))}
    </div>
  );
}
