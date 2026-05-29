import { BaseTap, type Tap } from '@owebeeone/grip-react';
import { grok } from '../runtime';
import { GRAPH_NODES } from './grips';
import { dependencyEdges } from './fakeData';
import type { GraphRenderNode, RepoStatus } from './types';

// Force-directed graph simulation kept entirely outside React. The component is
// pure: it reads GRAPH_NODES (published by GraphSimTap) and calls engine methods
// from event handlers. No useState/useEffect/useRef in the view.

export const VBW = 840;
export const VBH = 520;
const SPRING_LEN = 210;
const SPRING_K = 0.04;
const PADDING = 34;
const GRAVITY = 0.014;
const FRICTION = 0.82;
const SETTLE = 0.18;

interface PNode {
  id: string; repo: RepoStatus; color: string;
  x: number; y: number; vx: number; vy: number;
  width: number; height: number;
  baseW: number; baseH: number; expW: number; expH: number;
}

function statusColor(r: RepoStatus): string {
  if (r.dirty) return '#e3b341';
  if (r.behind > 0) return '#f85149';
  if (r.ahead > 0) return '#8ab4ff';
  return '#3fb950';
}

let nodes: PNode[] = [];
let links: { source: string; target: string }[] = [];
let repoKey = '';
let hover: string | null = null;
let dragId: string | null = null;
let pinned: string | null = null;
let dragOffX = 0;
let dragOffY = 0;
let publishFn: ((n: GraphRenderNode[]) => void) | null = null;
let raf = 0;
let running = false;

function build(repos: RepoStatus[]) {
  nodes = repos.map((r, i) => {
    const a = (i / Math.max(1, repos.length)) * Math.PI * 2;
    return {
      id: r.path || 'root', repo: r, color: statusColor(r),
      x: r.path === '' ? VBW / 2 : VBW / 2 + Math.cos(a) * 180,
      y: r.path === '' ? VBH / 2 : VBH / 2 + Math.sin(a) * 150,
      vx: (Math.random() - 0.5) * 4, vy: (Math.random() - 0.5) * 4,
      width: 168, height: 66, baseW: 168, baseH: 66, expW: 250, expH: 168,
    };
  });
  // Edges are the (cached) dependency hierarchy, not filesystem containment.
  links = dependencyEdges(repos.map((r) => r.path));
}

function isExpanded(id: string) {
  return pinned === id || hover === id || dragId === id;
}

function snapshot(): GraphRenderNode[] {
  return nodes.map((n) => ({
    id: n.id, repoPath: n.repo.path, name: n.repo.name, branch: n.repo.branch,
    head: n.repo.head, ahead: n.repo.ahead, behind: n.repo.behind, dirty: n.repo.dirty,
    color: n.color, x: n.x, y: n.y, w: n.width, h: n.height,
    expanded: isExpanded(n.id), changedFiles: n.repo.changedFiles,
  }));
}

