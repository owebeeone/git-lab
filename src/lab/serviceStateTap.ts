import { createAsyncStreamMultiTap, type Tap } from '@owebeeone/grip-react';
import { SERVICE_CONNECTION, type ServiceConnectionState } from './grips.service';
import { defaultServiceClient, type ServiceClient } from './serviceClient/client.ts';

type ServiceStateOuts = {
  connection: typeof SERVICE_CONNECTION;
};

export function createServiceStateTap(client: ServiceClient = defaultServiceClient): Tap {
  return createAsyncStreamMultiTap<ServiceStateOuts, ServiceConnectionState>({
    provides: [SERVICE_CONNECTION],
    requestKeyOf: () => 'service-connection',
    subscribe: (_params, signal) => client.watchStatus(signal),
    mapEvent: (_params, event) => new Map([[SERVICE_CONNECTION, event]]),
    initialState: [[SERVICE_CONNECTION, client.status]],
    cacheLatest: true,
  }) as unknown as Tap;
}
