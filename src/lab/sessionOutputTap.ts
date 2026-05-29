import { createFunctionTap, type Tap } from '@owebeeone/grip-react';
import { grok } from '../runtime';
import { SESSIONS, SELECTED_SESSION, SELECTED_TARGET, SESSION_OUTPUT, SESSION_DIAGNOSTICS } from './grips';
import type { CommandSession, SessionDiagnostics } from './types';

// Strip ANSI escape codes for text-pattern diagnostics parsing.
// eslint-disable-next-line no-control-regex
const ANSI = /\u001b\[[0-9;]*m/g;

export function parseDiagnostics(output: string, exitCode: number | null): SessionDiagnostics {
  const text = output.replace(ANSI, '');
  const failed = [...text.matchAll(/^FAILED\s+(.+)$/gm)].map((m) => m[1].trim());
  const summary = text.match(/(\d+)\s+failed(?:,\s*(\d+)\s+passed)?/);
  const passedOnly = text.match(/(\d+)\s+passed/);
  if (failed.length || summary) {
    return {
      kind: 'pytest',
      failed: summary ? Number(summary[1]) : failed.length,
      passed: summary && summary[2] ? Number(summary[2]) : (passedOnly ? Number(passedOnly[1]) : 0),
      failures: failed,
    };
  }
  // Non-test failures still surface via exit code.
  if (exitCode != null && exitCode !== 0) {
    return { kind: 'none', failed: 1, passed: 0, failures: [] };
  }
  return { kind: 'none', failed: 0, passed: passedOnly ? Number(passedOnly[1]) : 0, failures: [] };
}

// Provides the selected session's output + parsed diagnostics. Reads the
// selection + session list as home params (the delta-protocol seam for the
// real per-executor log later).
export function registerSessionOutputTap() {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const tap = createFunctionTap<any, any, any, any>({
    provides: [SESSION_OUTPUT, SESSION_DIAGNOSTICS],
    homeParamGrips: [SELECTED_SESSION, SELECTED_TARGET, SESSIONS],
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    compute: ({ getHomeParam }: any) => {
      const id: string | null = getHomeParam(SELECTED_SESSION) ?? null;
      const targetRepo: string | null = getHomeParam(SELECTED_TARGET) ?? null;
      const sessions: CommandSession[] = getHomeParam(SESSIONS) ?? [];
      const session = sessions.find((s) => s.id === id);
      const target = session
        ? (session.targets.find((t) => t.repoPath === targetRepo) ?? session.targets[0])
        : undefined;
      const output = target?.output ?? '';
      const diagnostics = target
        ? parseDiagnostics(target.output, target.exitCode)
        : { kind: 'none' as const, failed: 0, passed: 0, failures: [] };
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      return new Map<any, any>([[SESSION_OUTPUT, output], [SESSION_DIAGNOSTICS, diagnostics]]);
    },
  });
  grok.registerTap(tap as unknown as Tap);
}
