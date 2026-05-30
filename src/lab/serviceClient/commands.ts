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
