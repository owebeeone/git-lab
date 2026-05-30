import { defaultServiceClient, type ServiceClient } from './client.ts';
import type { ProbeResult } from '../types';

export interface PeerProbeRequest {
  sshAddress: string;
  location: string;
}

export interface PeerProbeResult extends ProbeResult {
  ok: boolean;
  error?: string;
  workspace?: {
    root: string;
    exists: boolean;
  };
  git?: boolean;
}

export async function probeServicePeer(
  request: PeerProbeRequest,
  client: ServiceClient = defaultServiceClient,
): Promise<PeerProbeResult> {
  const response = await client.request('peer.probe', { ...request });
  return response.payload as unknown as PeerProbeResult;
}
