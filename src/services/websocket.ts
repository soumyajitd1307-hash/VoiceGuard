import { RiskUpdate, WSConnectionStatus } from '../types';

export type WSMessageListener = (message: RiskUpdate) => void;
export type WSStatusListener = (status: WSConnectionStatus, message?: string) => void;

class WebSocketService {
  private socket: WebSocket | null = null;
  private url: string;
  private status: WSConnectionStatus = 'DISCONNECTED';
  private messageListeners: Set<WSMessageListener> = new Set();
  private statusListeners: Set<WSStatusListener> = new Set();
  private reconnectAttempts = 0;
  private maxReconnectAttempts = 5;
  private reconnectTimer: number | null = null;
  private manualDisconnect = false;

  constructor() {
    this.url = import.meta.env.VITE_WS_URL || 'ws://localhost:8000/ws/calls';
  }

  public setUrl(url: string): void {
    this.url = url;
  }

  public getUrl(): string {
    return this.url;
  }

  public getStatus(): WSConnectionStatus {
    return this.status;
  }

  private setStatus(status: WSConnectionStatus, message?: string): void {
    this.status = status;
    this.statusListeners.forEach(listener => listener(status, message));
  }

  public connect(): void {
    if (this.socket && (this.socket.readyState === WebSocket.OPEN || this.socket.readyState === WebSocket.CONNECTING)) {
      return;
    }

    this.manualDisconnect = false;
    this.setStatus('CONNECTING');

    try {
      this.socket = new WebSocket(this.url);

      this.socket.onopen = () => {
        this.reconnectAttempts = 0;
        this.setStatus('CONNECTED');
      };

      this.socket.onmessage = (event: MessageEvent) => {
        try {
          const data = JSON.parse(event.data);
          if (data && data.type === 'risk_update') {
            this.broadcastMessage(data as RiskUpdate);
          }
        } catch {
          // ignore malformed message
        }
      };

      this.socket.onerror = () => {
        this.setStatus('ERROR', 'WebSocket connection error');
      };

      this.socket.onclose = () => {
        if (!this.manualDisconnect) {
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
      this.setStatus('DISCONNECTED', 'Backend unavailable. Operating in local demo simulation mode.');
    }
  }

  public disconnect(): void {
    this.manualDisconnect = true;
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
