import { parseServiceEnvelope, type ServiceEnvelope } from './protocol.ts';

export interface ServiceTransport {
  connect(signal?: AbortSignal): Promise<void>;
  send(envelope: ServiceEnvelope): void;
  close(): void;
  messages(signal?: AbortSignal): AsyncIterable<ServiceEnvelope>;
}

export class WebSocketServiceTransport implements ServiceTransport {
  private socket: WebSocket | null = null;
  private readonly queue: ServiceEnvelope[] = [];
  private waiters: Array<(value: IteratorResult<ServiceEnvelope>) => void> = [];
  private closed = false;
  private readonly url: string;

  constructor(url: string) {
    this.url = url;
  }

  connect(signal?: AbortSignal): Promise<void> {
    if (this.socket?.readyState === WebSocket.OPEN) return Promise.resolve();
    this.closed = false;
    const socket = new WebSocket(this.url);
    this.socket = socket;
    signal?.addEventListener('abort', () => socket.close(), { once: true });
    return new Promise((resolve, reject) => {
      socket.onopen = () => resolve();
      socket.onerror = () => reject(new Error('websocket connection failed'));
      socket.onmessage = (event) => {
        this.push(parseServiceEnvelope(JSON.parse(String(event.data))));
      };
      socket.onclose = () => {
        this.closed = true;
        this.flushDone();
      };
    });
  }

  send(envelope: ServiceEnvelope): void {
    if (!this.socket || this.socket.readyState !== WebSocket.OPEN) {
      throw new Error('service websocket is not connected');
    }
    this.socket.send(JSON.stringify(envelope));
  }

  close(): void {
    this.closed = true;
    this.socket?.close();
    this.flushDone();
  }

  async *messages(signal?: AbortSignal): AsyncIterable<ServiceEnvelope> {
    while (!this.closed && !signal?.aborted) {
      const next = await this.next(signal);
      if (next.done) return;
      yield next.value;
    }
  }

  private push(envelope: ServiceEnvelope): void {
    const waiter = this.waiters.shift();
    if (waiter) {
      waiter({ done: false, value: envelope });
    } else {
      this.queue.push(envelope);
    }
  }

  private next(signal?: AbortSignal): Promise<IteratorResult<ServiceEnvelope>> {
    const queued = this.queue.shift();
    if (queued) return Promise.resolve({ done: false, value: queued });
    if (this.closed || signal?.aborted) return Promise.resolve({ done: true, value: undefined });
    return new Promise((resolve) => {
      const abort = () => resolve({ done: true, value: undefined });
      signal?.addEventListener('abort', abort, { once: true });
      this.waiters.push((value) => {
        signal?.removeEventListener('abort', abort);
        resolve(value);
      });
    });
  }

  private flushDone(): void {
    for (const waiter of this.waiters.splice(0)) {
      waiter({ done: true, value: undefined });
    }
  }
}
