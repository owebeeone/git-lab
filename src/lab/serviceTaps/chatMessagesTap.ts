import { createAsyncStreamMultiTap, type Tap } from '@owebeeone/grip-react';
import { CHAT_MESSAGES } from '../grips';
import { defaultServiceClient, type ServiceClient } from '../serviceClient/client.ts';
import type { ServiceStreamEvent } from '../serviceClient/protocol.ts';
import type { ChatMessage } from '../types';

interface ChatMessagesPayload {
  messages: ChatMessage[];
}

type ChatMessagesOuts = {
  messages: typeof CHAT_MESSAGES;
};

export function createServiceChatMessagesTap(client: ServiceClient = defaultServiceClient): Tap {
  return createAsyncStreamMultiTap<ChatMessagesOuts, ServiceStreamEvent>({
    provides: [CHAT_MESSAGES],
    requestKeyOf: () => 'chat.subscribe',
    subscribe: (_params, signal) => client.subscribe('chat.subscribe', {}, signal),
    mapEvent: (_params, event) => {
      const payload = event.payload as unknown as ChatMessagesPayload;
      return new Map([[CHAT_MESSAGES, payload.messages ?? []]]);
    },
    initialState: [[CHAT_MESSAGES, []]],
  }) as unknown as Tap;
}
