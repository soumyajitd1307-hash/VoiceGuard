/**
 * Backend 1 — audio uplink WebSocket (Milestone 2).
 *
 * Channel separation (architectural rule):
 *   AUDIO (this file):  frontend -> VITE_AUDIO_WS_URL -> Backend 1 (:8001)
 *   RISK (elsewhere):   Backend 4 -> VITE_WS_URL -> services/websocket.ts
 *
 * This module never imports services/websocket.ts, CallContext, or types.
 * It sends ONLY binary PCM frames and only reads Backend 1 ACK frames:
 *   {"type": "ack", "seq": N}
 * ACKs are counted/logged for development; they are never converted into
 * risk updates and never forwarded anywhere.
 */

export const DEFAULT_AUDIO_WS_URL = 'ws://localhost:8001/ws/audio';

function resolveBaseUrl(): string {
  const fromEnv =
    typeof import.meta !== 'undefined'
      ? (import.meta.env?.VITE_AUDIO_WS_URL as string | undefined)
      : undefined;
  return (fromEnv ?? DEFAULT_AUDIO_WS_URL).replace(/\/+$/, '');
}

export interface AudioStreamStats {
  connected: boolean;
  sessionId: string | null;
  framesSent: number;
  bytesSent: number;
  /** Frames dropped because the socket was not OPEN (never throws). */
  droppedFrames: number;
  ackCount: number;
  lastAckSeq: number | null;
}

export class AudioStreamService {
  private socket: WebSocket | null = null;
  private sessionId: string | null = null;
  private connectPromise: Promise<void> | null = null;

  private framesSent = 0;
  private bytesSent = 0;
  private droppedFrames = 0;
  private ackCount = 0;
  private lastAckSeq: number | null = null;

  public isConnected(): boolean {
    return this.socket !== null && this.socket.readyState === WebSocket.OPEN;
  }

  public getStats(): AudioStreamStats {
    return {
      connected: this.isConnected(),
      sessionId: this.sessionId,
      framesSent: this.framesSent,
      bytesSent: this.bytesSent,
      droppedFrames: this.droppedFrames,
      ackCount: this.ackCount,
      lastAckSeq: this.lastAckSeq,
    };
  }

  public connect(sessionId: string): Promise<void> {
    if (!sessionId) {
      return Promise.reject(
        new Error('audioStream: sessionId is required'),
      );
    }
    if (this.socket) {
      if (this.sessionId === sessionId && this.connectPromise) {
        return this.connectPromise; // idempotent reconnect to same session
      }
      throw new Error(
        'audioStream: already connected — call disconnect() first',
      );
    }

    const url = `${resolveBaseUrl()}?session_id=${encodeURIComponent(sessionId)}`;
    this.sessionId = sessionId;

    this.connectPromise = new Promise<void>((resolve, reject) => {
      let settled = false;
      const timer = window.setTimeout(() => {
        if (!settled) {
          settled = true;
          try {
            this.socket?.close();
          } catch {
            // ignore
          }
          this.socket = null;
          this.connectPromise = null;
          reject(
            new Error(`audioStream: connection timeout (${url}) — is Backend 1 running on :8001?`),
          );
        }
      }, 10000);

      let socket: WebSocket;
      try {
        socket = new WebSocket(url);
      } catch (err) {
        window.clearTimeout(timer);
        this.socket = null;
        this.connectPromise = null;
        reject(
          err instanceof Error
            ? err
            : new Error('audioStream: failed to create WebSocket'),
        );
        return;
      }
      this.socket = socket;

      socket.binaryType = 'arraybuffer';

      socket.onopen = () => {
        if (settled) return;
        settled = true;
        window.clearTimeout(timer);
        // Fresh session: reset cumulative counters so diagnostics describe
        // THIS connection (sessionId already updated above), not history.
        this.framesSent = 0;
        this.bytesSent = 0;
        this.droppedFrames = 0;
        this.ackCount = 0;
        this.lastAckSeq = null;
        if (import.meta.env.DEV) {
          // eslint-disable-next-line no-console
          console.info(`[audioStream] connected: session_id=${sessionId}`);
        }
        resolve();
      };

      socket.onerror = () => {
        if (settled) {
          if (import.meta.env.DEV) {
            // eslint-disable-next-line no-console
            console.warn('[audioStream] socket error (after connect)');
          }
          return;
        }
        settled = true;
        window.clearTimeout(timer);
        this.socket = null;
        this.connectPromise = null;
        reject(
          new Error(
            `audioStream: connection failed (${url}) — is Backend 1 running on :8001?`,
          ),
        );
      };

      socket.onclose = () => {
        if (import.meta.env.DEV) {
          // eslint-disable-next-line no-console
          console.info(
            `[audioStream] closed: session_id=${this.sessionId} ` +
              `sent=${this.framesSent} acked=${this.ackCount} dropped=${this.droppedFrames}`,
          );
        }
        if (!settled) {
          settled = true;
          window.clearTimeout(timer);
          this.socket = null;
          this.connectPromise = null;
          reject(new Error('audioStream: connection closed before open'));
          return;
        }
        this.socket = null;
        this.connectPromise = null;
      };

      socket.onmessage = (event: MessageEvent) => {
        this.handleMessage(event.data);
      };
    });

    return this.connectPromise;
  }

  /**
   * Backend 1 ACK handler. Counts + dev-logs only. Deliberately knows
   * nothing about RiskUpdate/CallContext — ACKs must never become UI state.
   */
  private handleMessage(data: unknown): void {
    if (typeof data !== 'string') {
      return; // Backend 1 only sends JSON text ACKs; ignore anything else
    }
    try {
      const msg = JSON.parse(data) as { type?: unknown; seq?: unknown };
      if (msg.type === 'ack' && typeof msg.seq === 'number') {
        this.ackCount += 1;
        this.lastAckSeq = msg.seq;
        if (import.meta.env.DEV) {
          // eslint-disable-next-line no-console
          console.debug(`[audioStream] ack seq=${msg.seq}`);
        }
      } else if (import.meta.env.DEV) {
        // eslint-disable-next-line no-console
        console.debug('[audioStream] non-ack message ignored', msg);
      }
    } catch {
      // Malformed frame: ignore, never crash the app.
    }
  }

  /**
   * Send one PCM frame as a binary WebSocket message.
   * Drops (and counts) when not OPEN instead of throwing, so a transient
   * reconnect never crashes the capture loop.
   */
  public sendAudio(chunk: ArrayBuffer): void {
    if (this.isConnected() && this.socket) {
      try {
        this.socket.send(chunk);
        this.framesSent += 1;
        this.bytesSent += chunk.byteLength;
      } catch {
        this.droppedFrames += 1;
      }
      return;
    }
    this.droppedFrames += 1;
    if (import.meta.env.DEV) {
      // eslint-disable-next-line no-console
      console.warn(
        `[audioStream] dropped frame (${chunk.byteLength} bytes): socket not open`,
      );
    }
  }

  public disconnect(): void {
    // Idempotent: safe to call when never connected or already closed.
    const socket = this.socket;
    this.socket = null;
    this.connectPromise = null;
    this.sessionId = null;
    if (socket) {
      try {
        if (
          socket.readyState === WebSocket.OPEN ||
          socket.readyState === WebSocket.CONNECTING
        ) {
          socket.close(1000, 'client disconnect');
        }
      } catch {
        // ignore teardown errors
      }
    }
  }
}

export const audioStream = new AudioStreamService();
