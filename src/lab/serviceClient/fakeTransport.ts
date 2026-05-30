import type { ServiceEnvelope } from './protocol.ts';
import type { ServiceTransport } from './transport.ts';

export class FakeServiceTransport implements ServiceTransport {
  readonly sent: ServiceEnvelope[] = [];
  private readonly queue: ServiceEnvelope[] = [];
  private waiters: Array<(value: IteratorResult<ServiceEnvelope>) => void> = [];
  private connected = false;
  private closed = false;

  async connect(): Promise<void> {
    this.connected = true;
    this.closed = false;
  }

  send(envelope: ServiceEnvelope): void {
    if (!this.connected) throw new Error('fake transport is not connected');
    this.sent.push(envelope);
  }

  push(envelope: ServiceEnvelope): void {
    const waiter = this.waiters.shift();
    if (waiter) waiter({ done: false, value: envelope });
    else this.queue.push(envelope);
  }

  close(): void {
    this.closed = true;
    for (const waiter of this.waiters.splice(0)) {
      waiter({ done: true, value: undefined });
    }
  }

  async *messages(signal?: AbortSignal): AsyncIterable<ServiceEnvelope> {
    while (!this.closed && !signal?.aborted) {
      const queued = this.queue.shift();
      if (queued) {
        yield queued;
        continue;
      }
      const next = await new Promise<IteratorResult<ServiceEnvelope>>((resolve) => {
        const abort = () => resolve({ done: true, value: undefined });
        signal?.addEventListener('abort', abort, { once: true });
        this.waiters.push((value) => {
          signal?.removeEventListener('abort', abort);
          resolve(value);
        });
      });
      if (next.done) return;
      yield next.value;
    }
  }
}
