import { Terminal } from '@xterm/xterm';
import { FitAddon } from '@xterm/addon-fit';
import { SearchAddon } from '@xterm/addon-search';
import '@xterm/xterm/css/xterm.css';

// Imperative xterm.js wrapper kept out of React. A component mounts a terminal
// via a ref callback (React 19 cleanup) — no useState/useEffect/useRef.

const DARK = { background: '#16171a', foreground: '#e6e6e6', cursor: '#8ab4ff' };
const LIGHT = { background: '#ffffff', foreground: '#1c1e21', cursor: '#1a56db' };

export interface TermHandle {
  dispose(): void;
  update(opts: {
    content?: string;
    interactive?: boolean;
    dark?: boolean;
    onData?: (data: string) => void;
    onResize?: (cols: number, rows: number) => void;
  }): void;
  search(query: string): void;
}

export function createTerminal(
  el: HTMLElement,
  opts: {
    content?: string;
    interactive?: boolean;
    dark?: boolean;
    onData?: (data: string) => void;
    onResize?: (cols: number, rows: number) => void;
  },
): TermHandle {
  let content = opts.content ?? '';
  let interactive = !!opts.interactive;
  let boundInteractive = interactive;
  let boundOnData = opts.onData;
  let onDataDispose: { dispose(): void } | undefined;
  const term = new Terminal({
    convertEol: true,
    fontSize: 12,
    fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace',
    disableStdin: !interactive,
    cursorBlink: interactive,
    scrollback: 5000,
    theme: opts.dark === false ? LIGHT : DARK,
  });
  const fit = new FitAddon();
  const search = new SearchAddon();
  term.loadAddon(fit);
  term.loadAddon(search);
  term.open(el);
  const safeFit = () => {
    try {
      fit.fit();
      opts.onResize?.(term.cols, term.rows);
    } catch { /* not laid out yet */ }
  };
  safeFit();

  const ro = new ResizeObserver(safeFit);
  ro.observe(el);

  if (content) term.write(content);

  const bindInput = (nextInteractive?: boolean, nextOnData?: (data: string) => void) => {
    if (!!nextInteractive === boundInteractive && nextOnData === boundOnData) return;
    boundInteractive = !!nextInteractive;
    boundOnData = nextOnData;
    onDataDispose?.dispose();
    onDataDispose = undefined;
    interactive = !!nextInteractive;
    term.options.disableStdin = !interactive;
    term.options.cursorBlink = interactive;
    if (!interactive) return;
    if (nextOnData) {
      onDataDispose = term.onData(nextOnData);
      return;
    }
    term.write('\u001b[2m# mock interactive session — type to echo\u001b[0m\r\n$ ');
    onDataDispose = term.onData((d) => {
      if (d === '\r') term.write('\r\n$ ');
      else if (d === '\u007f') term.write('\b \b'); // backspace
      else term.write(d);
    });
  };

  if (interactive) {
    if (opts.onData) {
      onDataDispose = term.onData(opts.onData);
    } else {
      term.write('\u001b[2m# mock interactive session — type to echo\u001b[0m\r\n$ ');
      onDataDispose = term.onData((d) => {
        if (d === '\r') term.write('\r\n$ ');
        else if (d === '\u007f') term.write('\b \b'); // backspace
        else term.write(d);
      });
    }
  }

  return {
    dispose() {
      onDataDispose?.dispose();
      ro.disconnect();
      term.dispose();
    },
    update(next) {
      opts.onResize = next.onResize;
      term.options.theme = next.dark === false ? LIGHT : DARK;
      if ((next.content ?? '') !== content) {
        const nextContent = next.content ?? '';
        if (nextContent.startsWith(content)) {
          term.write(nextContent.slice(content.length));
        } else {
          term.clear();
          if (nextContent) term.write(nextContent);
        }
        content = nextContent;
      }
      bindInput(next.interactive, next.onData);
      safeFit();
    },
    search(query: string) {
      try {
        if (query) search.findNext(query);
        else search.clearDecorations();
      } catch { /* addon edge cases */ }
    },
  };
}
