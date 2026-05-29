import { useGrip } from '@owebeeone/grip-react';
import { GRAPH_NODES } from '../grips';
import { dragProps, fileLink } from '../dnd';
import { dependencyEdges } from '../fakeData';
import { graphEngine, VBW, VBH } from '../graphEngine';
import { useEditor } from '../useEditor';
import PeerSelect from './PeerSelect';
import type { GraphRenderNode, Peer, RepoStatus } from '../types';

function toCanvas(svg: SVGSVGElement, clientX: number, clientY: number) {
  const rect = svg.getBoundingClientRect();
  return { x: (clientX - rect.left) * (VBW / rect.width), y: (clientY - rect.top) * (VBH / rect.height) };
}

function boundaryIntersection(from: GraphRenderNode, to: GraphRenderNode) {
  const dx = from.x - to.x; const dy = from.y - to.y;
  if (Math.abs(dx) < 0.001 && Math.abs(dy) < 0.001) return { x: to.x, y: to.y };
  const scale = Math.min((to.w / 2) / (Math.abs(dx) || Infinity), (to.h / 2) / (Math.abs(dy) || Infinity));
  return { x: to.x + dx * scale, y: to.y + dy * scale };
}

export default function WorkspaceGraphView({ repos, peer }: { repos: RepoStatus[]; peer?: Peer }) {
  const { openInFiles } = useEditor();
  const nodes = useGrip(GRAPH_NODES) ?? [];

  // Feed the latest repo set to the engine (idempotent; not React state).
  graphEngine.setInput(repos);

  const byId = new Map(nodes.map((n) => [n.id, n]));
  // Dependency edges (source depends on target), arrow points to the dependency.
  const edges = dependencyEdges(nodes.map((n) => n.repoPath))
    .map((e) => {
      const s = byId.get(e.source);
      const t = byId.get(e.target);
      if (!s || !t) return null;
      const ti = boundaryIntersection(s, t);
      const si = boundaryIntersection(t, s);
      const angle = Math.atan2(ti.y - si.y, ti.x - si.x);
      const al = 9; const aw = 5.5;
      const p1x = ti.x - al * Math.cos(angle) + aw * Math.sin(angle);
      const p1y = ti.y - al * Math.sin(angle) - aw * Math.cos(angle);
      const p2x = ti.x - al * Math.cos(angle) - aw * Math.sin(angle);
      const p2y = ti.y - al * Math.sin(angle) + aw * Math.cos(angle);
      const hot = s.expanded || t.expanded;
      return { id: `${e.source}->${e.target}`, x1: si.x, y1: si.y, x2: ti.x, y2: ti.y, arrow: `M ${ti.x} ${ti.y} L ${p1x} ${p1y} L ${p2x} ${p2y} Z`, color: hot ? s.color : 'var(--border)', hot };
    })
    .filter(Boolean) as { id: string; x1: number; y1: number; x2: number; y2: number; arrow: string; color: string; hot: boolean }[];

  const openInTab = (repoPath: string, path: string) => openInFiles(`${repoPath}::${path}`);

  return (
    <div className="graph-wrap">
      <div className="graph-toolbar">
        <div className="graph-toolbar-left">
          <PeerSelect />
          <span className="muted">Drag nodes to anchor · click to pin · hover to expand</span>
        </div>
        <button className="ghost" onClick={() => graphEngine.scatter()}>↻ Re-layout</button>
      </div>
      <svg
        className="graph-svg"
        viewBox={`0 0 ${VBW} ${VBH}`}
        preserveAspectRatio="xMidYMid meet"
        onMouseMove={(e) => graphEngine.moveDrag(toCanvas(e.currentTarget, e.clientX, e.clientY))}
        onMouseUp={() => graphEngine.endDrag()}
        onMouseLeave={() => graphEngine.endDrag()}
        onClick={() => graphEngine.pin(null)}
      >
        <g>
          {edges.map((e) => (
            <g key={e.id}>
              <line x1={e.x1} y1={e.y1} x2={e.x2} y2={e.y2} stroke={e.color} strokeWidth={e.hot ? 2.4 : 1.5} />
              <path d={e.arrow} fill={e.color} />
            </g>
          ))}
        </g>
        <g>
          {nodes.map((n) => (
            <g
              key={n.id}
              transform={`translate(${n.x}, ${n.y})`}
              onMouseEnter={() => graphEngine.setHover(n.id)}
              onMouseLeave={() => graphEngine.setHover(null)}
              onMouseDown={(e) => {
                const svg = (e.currentTarget as SVGGElement).ownerSVGElement;
                if (svg) graphEngine.startDrag(n.id, toCanvas(svg, e.clientX, e.clientY));
              }}
              onClick={(e) => { e.stopPropagation(); graphEngine.pin(n.id); }}
              style={{ cursor: 'grab' }}
            >
              <rect x={-n.w / 2} y={-n.h / 2} width={n.w} height={n.h} rx={10}
                fill="var(--card)" stroke={n.expanded ? n.color : 'var(--border)'} strokeWidth={n.expanded ? 2 : 1.2} />
              <rect x={-n.w / 2} y={-n.h / 2} width={5} height={n.h} rx={2} fill={n.color} />
              <foreignObject x={-n.w / 2 + 10} y={-n.h / 2 + 6} width={n.w - 18} height={n.h - 12}>
                <div className="gnode-body">
                  <div className="gnode-title">
                    <strong>{n.name}</strong>
                    <span className={`state ${n.dirty ? 'dirty' : 'clean'}`}>{n.dirty ? 'dirty' : 'clean'}</span>
                  </div>
                  <div className="gnode-meta">
                    <span className="branch">⎇ {n.branch}</span>
                    <span className="sha">{n.head}</span>
                    {n.ahead > 0 && <span className="ahead">↑{n.ahead}</span>}
                    {n.behind > 0 && <span className="behind">↓{n.behind}</span>}
                  </div>
                  {n.expanded && n.changedFiles.length > 0 && (
                    <ul className="gnode-files">
                      {n.changedFiles.map((f) => (
                        <li key={f.path}>
                          <button
                            className="file-link"
                            {...dragProps(fileLink(n.repoPath, f.path, peer))}
                            onClick={(ev) => { ev.stopPropagation(); openInTab(n.repoPath, f.path); }}
                          >
                            {f.path}
                          </button>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              </foreignObject>
            </g>
          ))}
        </g>
      </svg>
    </div>
  );
}
