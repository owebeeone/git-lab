import type { AtomTapHandle } from '@owebeeone/grip-react';
import { defineGrip } from '../runtime';

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
