import { useGrip } from '@owebeeone/grip-react';
import {
  PEERS, PEERS_TAP, ONBOARDING_FORM, ONBOARDING_FORM_TAP,
  COLLAB_EDIT, COLLAB_EDIT_TAP, AVATAR_EDIT, AVATAR_EDIT_TAP,
} from '../grips';
import type { CollabEdit, OnboardingForm, OsKind, Peer, ProbeResult, ShellKind } from '../types';
import { STOCK_AVATARS, LETTER_COLORS } from '../avatars';
import Avatar from './Avatar';

const DEFAULT_PORT = 3141; // signature port (π) — uncommon, memorable
const EMPTY_FORM: OnboardingForm = { name: '', ssh: '', location: '', conn: { status: 'idle' } };

const OS_LABEL: Record<OsKind, string> = {
  macos: 'macOS', linux: 'Linux', windows: 'Windows',
};

// Mock probe. In the real client this connects to the peer and inspects the
// remote OS + available shells. Here we approximate from the ssh host.
function probe(sshAddress: string): ProbeResult {
  const host = sshAddress.toLowerCase();
  let os: OsKind = 'linux';
  if (/win|windows|msys/.test(host)) os = 'windows';
  else if (/mac|darwin|local/.test(host)) os = 'macos';
  const shells: ShellKind[] = os === 'windows' ? ['powershell'] : os === 'macos' ? ['zsh', 'bash'] : ['bash'];
  return { os, shells, online: true };
}

