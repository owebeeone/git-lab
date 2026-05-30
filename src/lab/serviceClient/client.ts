import type { ServiceConnectionState } from '../grips.service';
import {
  parseServiceEnvelope,
  parseServiceStreamEvent,
  type ServiceEnvelope,
  type ServiceStreamEvent,
} from './protocol.ts';
import { WebSocketServiceTransport, type ServiceTransport } from './transport.ts';

export interface ServiceClientOptions {
  url: string;
  httpUrl?: string;
  transportFactory?: (url: string) => ServiceTransport;
  reconnectDelayMs?: number;
  maxReconnectDelayMs?: number;
}

type StatusListener = (state: ServiceConnectionState) => void;

export class ServiceClient {
  private readonly options: ServiceClientOptions;
  private readonly transport: ServiceTransport;
  private messageIndex = 0;
  private streamIndex = 0;
  private reader: Promise<void> | null = null;
  private readonly pending = new Map<string, {
    resolve: (value: ServiceEnvelope) => void;
    reject: (error: Error) => void;
  }>();
  private readonly streams = new Map<string, {
    queue: ServiceStreamEvent[];
    waiters: Array<(value: IteratorResult<ServiceStreamEvent>) => void>;
  }>();
  private readonly streamRequestIds = new Map<string, string>();
  private readonly statusListeners = new Set<StatusListener>();
  private currentStatus: ServiceConnectionState;
  private reconnecting = false;

  constructor(options: ServiceClientOptions) {
    this.options = options;
    this.transport = options.transportFactory?.(options.url) ?? new WebSocketServiceTransport(options.url);
    this.currentStatus = { status: 'disconnected', url: options.url, error: null };
  }

  get status(): ServiceConnectionState {
    return this.currentStatus;
  }

  get httpUrl(): string {
    return this.options.httpUrl ?? websocketUrlToHttpUrl(this.options.url);
  }

  nextMessageId(): string {
    this.messageIndex += 1;
    return `m${this.messageIndex.toString().padStart(6, '0')}`;
  }

  nextStreamId(): string {
    this.streamIndex += 1;
    return `s${this.streamIndex.toString().padStart(6, '0')}`;
  }

  async connect(signal?: AbortSignal): Promise<void> {
    if (this.currentStatus.status === 'connected' || this.currentStatus.status === 'connecting') {
      return;
    }
    this.setStatus({ status: 'connecting', url: this.options.url, error: null });
    try {
      await this.transport.connect(signal);
      this.setStatus({ status: 'connected', url: this.options.url, error: null });
      this.reader ??= this.readLoop(signal);
    } catch (error) {
      this.setStatus({ status: 'error', url: this.options.url, error: errorMessage(error) });
      throw error;
    }
  }

  close(): void {
    this.transport.close();
    this.reconnecting = false;
    this.setStatus({ status: 'disconnected', url: this.options.url, error: null });
  }

  async request(method: string, payload: Record<string, unknown> = {}, signal?: AbortSignal): Promise<ServiceEnvelope> {
    await this.connect(signal);
    const messageId = this.nextMessageId();
    const envelope = parseServiceEnvelope({ messageId, kind: 'request', method, payload });
    const result = new Promise<ServiceEnvelope>((resolve, reject) => {
      this.pending.set(messageId, { resolve, reject });
      signal?.addEventListener('abort', () => {
        this.pending.delete(messageId);
        reject(new Error('request aborted'));
      }, { once: true });
    });
    this.transport.send(envelope);
    return result;
  }

  async routeRequest(
    targetPeerId: string,
    method: string,
    payload: Record<string, unknown> = {},
    signal?: AbortSignal,
  ): Promise<ServiceEnvelope> {
    return this.request('hub.route.request', { targetPeerId, method, payload }, signal);
  }

  async getJson<T>(path: string, signal?: AbortSignal): Promise<T> {
    const response = await fetch(new URL(path, this.httpUrl), { signal });
    if (!response.ok) {
      throw new Error(`service http ${response.status}: ${response.statusText}`);
    }
    return await response.json() as T;
  }

  async *subscribe(method: string, payload: Record<string, unknown> = {}, signal?: AbortSignal): AsyncIterable<ServiceStreamEvent> {
    await this.connect(signal);
    const messageId = this.nextMessageId();
    const streamId = this.nextStreamId();
    this.streams.set(streamId, { queue: [], waiters: [] });
    this.streamRequestIds.set(messageId, streamId);
    this.transport.send(parseServiceEnvelope({ messageId, kind: 'request', method, streamId, payload }));
    try {
      while (!signal?.aborted) {
        const event = await this.nextStreamEvent(streamId, signal);
        if (event.done) return;
        if (event.value.event === 'error') {
          yield event.value;
          return;
        }
        yield event.value;
      }
    } finally {
      this.streams.delete(streamId);
      this.streamRequestIds.delete(messageId);
    }
  }

  routeSubscribe(
    targetPeerId: string,
    method: string,
    payload: Record<string, unknown> = {},
    signal?: AbortSignal,
  ): AsyncIterable<ServiceStreamEvent> {
    return this.subscribe('hub.route.subscribe', { targetPeerId, method, payload }, signal);
  }

