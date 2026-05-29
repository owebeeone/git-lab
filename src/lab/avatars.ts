import type { StockAvatar } from './types';

// 20 stock avatars: an emoji on a colored circle (dependency-free, no binaries).
export const STOCK_AVATARS: StockAvatar[] = [
  { id: 'fox', emoji: '🦊', bg: '#e8763a' },
  { id: 'panda', emoji: '🐼', bg: '#475569' },
  { id: 'penguin', emoji: '🐧', bg: '#2b6cb0' },
  { id: 'owl', emoji: '🦉', bg: '#8a5a2b' },
  { id: 'octopus', emoji: '🐙', bg: '#b83280' },
  { id: 'turtle', emoji: '🐢', bg: '#2f855a' },
  { id: 'raccoon', emoji: '🦝', bg: '#4a5568' },
  { id: 'rabbit', emoji: '🐰', bg: '#9f7aea' },
  { id: 'tiger', emoji: '🐯', bg: '#dd6b20' },
  { id: 'lion', emoji: '🦁', bg: '#d69e2e' },
  { id: 'frog', emoji: '🐸', bg: '#38a169' },
  { id: 'whale', emoji: '🐳', bg: '#3182ce' },
  { id: 'unicorn', emoji: '🦄', bg: '#d53f8c' },
  { id: 'bee', emoji: '🐝', bg: '#b7791f' },
  { id: 'butterfly', emoji: '🦋', bg: '#6b46c1' },
  { id: 'dolphin', emoji: '🐬', bg: '#319795' },
  { id: 'parrot', emoji: '🦜', bg: '#e53e3e' },
  { id: 'wolf', emoji: '🐺', bg: '#718096' },
  { id: 'zebra', emoji: '🦓', bg: '#2d3748' },
  { id: 'hedgehog', emoji: '🦔', bg: '#975a16' },
];

// Palette for letter avatars (and the per-letter default color).
export const LETTER_COLORS = [
  '#ef4444', '#f59e0b', '#eab308', '#10b981', '#14b8a6',
  '#3b82f6', '#6366f1', '#8b5cf6', '#ec4899', '#64748b',
];

export function stockById(id: string): StockAvatar | undefined {
  return STOCK_AVATARS.find((a) => a.id === id);
}

export function letterOf(name: string): string {
  return (name.trim()[0] || '?').toUpperCase();
}

// Deterministic color for a name when no avatar is chosen (Google-style).
export function deriveColor(name: string): string {
  let h = 0;
  for (const ch of name) h = (h * 31 + ch.charCodeAt(0)) >>> 0;
  return LETTER_COLORS[h % LETTER_COLORS.length];
}
