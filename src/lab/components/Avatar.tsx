import type { Peer } from '../types';
import { stockById, deriveColor, letterOf } from '../avatars';

// Small round avatar: a stock emoji image, a chosen letter color, or (default)
// a Google-style letter avatar with a color derived from the name.
export default function Avatar({ peer, size = 22 }: { peer?: Peer; size?: number }) {
  const name = peer?.name ?? '?';
  const av = peer?.avatar;

  if (av?.kind === 'stock') {
    const s = stockById(av.id);
    if (s) {
      return (
        <span className="avatar avatar-img" style={{ width: size, height: size, background: s.bg, fontSize: size * 0.58 }}>
          {s.emoji}
        </span>
      );
    }
  }
  const color = av?.kind === 'letter' ? av.color : deriveColor(name);
  return (
    <span className="avatar avatar-letter" style={{ width: size, height: size, background: color, fontSize: size * 0.5 }}>
      {letterOf(name)}
    </span>
  );
}