  async *watchStatus(signal?: AbortSignal): AsyncIterable<ServiceConnectionState> {
    yield this.currentStatus;
    const queue: ServiceConnectionState[] = [];
    const waiters: Array<(value: IteratorResult<ServiceConnectionState>) => void> = [];
    const listener = (state: ServiceConnectionState) => {
      const waiter = waiters.shift();
      if (waiter) waiter({ done: false, value: state });
      else queue.push(state);
    };
    this.statusListeners.add(listener);
    try {
      while (!signal?.aborted) {
        const queued = queue.shift();
        if (queued) {
          yield queued;
          continue;
        }
        const next = await new Promise<IteratorResult<ServiceConnectionState>>((resolve) => {
          const abort = () => resolve({ done: true, value: undefined });
          signal?.addEventListener('abort', abort, { once: true });
          waiters.push((value) => {
            signal?.removeEventListener('abort', abort);
            resolve(value);
          });
        });
        if (next.done) return;
        yield next.value;
      }
    } finally {
      this.statusListeners.delete(listener);
    }
  }

  private async readLoop(signal?: AbortSignal): Promise<void> {
    try {
      for await (const message of this.transport.messages(signal)) {
        this.dispatch(parseServiceEnvelope(message));
      }
    } catch (error) {
      this.failAll(errorMessage(error));
      this.setStatus({ status: 'error', url: this.options.url, error: errorMessage(error) });
    } finally {
      this.reader = null;
      if (this.currentStatus.status === 'connected') {
        this.setStatus({ status: 'reconnecting', url: this.options.url, error: 'transport closed' });
        this.endAllStreams();
        void this.reconnectLoop(signal);
      }
    }
  }

  private async reconnectLoop(signal?: AbortSignal): Promise<void> {
    if (this.reconnecting) return;
    this.reconnecting = true;
    let delay = this.options.reconnectDelayMs ?? 250;
    const maxDelay = this.options.maxReconnectDelayMs ?? 4000;
    try {
      while (!signal?.aborted && this.currentStatus.status === 'reconnecting') {
        await sleep(delay, signal);
        if (signal?.aborted || this.currentStatus.status !== 'reconnecting') return;
        try {
          await this.transport.connect(signal);
          this.setStatus({ status: 'connected', url: this.options.url, error: null });
          this.reader ??= this.readLoop(signal);
          return;
        } catch (error) {
          const message = errorMessage(error);
          this.setStatus({ status: 'reconnecting', url: this.options.url, error: message });
          delay = Math.min(maxDelay, Math.round(delay * 1.8));
        }
      }
    } finally {
      this.reconnecting = false;
    }
  }

  private dispatch(message: ServiceEnvelope): void {
    if (message.kind === 'response' || message.kind === 'error') {
      const pending = this.pending.get(message.messageId);
      if (pending) {
        this.pending.delete(message.messageId);
        if (message.kind === 'error') pending.reject(new Error(message.error?.message ?? 'service error'));
        else pending.resolve(message);
        return;
      }
      if (message.kind === 'error') {
        const streamId = message.streamId ?? this.streamRequestIds.get(message.messageId);
        if (streamId) {
          this.enqueueStreamEvent(streamId, {
            streamId,
            seq: 0,
            event: 'error',
            payload: {
              code: message.error?.code ?? 'service-error',
              message: message.error?.message ?? 'service stream error',
              details: message.error?.details ?? {},
            },
          });
        }
      }
      return;
    }
    if (message.kind === 'stream-event' && message.streamId) {
      const event = parseServiceStreamEvent(message.payload);
      this.enqueueStreamEvent(message.streamId, event);
    }
  }

  private enqueueStreamEvent(streamId: string, event: ServiceStreamEvent): void {
    const stream = this.streams.get(streamId);
    if (!stream) return;
    const waiter = stream.waiters.shift();
    if (waiter) waiter({ done: false, value: event });
    else stream.queue.push(event);
  }

  private nextStreamEvent(streamId: string, signal?: AbortSignal): Promise<IteratorResult<ServiceStreamEvent>> {
    const stream = this.streams.get(streamId);
    if (!stream || signal?.aborted) return Promise.resolve({ done: true, value: undefined });
    const queued = stream.queue.shift();
    if (queued) return Promise.resolve({ done: false, value: queued });
    return new Promise((resolve) => {
      const abort = () => resolve({ done: true, value: undefined });
      signal?.addEventListener('abort', abort, { once: true });
      stream.waiters.push((value) => {
        signal?.removeEventListener('abort', abort);
        resolve(value);
      });
    });
  }

  private setStatus(state: ServiceConnectionState): void {
    this.currentStatus = state;
    for (const listener of this.statusListeners) listener(state);
  }

  private failAll(message: string): void {
    for (const pending of this.pending.values()) pending.reject(new Error(message));
    this.pending.clear();
  }

  private endAllStreams(): void {
    for (const stream of this.streams.values()) {
      for (const waiter of stream.waiters.splice(0)) {
        waiter({ done: true, value: undefined });
      }
    }
  }
}

function sleep(ms: number, signal?: AbortSignal): Promise<void> {
  if (signal?.aborted) return Promise.resolve();
  return new Promise((resolve) => {
    const timer = globalThis.setTimeout(resolve, ms);
    signal?.addEventListener('abort', () => {
      globalThis.clearTimeout(timer);
      resolve();
    }, { once: true });
  });
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function websocketUrlToHttpUrl(value: string): string {
  const url = new URL(value);
  url.protocol = url.protocol === 'wss:' ? 'https:' : 'http:';
  url.pathname = '/';
  url.search = '';
  url.hash = '';
  return url.toString();
}

const viteEnv = (import.meta as ImportMeta & { env?: { VITE_GL_SERVICE_URL?: string } }).env;
const serviceUrl = viteEnv?.VITE_GL_SERVICE_URL ?? 'ws://127.0.0.1:3141/ws';

export const defaultServiceClient = new ServiceClient({ url: serviceUrl });
