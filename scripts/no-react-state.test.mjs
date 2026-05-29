#!/usr/bin/env node
// Fails if `useState` or `useEffect` appears anywhere under src/.
// grip-lab forbids React local state — all state lives in grips (see
// dev-docs/GLCodingRules.md). Comments and strings are stripped before scanning
// so documentation that mentions these names does not trip the check.

import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join, dirname, relative } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const srcDir = join(root, 'src');
const BANNED = ['useState', 'useEffect'];
const exts = new Set(['.ts', '.tsx', '.js', '.jsx']);

function walk(dir) {
  const out = [];
  for (const entry of readdirSync(dir)) {
    const p = join(dir, entry);
    if (statSync(p).isDirectory()) out.push(...walk(p));
    else if (exts.has(p.slice(p.lastIndexOf('.')))) out.push(p);
  }
  return out;
}

function stripCommentsAndStrings(code) {
  return code
    .replace(/\/\*[\s\S]*?\*\//g, ' ')      // block comments
    .replace(/\/\/[^\n]*/g, ' ')            // line comments
    .replace(/`(?:\\[\s\S]|[^\\`])*`/g, ' ') // template strings
    .replace(/'(?:\\.|[^\\'])*'/g, ' ')      // single-quoted strings
    .replace(/"(?:\\.|[^\\"])*"/g, ' ');     // double-quoted strings
}

const violations = [];
for (const file of walk(srcDir)) {
  const cleaned = stripCommentsAndStrings(readFileSync(file, 'utf8'));
  const lines = cleaned.split('\n');
  lines.forEach((line, i) => {
    for (const name of BANNED) {
      if (new RegExp(`\\b${name}\\b`).test(line)) {
        violations.push(`${relative(root, file)}:${i + 1}  uses ${name}`);
      }
    }
  });
}

if (violations.length) {
  console.error('FAIL: React local state is banned in grip-lab (use grips). Found:');
  for (const v of violations) console.error('  ' + v);
  process.exit(1);
}
console.log('OK: no useState/useEffect found in src/.');
