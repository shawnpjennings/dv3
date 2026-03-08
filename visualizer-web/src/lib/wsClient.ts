import type { VisualizerEvent } from './manifest';

interface WSClientOptions {
  url: string;
  onEvent: (event: VisualizerEvent) => void;
  onAudio?: (pcmInt16: ArrayBuffer) => void;
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

  /** Send raw binary data (mic audio) to the backend. */
  sendBinary(data: ArrayBuffer): void {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(data);
    }
  }

  get connected(): boolean {
    return this.ws?.readyState === WebSocket.OPEN;
  }

  private _connect(): void {
    if (this.stopped) return;
    try {
      this.ws = new WebSocket(this.options.url);
      this.ws.binaryType = 'arraybuffer';

      this.ws.onopen = () => {
        this.reconnectDelay = 1000; // reset backoff
        this.wasConnected = true;
        this.options.onConnect?.();
      };

      this.ws.onmessage = (evt) => {
        if (evt.data instanceof ArrayBuffer) {
          // Binary message — TTS audio from backend
          // First byte is message type: 0x01 = audio
          const view = new Uint8Array(evt.data);
          if (view.length > 1 && view[0] === 0x01) {
            // Strip the 1-byte header, pass PCM int16 to audio handler
            const pcm = evt.data.slice(1);
            this.options.onAudio?.(pcm);
          }
          return;
        }

        // Text message — JSON event
        try {
          const payload = JSON.parse(evt.data as string) as VisualizerEvent;
          this.options.onEvent(payload);
        } catch {
          console.warn('[wsClient] Failed to parse message', evt.data);
        }
      };

      this.ws.onclose = () => {
        if (this.wasConnected) {
          this.wasConnected = false;
          this.options.onDisconnect?.();
        }
        if (!this.stopped) {
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
