import { RiskUpdate, BackendSecurityAlertEvent, WSConnectionStatus } from '../types';

export type WSMessageListener = (message: RiskUpdate) => void;
export type WSAlertListener = (event: BackendSecurityAlertEvent) => void;
export type WSStatusListener = (status: WSConnectionStatus, message?: string) => void;

/**
 * Build the exact risk-stream URL for one call. Exported for tests.
 * The call_id is REQUIRED: the backend closes id-less sockets (4401).
 */
export function buildRiskWsUrl(baseUrl: string, callId: string): string {
  const base = baseUrl.replace(/\/+$/, '');
  return `${base}?call_id=${encodeURIComponent(callId)}`;
}

function isRecord(data: unknown): data is Record<string, unknown> {
  return typeof data === 'object' && data !== null;
}

/**
 * Validate an inbound frame against the B4 RiskUpdate contract.
 * Returns the update verbatim (values never recalculated), or null for
 * malformed frames and unknown message types (e.g. security_alert, which
 * belongs to a later milestone). Never throws, never fabricates.
 */
export function validateRiskUpdate(data: unknown): RiskUpdate | null {
  if (!isRecord(data)) return null;
  if (data['type'] !== 'risk_update') return null;
  if (typeof data['callId'] !== 'string' || !data['callId']) return null;
  if (
    typeof data['risk'] !== 'number' ||
    !Number.isFinite(data['risk']) ||
    data['risk'] < 0 ||
    data['risk'] > 100
  ) {
    return null;
  }
  if (
    typeof data['timestamp'] !== 'number' ||
    !Number.isFinite(data['timestamp']) ||
    data['timestamp'] < 0
  ) {
    return null;
  }
  if (typeof data['confidence'] !== 'string' || !data['confidence']) return null;
  return data as unknown as RiskUpdate;
}

/**
 * Cross-call isolation predicate: an update belongs to exactly one call.
 * Exported for tests; CallContext enforces it before applying state.
 */
export function isRiskUpdateForCall(update: RiskUpdate, callId: string): boolean {
  return update.callId === callId;
}

/**
 * Validate an inbound B4 `security_alert` event. Returns the event
 * verbatim or null for malformed/foreign frames. Never throws.
 * NOTE: this is a lightweight notice, not the authoritative record —
 * CallContext converges it via GET /alerts (deduped by alert_id).
 */
export function validateSecurityAlert(data: unknown): BackendSecurityAlertEvent | null {
  if (!isRecord(data)) return null;
  if (data['type'] !== 'security_alert') return null;
  if (typeof data['callId'] !== 'string' || !data['callId']) return null;
  if (typeof data['alert_id'] !== 'string' || !data['alert_id']) return null;
  if (
    typeof data['risk'] !== 'number' ||
    !Number.isFinite(data['risk']) ||
    data['risk'] < 0 ||
    data['risk'] > 100
  ) {
    return null;
  }
  if (
    typeof data['timestamp'] !== 'number' ||
    !Number.isFinite(data['timestamp']) ||
    data['timestamp'] < 0
  ) {
    return null;
  }
  return data as unknown as BackendSecurityAlertEvent;
}

class WebSocketService {
  private socket: WebSocket | null = null;
  private baseUrl: string;
  /** B4 call this socket is bound to. Reconnects always reuse it. */
  private boundCallId: string | null = null;
  private status: WSConnectionStatus = 'DISCONNECTED';
  private messageListeners: Set<WSMessageListener> = new Set();
  private alertListeners: Set<WSAlertListener> = new Set();
  private statusListeners: Set<WSStatusListener> = new Set();
  private reconnectAttempts = 0;
  private maxReconnectAttempts = 5;
  private reconnectTimer: number | null = null;
  private manualDisconnect = false;

  constructor() {
    this.baseUrl = import.meta.env?.VITE_WS_URL || 'ws://localhost:8000/ws/calls';
  }

  public setUrl(url: string): void {
    this.baseUrl = url;
  }

  public getUrl(): string {
    return this.baseUrl;
  }

  /** The B4 call id this socket is bound to (null when unbound). */
  public getCallId(): string | null {
    return this.boundCallId;
  }

  public getStatus(): WSConnectionStatus {
    return this.status;
  }

  private setStatus(status: WSConnectionStatus, message?: string): void {
    this.status = status;
    this.statusListeners.forEach(listener => listener(status, message));
  }

