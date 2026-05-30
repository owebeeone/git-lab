// Minimal LCS-based line diff for the mock's side-by-side diff viewer.
import type { DiffHunk } from './serviceClient/diff';

export type DiffRowKind = 'same' | 'add' | 'del' | 'change';

export interface DiffRow {
  kind: DiffRowKind;
  left: string | null;
  right: string | null;
  leftNo: number | null;
  rightNo: number | null;
}

export function lineDiff(a: string, b: string): DiffRow[] {
  const left = a.replace(/\n$/, '').split('\n');
  const right = b.replace(/\n$/, '').split('\n');
  const m = left.length;
  const n = right.length;

  // LCS length table
  const lcs: number[][] = Array.from({ length: m + 1 }, () => new Array(n + 1).fill(0));
  for (let i = m - 1; i >= 0; i--) {
    for (let j = n - 1; j >= 0; j--) {
      lcs[i][j] = left[i] === right[j]
        ? lcs[i + 1][j + 1] + 1
        : Math.max(lcs[i + 1][j], lcs[i][j + 1]);
    }
  }

  const rows: DiffRow[] = [];
  let i = 0;
  let j = 0;
  while (i < m && j < n) {
    if (left[i] === right[j]) {
      rows.push({ kind: 'same', left: left[i], right: right[j], leftNo: i + 1, rightNo: j + 1 });
      i++; j++;
    } else if (lcs[i + 1][j] >= lcs[i][j + 1]) {
      rows.push({ kind: 'del', left: left[i], right: null, leftNo: i + 1, rightNo: null });
      i++;
    } else {
      rows.push({ kind: 'add', left: null, right: right[j], leftNo: null, rightNo: j + 1 });
      j++;
    }
  }
  while (i < m) { rows.push({ kind: 'del', left: left[i], right: null, leftNo: i + 1, rightNo: null }); i++; }
  while (j < n) { rows.push({ kind: 'add', left: null, right: right[j], leftNo: null, rightNo: j + 1 }); j++; }
  return rows;
}

export function rowsToDiffHunks(rows: DiffRow[]): DiffHunk[] {
  if (rows.length === 0) return [];
  const leftNumbers = rows.map((row) => row.leftNo).filter((n): n is number => n != null);
  const rightNumbers = rows.map((row) => row.rightNo).filter((n): n is number => n != null);
  return [{
    id: 'h000001',
    leftStart: leftNumbers.length ? Math.min(...leftNumbers) : 1,
    leftLines: leftNumbers.length,
    rightStart: rightNumbers.length ? Math.min(...rightNumbers) : 1,
    rightLines: rightNumbers.length,
    lines: rows,
  }];
}
