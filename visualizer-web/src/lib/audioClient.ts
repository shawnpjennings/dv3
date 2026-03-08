/**
 * Browser-based audio I/O for DV3.
 *
 * Captures mic audio via Web Audio API, resamples to 16 kHz mono PCM int16,
 * and streams it to the backend over the existing WebSocket connection.
 *
 * Also plays incoming TTS audio (PCM int16) from the backend.
 * Gemini native audio models output at 24 kHz; mic input is 16 kHz.
 */

const MIC_SAMPLE_RATE = 16000;
const PLAYBACK_SAMPLE_RATE = 24000; // Gemini native audio output rate
const CHUNK_DURATION_MS = 80; // 80ms chunks = 1280 samples at 16 kHz
const CHUNK_SIZE = (MIC_SAMPLE_RATE * CHUNK_DURATION_MS) / 1000; // 1280

export class AudioClient {
  private mediaStream: MediaStream | null = null;
  private audioContext: AudioContext | null = null;
  private workletNode: AudioWorkletNode | null = null;
  private sourceNode: MediaStreamAudioSourceNode | null = null;
  private silentGain: GainNode | null = null;
  private sendBinary: ((data: ArrayBuffer) => void) | null = null;

  // Playback
  private playbackCtx: AudioContext | null = null;
  private nextPlayTime = 0;
  private isCapturing = false;
  private _isSpeaking = false;

  /**
   * Start capturing mic audio.
   * @param sendBinary  Callback to send binary data over WS.
   */
  async startCapture(sendBinary: (data: ArrayBuffer) => void): Promise<void> {
    if (this.isCapturing) return;
    this.sendBinary = sendBinary;

    try {
      this.mediaStream = await navigator.mediaDevices.getUserMedia({
        audio: {
          echoCancellation: true,
          noiseSuppression: true,
          sampleRate: MIC_SAMPLE_RATE,
        },
      });
    } catch (err) {
      console.error('[audioClient] Mic access denied:', err);
      throw err;
    }

    // Create AudioContext at target sample rate if browser supports it,
    // otherwise we'll resample in the worklet.
    this.audioContext = new AudioContext({ sampleRate: MIC_SAMPLE_RATE });

    // Register worklet processor inline via blob URL
    const workletCode = `
      class PcmChunkProcessor extends AudioWorkletProcessor {
        constructor() {
          super();
          this._buffer = new Float32Array(0);
          this._chunkSize = ${CHUNK_SIZE};
        }
        process(inputs) {
          const input = inputs[0];
          if (!input || !input[0]) return true;
          const channel = input[0];

          // Append to buffer
          const newBuf = new Float32Array(this._buffer.length + channel.length);
          newBuf.set(this._buffer);
          newBuf.set(channel, this._buffer.length);
          this._buffer = newBuf;

          // Emit full chunks
          while (this._buffer.length >= this._chunkSize) {
            const chunk = this._buffer.slice(0, this._chunkSize);
            this._buffer = this._buffer.slice(this._chunkSize);

            // Convert float32 [-1,1] to int16
            const int16 = new Int16Array(chunk.length);
            for (let i = 0; i < chunk.length; i++) {
              const s = Math.max(-1, Math.min(1, chunk[i]));
              int16[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
            }
            this.port.postMessage(int16.buffer, [int16.buffer]);
          }
          return true;
        }
      }
      registerProcessor('pcm-chunk-processor', PcmChunkProcessor);
    `;
    const blob = new Blob([workletCode], { type: 'application/javascript' });
    const workletUrl = URL.createObjectURL(blob);

    await this.audioContext.audioWorklet.addModule(workletUrl);
    URL.revokeObjectURL(workletUrl);

    this.sourceNode = this.audioContext.createMediaStreamSource(this.mediaStream);
    this.workletNode = new AudioWorkletNode(this.audioContext, 'pcm-chunk-processor');

    this.workletNode.port.onmessage = (e: MessageEvent) => {
      if (this.sendBinary) {
        this.sendBinary(e.data as ArrayBuffer);
      }
    };

    this.sourceNode.connect(this.workletNode);
    // Connect worklet to destination via a zero-gain node.  The worklet
    // must be part of the active audio graph for process() to fire, but
    // we don't want to hear our own mic audio (echo).
    this.silentGain = this.audioContext.createGain();
    this.silentGain.gain.value = 0;
    this.workletNode.connect(this.silentGain);
    this.silentGain.connect(this.audioContext.destination);

    this.isCapturing = true;
    console.log('[audioClient] Mic capture started (16 kHz, mono, int16)');
  }

  /** Stop capturing mic audio. */
  stopCapture(): void {
    if (this.silentGain) {
      this.silentGain.disconnect();
      this.silentGain = null;
    }
    if (this.workletNode) {
      this.workletNode.disconnect();
      this.workletNode = null;
    }
    if (this.sourceNode) {
      this.sourceNode.disconnect();
      this.sourceNode = null;
    }
    if (this.audioContext) {
      this.audioContext.close();
      this.audioContext = null;
    }
    if (this.mediaStream) {
      this.mediaStream.getTracks().forEach((t) => t.stop());
      this.mediaStream = null;
    }
    this.isCapturing = false;
    this.sendBinary = null;
    console.log('[audioClient] Mic capture stopped');
  }

  /**
   * Play incoming TTS audio from the backend.
   * @param pcmInt16 Raw PCM int16 bytes, 24 kHz mono (Gemini native audio output).
   *
   * Creates the playback AudioContext at the browser's default rate (usually
   * 48 kHz) and tags each AudioBuffer at 24 kHz.  The Web Audio API
   * automatically resamples 24→48 kHz during playback.
   */
  playAudio(pcmInt16: ArrayBuffer): void {
    if (!this.playbackCtx) {
      // Use default browser sample rate (typically 48 kHz) — Web Audio API
      // will resample the 24 kHz buffer automatically.
      this.playbackCtx = new AudioContext();
    }

    const int16View = new Int16Array(pcmInt16);
    const float32 = new Float32Array(int16View.length);
    for (let i = 0; i < int16View.length; i++) {
      float32[i] = int16View[i] / 32768;
    }

    // Tag buffer at source rate (24 kHz) — context resamples to output rate
    const buffer = this.playbackCtx.createBuffer(1, float32.length, PLAYBACK_SAMPLE_RATE);
    buffer.getChannelData(0).set(float32);

    const source = this.playbackCtx.createBufferSource();
    source.buffer = buffer;
    source.connect(this.playbackCtx.destination);

    const now = this.playbackCtx.currentTime;
    // If schedule has drifted more than 500ms behind real-time, reset
    // to prevent accumulating delay across turns.
    if (this.nextPlayTime < now - 0.5) {
      this.nextPlayTime = now;
    }
    const startTime = Math.max(now, this.nextPlayTime);
    source.start(startTime);
    this.nextPlayTime = startTime + buffer.duration;

    // Track speaking state for mic suppression
    this._isSpeaking = true;
    source.onended = () => {
      if (this.playbackCtx && this.playbackCtx.currentTime >= this.nextPlayTime - 0.01) {
        this._isSpeaking = false;
      }
    };
  }

  /** Reset playback scheduling (call when conversation ends). */
  resetPlayback(): void {
    this.nextPlayTime = 0;
  }

  get capturing(): boolean {
    return this.isCapturing;
  }

  /** True while TTS audio is playing through speakers. */
  get speaking(): boolean {
    return this._isSpeaking;
  }
}