  /**
   * Connect the risk stream for ONE real B4 call. Passing a new call id
   * closes any previous call's socket first. Calling with no id reuses
   * the bound one (reconnect path); with nothing bound it refuses rather
   * than opening an id-less socket the backend would immediately close.
   * At most one socket exists at any time — re-calling for the same open
   * call is a no-op (React-rerender safe).
   */
  public connect(callId?: string): void {
    if (callId !== undefined) {
      this.boundCallId = callId;
    }
    if (!this.boundCallId) {
      if (import.meta.env?.DEV) {
        // eslint-disable-next-line no-console
        console.warn('[wsService] connect refused: no call_id bound (risk socket needs a real B4 call)');
      }
      return;
    }
    const target = buildRiskWsUrl(this.baseUrl, this.boundCallId);

    if (this.socket && (this.socket.readyState === WebSocket.OPEN || this.socket.readyState === WebSocket.CONNECTING)) {
      if (this.socket.url === target) return; // same call: no duplicate socket
      this.disconnect(); // different call: close the old one first
    }

    this.manualDisconnect = false;
    this.setStatus('CONNECTING');

    try {
      this.socket = new WebSocket(target);

      this.socket.onopen = () => {
        this.reconnectAttempts = 0;
        this.setStatus('CONNECTED');
      };

      this.socket.onmessage = (event: MessageEvent) => {
        let data: unknown;
        try {
          data = JSON.parse(event.data);
        } catch {
          return; // malformed JSON: ignore, never crash
        }
        const update = validateRiskUpdate(data);
        if (update) {
          this.broadcastMessage(update);
          return;
        }
        const alert = validateSecurityAlert(data);
        if (alert) {
          this.broadcastAlert(alert);
          return;
        }
        if (import.meta.env?.DEV) {
          // eslint-disable-next-line no-console
          console.debug('[wsService] ignoring non-risk frame');
        }
        return;
      };

      this.socket.onerror = () => {
        this.setStatus('ERROR', 'WebSocket connection error');
      };

      this.      socket.onclose = (event: CloseEvent) => {
        if (!this.manualDisconnect) {
          if (event && event.code === 4401) {
            // Rejected call id (unknown/foreign): retrying the same id is
            // pointless. Unbind so nothing reconnects a dead id, and
            // surface the rejection honestly instead of a generic error.
            this.manualDisconnect = true;
            this.boundCallId = null;
            this.setStatus('ERROR', 'Call rejected by backend (unknown call id).');
            return;
          }
          this.handleReconnect();
        } else {
          this.setStatus('DISCONNECTED');
        }
      };
    } catch {
      this.handleReconnect();
    }
  }

  private handleReconnect(): void {
    if (this.reconnectAttempts < this.maxReconnectAttempts) {
      this.reconnectAttempts++;
      this.setStatus('RECONNECTING', `Attempting to reconnect (${this.reconnectAttempts}/${this.maxReconnectAttempts})...`);
      
      const delay = Math.min(1000 * Math.pow(2, this.reconnectAttempts - 1), 8000);
      this.reconnectTimer = window.setTimeout(() => {
        this.connect();
      }, delay);
    } else {
      // Bounded: after 5 attempts we stop. The message must not claim a
      // demo fallback — live mode has none; the UI shows this verbatim.
      this.setStatus('DISCONNECTED', 'Backend unavailable. Live updates paused after 5 attempts.');
    }
  }

  /**
   * Close the socket and stop any reconnect loop. Pass resetBinding=true
   * when the bound call itself is over (endCall) so nothing can later
   * reconnect a dead call; default keeps the binding for transient drops.
   */
  public disconnect(resetBinding = false): void {
    this.manualDisconnect = true;
    if (resetBinding) {
      this.boundCallId = null;
    }
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    if (this.socket) {
      this.socket.close();
      this.socket = null;
    }
    this.setStatus('DISCONNECTED');
  }

  /**
   * Broadcasts a message to all listeners.
   * Can be invoked by real WebSocket or by the Demo Simulator!
   */
  public broadcastMessage(update: RiskUpdate): void {
    this.messageListeners.forEach(listener => listener(update));
  }

  public onMessage(listener: WSMessageListener): () => void {
    this.messageListeners.add(listener);
    return () => {
      this.messageListeners.delete(listener);
    };
  }

  /**
   * Subscribe to validated B4 `security_alert` events (Prompt 7).
   * Listeners receive the verbatim event; authoritative records still
   * come from GET /alerts. Call-id isolation is the subscriber's job.
   */
  public onAlert(listener: WSAlertListener): () => void {
    this.alertListeners.add(listener);
    return () => {
      this.alertListeners.delete(listener);
    };
  }

  private broadcastAlert(event: BackendSecurityAlertEvent): void {
    this.alertListeners.forEach(listener => listener(event));
  }

  public onStatusChange(listener: WSStatusListener): () => void {
    this.statusListeners.add(listener);
    // Immediately inform listener of current status
    listener(this.status);
    return () => {
      this.statusListeners.delete(listener);
    };
  }
}

export const wsService = new WebSocketService();