export default function OnboardingView() {
  const peers = useGrip(PEERS) ?? [];
  const peersTap = useGrip(PEERS_TAP);
  const form = useGrip(ONBOARDING_FORM) ?? EMPTY_FORM;
  const formTap = useGrip(ONBOARDING_FORM_TAP);
  const setForm = (patch: Partial<OnboardingForm>) => formTap?.set({ ...form, ...patch });

  const edit = useGrip(COLLAB_EDIT) ?? null;
  const editTap = useGrip(COLLAB_EDIT_TAP);
  const avatarEdit = useGrip(AVATAR_EDIT) ?? null;
  const avatarEditTap = useGrip(AVATAR_EDIT_TAP);
  const avatarPeer = peers.find((p) => p.id === avatarEdit);

  const updatePeer = (id: string, patch: Partial<Peer>) =>
    peersTap?.set(peers.map((p) => (p.id === id ? { ...p, ...patch } : p)));

  // Connect/probe the connection string (synchronous in the mock).
  const connect = (address: string) => {
    if (!address.trim()) { setForm({ conn: { status: 'idle' } }); return; }
    const r = probe(address);
    setForm({ conn: { status: 'connected', os: r.os, shells: r.shells } });
  };

  const add = () => {
    if (!form.name.trim() || !form.ssh.trim() || !form.location.trim()) return;
    const connected = form.conn.status === 'connected';
    const peer: Peer = {
      id: `${form.name.trim().toLowerCase().replace(/\s+/g, '-')}-${peers.length}`,
      name: form.name.trim(),
      sshAddress: form.ssh.trim(),
      location: form.location.trim(),
      os: connected ? form.conn.os ?? null : null,
      shells: connected ? form.conn.shells ?? [] : [],
      online: connected,
      isSelf: false,
    };
    peersTap?.set([...peers, peer]);
    formTap?.set(EMPTY_FORM);
  };

  const remove = (id: string) => peersTap?.set(peers.filter((p) => p.id !== id));

  const check = (id: string) => {
    const target = peers.find((p) => p.id === id);
    if (!target) return;
    const r = probe(target.sshAddress);
    peersTap?.set(peers.map((p) => (p.id === id ? { ...p, os: r.os, shells: r.shells, online: r.online } : p)));
  };

  // Inline-editable cell: click to edit, commit on blur/Enter.
  const cell = (p: Peer, field: CollabEdit['field'], mono = false) => {
    const editing = edit?.peerId === p.id && edit?.field === field;
    if (editing) {
      return (
        <input
          autoFocus
          className={`cell-input${mono ? ' mono' : ''}`}
          value={p[field]}
          onChange={(e) => updatePeer(p.id, { [field]: e.target.value })}
          onBlur={() => editTap?.set(null)}
          onKeyDown={(e) => { if (e.key === 'Enter' || e.key === 'Escape') editTap?.set(null); }}
        />
      );
    }
    return (
      <span className={`cell-edit${mono ? ' mono' : ''}`} title="Click to edit" onClick={() => editTap?.set({ peerId: p.id, field })}>
        {p[field] || <span className="muted">—</span>}
      </span>
    );
  };

  return (
    <section className="view">
      <table className="peer-table">
        <thead>
          <tr>
            <th></th><th>Name</th><th>ssh address</th><th>Location</th>
            <th>OS</th><th>Shells</th><th>Status</th><th></th>
          </tr>
        </thead>
        <tbody>
          {peers.map((p) => (
            <tr key={p.id}>
              <td>
                <button className="avatar-btn" onClick={() => avatarEditTap?.set(p.id)} title="Edit avatar">
                  <Avatar peer={p} size={26} />
                </button>
              </td>
              <td>{cell(p, 'name')}{p.isSelf ? <span className="muted"> (you)</span> : null}</td>
              <td>{cell(p, 'sshAddress', true)}</td>
              <td>{cell(p, 'location', true)}</td>
              <td>{p.os ? OS_LABEL[p.os] : <span className="muted">unknown</span>}</td>
              <td>{p.shells.length ? p.shells.join(', ') : <span className="muted">—</span>}</td>
              <td><span className={`dot ${p.online ? 'on' : 'off'}`} />{p.online ? 'online' : 'offline'}</td>
              <td className="row-actions">
                {!p.isSelf && <button className="ghost" onClick={() => check(p.id)}>check</button>}
                {!p.isSelf && <button className="ghost" onClick={() => remove(p.id)}>remove</button>}
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      {avatarPeer && (
        <div className="modal-backdrop" onClick={() => avatarEditTap?.set(null)}>
          <div className="modal avatar-modal" onClick={(e) => e.stopPropagation()}>
            <div className="modal-head">
              <strong>Avatar — {avatarPeer.name}</strong>
              <button className="ghost" onClick={() => avatarEditTap?.set(null)} title="Close">×</button>
            </div>
            <div className="modal-body">
              <div className="avatar-preview">
                <Avatar peer={avatarPeer} size={56} />
              </div>
              <div className="field-label">Images</div>
              <div className="avatar-grid">
                {STOCK_AVATARS.map((s) => {
                  const sel = avatarPeer.avatar?.kind === 'stock' && avatarPeer.avatar.id === s.id;
                  return (
                    <button
                      key={s.id}
                      className={`avatar-pick${sel ? ' sel' : ''}`}
                      style={{ background: s.bg }}
                      title={s.id}
                      onClick={() => updatePeer(avatarPeer.id, { avatar: { kind: 'stock', id: s.id } })}
                    >
                      {s.emoji}
                    </button>
                  );
                })}
              </div>
              <div className="field-label">Letter color</div>
              <div className="color-row">
                {LETTER_COLORS.map((c) => {
                  const sel = avatarPeer.avatar?.kind === 'letter' && avatarPeer.avatar.color === c;
                  return (
                    <button
                      key={c}
                      className={`color-swatch${sel ? ' sel' : ''}`}
                      style={{ background: c }}
                      title={c}
                      onClick={() => updatePeer(avatarPeer.id, { avatar: { kind: 'letter', color: c } })}
                    />
                  );
                })}
              </div>
            </div>
            <div className="modal-foot">
              <button className="ghost" onClick={() => updatePeer(avatarPeer.id, { avatar: undefined })}>Use default</button>
              <button className="primary" onClick={() => avatarEditTap?.set(null)}>Done</button>
            </div>
          </div>
        </div>
      )}

      <div className="add-peer">
        <h3>Add collaborator</h3>
        <div className="form-row">
          <input placeholder="Name" value={form.name} onChange={(e) => setForm({ name: e.target.value })} />
          <input
            placeholder={`user@host:${DEFAULT_PORT}`}
            value={form.ssh}
            onChange={(e) => setForm({ ssh: e.target.value, conn: { status: 'idle' } })}
            onBlur={() => connect(form.ssh)}
            onKeyDown={(e) => { if (e.key === 'Enter') connect(form.ssh); }}
          />
          <input
            className="loc-input"
            placeholder="remote workspace root (e.g. ~/work/project)"
            value={form.location}
            onChange={(e) => setForm({ location: e.target.value })}
          />
          <button className="primary" onClick={add}>Add</button>
        </div>

        <div className="conn-status">
          {form.conn.status !== 'connected' && (
            <span className="muted">Enter a connection string to check the peer.</span>
          )}
          {form.conn.status === 'connected' && form.conn.os && (
            <>
              <span className="dot on" />connected — <strong>{OS_LABEL[form.conn.os]}</strong>
              <span className="muted"> · shells: {(form.conn.shells ?? []).join(', ')}</span>
            </>
          )}
        </div>
      </div>
    </section>
  );
}
