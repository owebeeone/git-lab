import { defaultServiceClient, type ServiceClient } from './client.ts';
import { LAB_HUB_ROUTE } from '../dataMode';

export async function runServiceCommand(
  argv: string[],
  repos: string[],
  peerId: string,
  client: ServiceClient = defaultServiceClient,
): Promise<string> {
  const payload = { argv, repos, peerId };
  const response = LAB_HUB_ROUTE
    ? await client.routeRequest(peerId, 'cmd.run', payload)
    : await client.request('cmd.run', payload);
  const sessionId = response.payload.sessionId;
  if (typeof sessionId !== 'string') throw new Error('cmd.run response missing sessionId');
  return sessionId;
}

export async function openServiceTerminal(
  repoPath: string,
  peerId: string,
  cols = 120,
  rows = 30,
  client: ServiceClient = defaultServiceClient,
): Promise<string> {
  const payload = { repoPath, peerId, cols, rows };
  const response = LAB_HUB_ROUTE
    ? await client.routeRequest(peerId, 'term.open', payload)
    : await client.request('term.open', payload);
  const sessionId = response.payload.sessionId;
  if (typeof sessionId !== 'string') throw new Error('term.open response missing sessionId');
  return sessionId;
}

export async function sendServiceTerminalInput(
  sessionId: string,
  data: string,
  peerId: string,
  client: ServiceClient = defaultServiceClient,
): Promise<boolean> {
  const payload = { sessionId, data };
  const response = LAB_HUB_ROUTE
    ? await client.routeRequest(peerId, 'term.input', payload)
    : await client.request('term.input', payload);
  return response.payload.written === true;
}

export async function resizeServiceTerminal(
  sessionId: string,
  cols: number,
  rows: number,
  peerId: string,
  client: ServiceClient = defaultServiceClient,
): Promise<boolean> {
  const payload = { sessionId, cols, rows };
  const response = LAB_HUB_ROUTE
    ? await client.routeRequest(peerId, 'term.resize', payload)
    : await client.request('term.resize', payload);
  return response.payload.resized === true;
}
