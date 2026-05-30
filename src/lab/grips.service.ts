import type { AtomTapHandle } from '@owebeeone/grip-react';
import { defineGrip } from '../runtime';
import type { DiffDiagnostic, DiffHunk } from './serviceClient/diff';
import type { DiffStreamStatus } from './types';

export type ServiceConnectionStatus = 'disconnected' | 'connecting' | 'connected' | 'reconnecting' | 'error';

export interface ServiceConnectionState {
  status: ServiceConnectionStatus;
  url: string | null;
  error: string | null;
}

export const SERVICE_CONNECTION = defineGrip<ServiceConnectionState>('Lab.Service.Connection', {
  status: 'disconnected',
  url: null,
  error: null,
});

export const SERVICE_CONNECTION_TAP = defineGrip<AtomTapHandle<ServiceConnectionState>>('Lab.Service.Connection.Tap');

export const DIFF_HUNKS = defineGrip<DiffHunk[]>('Lab.Service.DiffHunks', []);
export const DIFF_DIAGNOSTICS = defineGrip<DiffDiagnostic[]>('Lab.Service.DiffDiagnostics', []);
export const DIFF_STREAM_STATUS = defineGrip<DiffStreamStatus>('Lab.Service.DiffStreamStatus', { status: 'idle', error: null });
export const DIFF_VERSION = defineGrip<string>('Lab.Service.DiffVersion', '');
