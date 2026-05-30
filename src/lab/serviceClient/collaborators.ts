import { defaultServiceClient, type ServiceClient } from './client.ts';
import { parsePeerHealth, type PeerHealth } from './protocol.ts';
import type { Peer } from '../types';

export interface CollaboratorUpsertRequest {
  peerId: string;
  name: string;
  sshAddress: string;
  location: string;
}

export async function upsertServiceCollaborator(
  request: CollaboratorUpsertRequest,
  client: ServiceClient = defaultServiceClient,
): Promise<void> {
  await client.request('peer.collaborator.upsert', { ...request });
}

export async function removeServiceCollaborator(
  peerId: string,
  client: ServiceClient = defaultServiceClient,
): Promise<void> {
  await client.request('peer.collaborator.remove', { peerId });
}

export async function getServicePeerHealth(
  peerId: string,
  client: ServiceClient = defaultServiceClient,
): Promise<PeerHealth> {
  const response = await client.request('peer.health.get', { peerId });
  return parsePeerHealth(response.payload.health);
}

export function peerIdForCollaborator(name: string, sshAddress: string, location: string, peers: Peer[]): string {
  const seed = name.trim() || `${sshAddress}-${location}`;
  const base = seed.toLowerCase().replace(/[^a-z0-9_-]+/g, '-').replace(/^-+|-+$/g, '') || 'peer';
  if (!peers.some((peer) => peer.id === base)) return base;
  let index = 2;
  while (peers.some((peer) => peer.id === `${base}-${index}`)) index += 1;
  return `${base}-${index}`;
}
