import type { VisualizerEvent } from './manifest';

interface WSClientOptions {
  url: string;
  onEvent: (event: VisualizerEvent) => void;
  onConnect?: () => void;
  onDisconnect?: () => void;
}

export class VisualizerWSClient {
  private ws: WebSocket | null = null;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private reconnectDelay = 1000;
  private stopped = false;
  private wasConnected = false;
  private options: WSClientOptions;

  constructor(options: WSClientOptions) {
    this.options = options;
  }

  connect(): void {
    this.stopped = false;
    this._connect();
  }

  disconnect(): void {
    this.stopped = true;
    if (this.reconnectTimer) clearTimeout(this.reconnectTimer);
    this.ws?.close();
    this.ws = null;
  }

  private _connect(): void {
    if (this.stopped) return;
    try {
      this.ws = new WebSocket(this.options.url);
      this.ws.onopen = () => {
        this.reconnectDelay = 1000; // reset backoff
        this.wasConnected = true;
        this.options.onConnect?.();
      };
      this.ws.onmessage = (evt) => {
        try {
          const payload = JSON.parse(evt.data as string) as VisualizerEvent;
          this.options.onEvent(payload);
        } catch {
          console.warn('[wsClient] Failed to parse message', evt.data);
        }
      };
      this.ws.onclose = () => {
        // Only notify disconnect if we had a successful connection before
        if (this.wasConnected) {
          this.wasConnected = false;
          this.options.onDisconnect?.();
        }
        if (!this.stopped) {
          // Exponential backoff, max 10s
          this.reconnectTimer = setTimeout(() => this._connect(), this.reconnectDelay);
          this.reconnectDelay = Math.min(this.reconnectDelay * 2, 10_000);
        }
      };
      this.ws.onerror = () => {
        this.ws?.close();
      };
    } catch {
      if (!this.stopped) {
        this.reconnectTimer = setTimeout(() => this._connect(), this.reconnectDelay);
      }
    }
  }
}
