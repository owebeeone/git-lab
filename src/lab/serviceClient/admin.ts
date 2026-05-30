import { LAB_HUB_ROUTE } from '../dataMode';
import { defaultServiceClient, type ServiceClient } from './client.ts';

export async function restartHub(client: ServiceClient = defaultServiceClient): Promise<void> {
  await client.request('admin.restart', {});
}

export async function restartLocalClient(client: ServiceClient = defaultServiceClient): Promise<void> {
  if (LAB_HUB_ROUTE) {
    await client.routeRequest('me', 'admin.restart', {});
  } else {
    await client.request('admin.restart', {});
  }
}
