import { Call, Evidence, SystemStatus } from '../types';
import { MOCK_ACTIVE_CALLS, MOCK_CALL_HISTORY, INITIAL_SYSTEM_STATUS } from './mockData';

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000/api/v1';

export class ApiService {
  private baseUrl: string;

  constructor() {
    this.baseUrl = API_BASE_URL;
  }

  public async getActiveCalls(): Promise<Call[]> {
    try {
      const res = await fetch(`${this.baseUrl}/calls/active`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return await res.json();
    } catch {
      // Fallback for standalone demo mode / backend unavailable
      return MOCK_ACTIVE_CALLS;
    }
  }

  public async getCallById(callId: string): Promise<Call | null> {
    try {
      const res = await fetch(`${this.baseUrl}/calls/${callId}`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return await res.json();
    } catch {
      const found = [...MOCK_ACTIVE_CALLS, ...MOCK_CALL_HISTORY].find(c => c.id === callId);
      return found || null;
    }
  }

  public async getEvidence(callId: string): Promise<Evidence | null> {
    try {
      const res = await fetch(`${this.baseUrl}/calls/${callId}/evidence`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return await res.json();
    } catch {
      const call = [...MOCK_ACTIVE_CALLS, ...MOCK_CALL_HISTORY].find(c => c.id === callId);
      return call?.evidence || null;
    }
  }

  public async getCallHistory(): Promise<Call[]> {
    try {
      const res = await fetch(`${this.baseUrl}/calls/history`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return await res.json();
    } catch {
      return MOCK_CALL_HISTORY;
    }
  }

  public async getSystemStatus(): Promise<SystemStatus> {
    try {
      const res = await fetch(`${this.baseUrl}/system/status`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return await res.json();
    } catch {
      return INITIAL_SYSTEM_STATUS;
    }
  }

  public async terminateCall(callId: string, reason: string): Promise<boolean> {
    try {
      const res = await fetch(`${this.baseUrl}/calls/${callId}/terminate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ reason })
      });
      return res.ok;
    } catch {
      return true;
    }
  }
}

export const apiService = new ApiService();
