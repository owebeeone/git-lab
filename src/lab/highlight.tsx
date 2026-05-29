import React from 'react';
import type { ChatLink } from './types';
import { dragProps } from './dnd';

// Scroll a focused line into view when it mounts (ref callback, no effects).
function scrollFocusIntoView(el: HTMLDivElement | null) {
  if (el) el.scrollIntoView({ block: 'center', behavior: 'smooth' });
}

// Tiny dependency-free syntax highlighter for the mock. Approximate on purpose:
// it colors strings, comments, numbers, and a small keyword set. A vetted
// highlighter (pinned per the dependency-age policy) replaces this later.

const KEYWORDS = new Set([
  // shared-ish keyword set across python / ts
  'def', 'class', 'return', 'if', 'elif', 'else', 'for', 'while', 'import',
  'from', 'as', 'in', 'not', 'and', 'or', 'is', 'None', 'True', 'False',
  'const', 'let', 'var', 'function', 'export', 'default', 'new', 'await',
  'async', 'type', 'interface', 'extends', 'implements', 'public', 'private',
]);

type Tok = { text: string; cls: string | null };

function tokenizeLine(line: string): Tok[] {
  const toks: Tok[] = [];
  let i = 0;
  const n = line.length;
  while (i < n) {
    const ch = line[i];
    // comments
    if (ch === '#' || (ch === '/' && line[i + 1] === '/')) {
      toks.push({ text: line.slice(i), cls: 'tk-comment' });
      break;
    }
    // strings
    if (ch === '"' || ch === "'" || ch === '`') {
      let j = i + 1;
      while (j < n && line[j] !== ch) {
        if (line[j] === '\\') j++;
        j++;
      }
      toks.push({ text: line.slice(i, Math.min(j + 1, n)), cls: 'tk-string' });
      i = j + 1;
      continue;
    }
    // identifiers / keywords
    if (/[A-Za-z_]/.test(ch)) {
      let j = i + 1;
      while (j < n && /[A-Za-z0-9_]/.test(line[j])) j++;
      const word = line.slice(i, j);
      toks.push({ text: word, cls: KEYWORDS.has(word) ? 'tk-keyword' : null });
      i = j;
      continue;
    }
    // numbers
    if (/[0-9]/.test(ch)) {
      let j = i + 1;
      while (j < n && /[0-9.]/.test(line[j])) j++;
      toks.push({ text: line.slice(i, j), cls: 'tk-number' });
      i = j;
      continue;
    }
    toks.push({ text: ch, cls: null });
    i++;
  }
  return toks;
}

export function Highlighted({
  code,
  focusLine,
  makeLineLink,
}: {
  code: string;
  // 1-based line to scroll to and highlight (e.g. from a state link).
  focusLine?: number | null;
  // when provided, each line number becomes a draggable chat reference.
  makeLineLink?: (lineNo: number) => ChatLink;
}) {
  const lines = code.replace(/\n$/, '').split('\n');

  return (
    <pre className="code-block">
      <code>
        {lines.map((line, idx) => {
          const no = idx + 1;
          const isFocus = focusLine === no;
          return (
            <div
              className={`code-line${isFocus ? ' focus' : ''}`}
              key={isFocus ? `focus-${no}` : idx}
              ref={isFocus ? scrollFocusIntoView : undefined}
            >
              <span
                className={`code-gutter${makeLineLink ? ' line-handle' : ''}`}
                title={makeLineLink ? 'Drag this line to chat' : undefined}
                {...(makeLineLink ? dragProps(makeLineLink(no)) : {})}
              >
                {no}
              </span>
              <span className="code-text">
                {tokenizeLine(line).map((t, k) =>
                  t.cls ? (
                    <span className={t.cls} key={k}>{t.text}</span>
                  ) : (
                    <React.Fragment key={k}>{t.text}</React.Fragment>
                  ),
                )}
              </span>
            </div>
          );
        })}
      </code>
    </pre>
  );
}