function step() {
  if (!nodes.length) { publishFn?.([]); running = false; return; }
  let activity = 0;

  nodes.forEach((n) => {
    const exp = isExpanded(n.id);
    const tw = exp ? n.expW : n.baseW;
    const th = exp ? n.expH : n.baseH;
    n.width += (tw - n.width) * 0.16;
    n.height += (th - n.height) * 0.16;
    activity += Math.abs(tw - n.width) + Math.abs(th - n.height);
  });

  links.forEach((l) => {
    const s = nodes.find((n) => n.id === l.source);
    const t = nodes.find((n) => n.id === l.target);
    if (!s || !t) return;
    const dx = t.x - s.x; const dy = t.y - s.y;
    const dist = Math.sqrt(dx * dx + dy * dy) || 0.1;
    const f = (dist - SPRING_LEN) * SPRING_K;
    const fx = (dx / dist) * f; const fy = (dy / dist) * f;
    if (s.id !== dragId) { s.vx += fx; s.vy += fy; }
    if (t.id !== dragId) { t.vx -= fx; t.vy -= fy; }
  });

  nodes.forEach((n) => {
    if (n.id === dragId) return;
    n.vx += (VBW / 2 - n.x) * GRAVITY;
    n.vy += (VBH / 2 - n.y) * GRAVITY;
  });

  for (let i = 0; i < nodes.length; i++) {
    for (let j = i + 1; j < nodes.length; j++) {
      const a = nodes[i]; const b = nodes[j];
      const minW = (a.width + b.width) / 2 + PADDING;
      const minH = (a.height + b.height) / 2 + PADDING;
      const dx = b.x - a.x; const dy = b.y - a.y;
      const ox = minW - Math.abs(dx); const oy = minH - Math.abs(dy);
      if (ox > 0 && oy > 0) {
        if (ox < oy) {
          const push = (dx > 0 ? 1 : -1) * ox * 0.5;
          if (a.id !== dragId) { a.x -= push; a.vx -= push * 0.4; }
          if (b.id !== dragId) { b.x += push; b.vx += push * 0.4; }
        } else {
          const push = (dy > 0 ? 1 : -1) * oy * 0.5;
          if (a.id !== dragId) { a.y -= push; a.vy -= push * 0.4; }
          if (b.id !== dragId) { b.y += push; b.vy += push * 0.4; }
        }
      }
    }
  }

  nodes.forEach((n) => {
    if (n.id !== dragId) {
      n.x += n.vx; n.y += n.vy;
      activity += Math.abs(n.vx) + Math.abs(n.vy);
      n.vx *= FRICTION; n.vy *= FRICTION;
    }
    const px = n.width / 2 + 10; const py = n.height / 2 + 10;
    if (n.x < px) { n.x = px; n.vx *= -0.2; }
    if (n.x > VBW - px) { n.x = VBW - px; n.vx *= -0.2; }
    if (n.y < py) { n.y = py; n.vy *= -0.2; }
    if (n.y > VBH - py) { n.y = VBH - py; n.vy *= -0.2; }
  });

  publishFn?.(snapshot());

  if (activity < SETTLE && !dragId) {
    nodes.forEach((n) => {
      const exp = isExpanded(n.id);
      n.width = exp ? n.expW : n.baseW;
      n.height = exp ? n.expH : n.baseH;
      n.vx = 0; n.vy = 0;
    });
    publishFn?.(snapshot());
    running = false;
    return;
  }
  raf = requestAnimationFrame(step);
}

function wake() {
  if (!running && publishFn) { running = true; raf = requestAnimationFrame(step); }
}

export const graphEngine = {
  setInput(repos: RepoStatus[]) {
    const key = repos.map((r) => `${r.path}:${r.head}:${r.dirty}:${r.ahead}:${r.behind}`).join('|');
    if (key !== repoKey) { repoKey = key; build(repos); publishFn?.(snapshot()); wake(); }
  },
  attach(fn: (n: GraphRenderNode[]) => void) { publishFn = fn; fn(snapshot()); wake(); },
  detach() { publishFn = null; if (raf) cancelAnimationFrame(raf); running = false; },
  setHover(id: string | null) { if (hover !== id) { hover = id; wake(); } },
  pin(id: string | null) { if (pinned !== id) { pinned = id; wake(); } },
  startDrag(id: string, p: { x: number; y: number }) {
    dragId = id;
    const n = nodes.find((x) => x.id === id);
    if (n) { dragOffX = p.x - n.x; dragOffY = p.y - n.y; }
    wake();
  },
  moveDrag(p: { x: number; y: number }) {
    if (!dragId) return;
    const n = nodes.find((x) => x.id === dragId);
    if (n) { n.x = p.x - dragOffX; n.y = p.y - dragOffY; n.vx = 0; n.vy = 0; }
    wake();
  },
  endDrag() { if (dragId) { dragId = null; wake(); } },
  scatter() { nodes.forEach((n) => { n.vx = (Math.random() - 0.5) * 22; n.vy = (Math.random() - 0.5) * 22; }); wake(); },
};

class GraphSimTapImpl extends BaseTap implements Tap {
  constructor() { super({ provides: [GRAPH_NODES] }); }
  private publishNodes = (n: GraphRenderNode[]) => {
    this.publish(new Map([[GRAPH_NODES as never, n as never]]));
  };
  onConnect(dest: unknown, grip: unknown): void {
    super.onConnect(dest as never, grip as never);
    graphEngine.attach(this.publishNodes);
  }
  onDisconnect(dest: unknown, grip: unknown): void {
    super.onDisconnect(dest as never, grip as never);
    const has = (this.producer?.getDestinations().size ?? 0) > 0;
    if (!has) graphEngine.detach();
  }
  produce(): void {}
  produceOnParams(): void {}
  produceOnDestParams(): void {}
}

export function registerGraphSimTap() {
  grok.registerTap(new GraphSimTapImpl() as unknown as Tap);
}
