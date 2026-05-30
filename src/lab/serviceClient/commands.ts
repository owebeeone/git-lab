import { defaultServiceClient, type ServiceClient } from './client.ts';

export async function runServiceCommand(
  argv: string[],
  repos: string[],
  peerId: string,
  client: ServiceClient = defaultServiceClient,
): Promise<string> {
  const response = await client.request('cmd.run', { argv, repos, peerId });
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
  const response = await client.request('term.open', { repoPath, peerId, cols, rows });
  const sessionId = response.payload.sessionId;
  if (typeof sessionId !== 'string') throw new Error('term.open response missing sessionId');
  return sessionId;
}

export async function sendServiceTerminalInput(
  sessionId: string,
  data: string,
  client: ServiceClient = defaultServiceClient,
): Promise<boolean> {
  const response = await client.request('term.input', { sessionId, data });
  return response.payload.written === true;
}

export async function resizeServiceTerminal(
  sessionId: string,
  cols: number,
  rows: number,
  client: ServiceClient = defaultServiceClient,
): Promise<boolean> {
  const response = await client.request('term.resize', { sessionId, cols, rows });
  return response.payload.resized === true;
}
