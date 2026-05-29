// Minimal LCS-based line diff for the mock's side-by-side diff viewer.

export type DiffRowKind = 'same' | 'add' | 'del';

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
