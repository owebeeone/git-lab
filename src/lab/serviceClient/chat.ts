import { defaultServiceClient, type ServiceClient } from './client.ts';
import type { ChatLink, ChatMessage } from '../types';

export async function postServiceChatMessage(
  input: { senderId: string; text: string; links: ChatLink[] },
  client: ServiceClient = defaultServiceClient,
): Promise<ChatMessage> {
  const response = await client.request('chat.post', input);
  const message = response.payload.message;
  if (!message || typeof message !== 'object') throw new Error('chat.post response missing message');
  return message as ChatMessage;
}
