/**
 * Two-person WebRTC signaling client (JSON envelopes only — no media).
 *
 * Channel (separate from audio ingest and risk sockets):
 *   frontend -> VITE_SIGNAL_WS_URL -> Backend 1 /ws/signal
 *     ?call_id=<CALL_ID>&participant_id=<PARTICIPANT_ID>
 *
 * SDP/ICE negotiation itself happens in RTCPeerConnection
 * (see webrtcCall.ts); this module only transports the envelopes.
 */

export const DEFAULT_SIGNAL_WS_URL = 'ws://localhost:8001/ws/signal';

function resolveBaseUrl(): string {
  const fromEnv =
    typeof import.meta !== 'undefined'
      ? (import.meta.env?.VITE_SIGNAL_WS_URL as string | undefined)
      : undefined;
  return (fromEnv ?? DEFAULT_SIGNAL_WS_URL).replace(/\/+$/, '');
}

export interface SignalPeer {
  participant_id: string;
  display_name: string;
}

export interface SignalHandlers {
  onJoined?: (peers: SignalPeer[]) => void;
  onPeerJoined?: (peer: SignalPeer) => void;
  onPeerLeft?: (participantId: string) => void;
  onOffer?: (from: string, sdp: RTCSessionDescriptionInit) => void;
  onAnswer?: (from: string, sdp: RTCSessionDescriptionInit) => void;
  onIce?: (from: string, candidate: RTCIceCandidateInit) => void;
  onErrorMessage?: (detail: string) => void;
  onClose?: () => void;
}

class WebRTCSignalingService {
  private socket: WebSocket | null = null;
  private connectPromise: Promise<void> | null = null;
  private handlers: SignalHandlers = {};
  private joinedResolve: (() => void) | null = null;
  private joinedReject: ((err: Error) => void) | null = null;

  public isConnected(): boolean {
    return this.socket !== null && this.socket.readyState === WebSocket.OPEN;
  }

  /**
   * Open the socket and join the call room. Resolves once the server
   * confirms with `joined` (including the current peer roster).
   */
  public connect(
    callId: string,
    participantId: string,
    displayName: string,
    handlers: SignalHandlers,
  ): Promise<void> {
    if (!callId || !participantId) {
      return Promise.reject(
        new Error('webrtcSignaling: callId and participantId are required'),
      );
    }
    if (this.socket) {
      return Promise.reject(
        new Error('webrtcSignaling: already connected — disconnect first'),
      );
    }
    this.handlers = handlers;

    const url =
      `${resolveBaseUrl()}?call_id=${encodeURIComponent(callId)}` +
      `&participant_id=${encodeURIComponent(participantId)}`;

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
            new Error(
              `webrtcSignaling: join timeout (${url}) — is Backend 1 running on :8001?`,
            ),
          );
        }
      }, 10000);

      const settleResolve = () => {
        if (settled) return;
        settled = true;
        window.clearTimeout(timer);
        resolve();
      };
      const settleReject = (err: Error) => {
        if (settled) return;
        settled = true;
        window.clearTimeout(timer);
        this.socket = null;
        this.connectPromise = null;
        reject(err);
      };
      this.joinedResolve = settleResolve;
      this.joinedReject = settleReject;

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
            : new Error('webrtcSignaling: failed to create WebSocket'),
        );
        return;
      }
      this.socket = socket;

      socket.onopen = () => {
        try {
          socket.send(JSON.stringify({ type: 'join', display_name: displayName }));
        } catch (err) {
          settleReject(
            err instanceof Error ? err : new Error('webrtcSignaling: join send failed'),
          );
        }
      };

      socket.onerror = () => {
        settleReject(
          new Error(
            `webrtcSignaling: connection failed (${url}) — is Backend 1 running on :8001?`,
          ),
        );
        this.handlers.onClose?.();
      };

      socket.onclose = () => {
        if (!settled) {
          settleReject(new Error('webrtcSignaling: closed before join completed'));
        }
        this.socket = null;
        this.connectPromise = null;
        this.handlers.onClose?.();
      };

      socket.onmessage = (event: MessageEvent) => {
        this.handleMessage(event.data);
      };
    });

    return this.connectPromise;
  }

  private handleMessage(data: unknown): void {
    if (typeof data !== 'string') return; // signaling is JSON text only
    let msg: Record<string, unknown>;
    try {
      msg = JSON.parse(data) as Record<string, unknown>;
    } catch {
      return; // malformed: ignore, never crash the app
    }
    const type = msg['type'];
    switch (type) {
      case 'joined':
        this.joinedResolve?.();
        this.joinedResolve = null;
        this.joinedReject = null;
        this.handlers.onJoined?.((msg['peers'] as SignalPeer[]) ?? []);
        break;
      case 'peer-joined':
        this.handlers.onPeerJoined?.({
          participant_id: String(msg['participant_id'] ?? ''),
          display_name: String(msg['display_name'] ?? ''),
        });
        break;
      case 'peer-left':
        this.handlers.onPeerLeft?.(String(msg['participant_id'] ?? ''));
        break;
      case 'offer':
        this.handlers.onOffer?.(
          String(msg['from'] ?? ''),
          (msg['payload'] ?? {}) as RTCSessionDescriptionInit,
        );
        break;
      case 'answer':
        this.handlers.onAnswer?.(
          String(msg['from'] ?? ''),
          (msg['payload'] ?? {}) as RTCSessionDescriptionInit,
        );
        break;
      case 'ice':
        this.handlers.onIce?.(
          String(msg['from'] ?? ''),
          (msg['payload'] ?? {}) as RTCIceCandidateInit,
        );
        break;
      case 'error':
        this.handlers.onErrorMessage?.(String(msg['detail'] ?? 'signaling error'));
        break;
      default:
        break; // unknown frame types are ignored
    }
  }

  private sendEnvelope(message: Record<string, unknown>): void {
    if (!this.isConnected() || !this.socket) {
      if (import.meta.env.DEV) {
        // eslint-disable-next-line no-console
        console.warn('[webrtcSignaling] drop: socket not open', message['type']);
      }
      return;
    }
    try {
      this.socket.send(JSON.stringify(message));
    } catch {
      // ignore send errors; close handler surfaces disconnects
    }
  }

  public sendOffer(to: string, sdp: RTCSessionDescriptionInit): void {
    this.sendEnvelope({ type: 'offer', to, payload: sdp });
  }

  public sendAnswer(to: string, sdp: RTCSessionDescriptionInit): void {
    this.sendEnvelope({ type: 'answer', to, payload: sdp });
  }

  public sendIce(to: string, candidate: RTCIceCandidateInit): void {
    this.sendEnvelope({ type: 'ice', to, payload: candidate });
  }

  public leave(): void {
    this.sendEnvelope({ type: 'leave' });
    this.disconnect();
  }

  public disconnect(): void {
    // Idempotent.
    const socket = this.socket;
    this.socket = null;
    this.connectPromise = null;
    this.joinedResolve = null;
    this.joinedReject = null;
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

export const webrtcSignaling = new WebRTCSignalingService();
