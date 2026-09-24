import React, { createContext, useContext, useState, useEffect, useCallback, useMemo, useRef } from 'react';
import { Call, RiskUpdate, DetectionEvent, SecurityAlert, Evidence, WSConnectionStatus, SystemStatus, MonitoringState, BackendAlert, BackendEvidenceRecord, BackendSecurityAlertEvent } from '../types';
import { wsService, isRiskUpdateForCall } from '../services/websocket';
import type { BackendCallSummary } from '../services/backend4calls';
import { getCallEvidence, getCallAlerts, acknowledgeAlert as acknowledgeBackendAlertApi, mergeBackendAlerts, getActiveCalls, getCallHistory, mergeCallLists, terminateCall as terminateBackendCall } from '../services/backend4calls';
import { demoSimulator } from '../services/demoSimulator';
import { audioCapture } from '../services/audioCapture';
import { audioStream } from '../services/audioStream';
import { MOCK_ACTIVE_CALLS, MOCK_CALL_HISTORY, INITIAL_SYSTEM_STATUS, INITIAL_EVIDENCE_1042 } from '../services/mockData';
import { getRiskLevel, formatSeconds, appendRiskPoint } from '../utils/risk';
import { resolveIntelFetch } from '../utils/intel';

interface CallContextType {
  activeCalls: Call[];
  selectedCall: Call | null;
  currentCallId: string;
  securityAlert: SecurityAlert | null;
  investigationCall: Call | null;
  evidenceModal: Evidence | null;
  wsStatus: WSConnectionStatus;
  wsMessage: string;
  isDemoMode: boolean;
  systemStatus: SystemStatus;
  callHistory: Call[];
  detectionEventsLog: DetectionEvent[];
  // Prompt 8: B4 list sync state. idle = not fetched yet; loading =
  // fetch in flight; ready = last fetch succeeded (possibly empty);
  // error = last explicit fetch failed (message in callsError).
  activeCallsStatus: CallListStatus;
  callHistoryStatus: CallListStatus;
  callsError: string | null;
  // Authoritative B4 intel (Prompt 7): alerts across calls (each carries
  // its call_id) and per-call evidence snapshots. Never fabricated.
  backendAlerts: BackendAlert[];
  backendEvidence: Record<string, BackendEvidenceRecord[]>;
  // Per-call intel fetch failures (evidence source): call id -> message.
  // Lets views report backend errors explicitly instead of silently
  // showing "no evidence". Cleared on the next fetch attempt/success.
  intelErrors: Record<string, string>;
  // Actions
  selectCall: (callId: string) => void;
  startCall: (callerName?: string) => string;
  endCall: (callId?: string) => void;
  registerBackendCall: (summary: BackendCallSummary) => void;
  acknowledgeBackendAlert: (alertId: string) => Promise<void>;
  refreshBackendIntel: (callId: string, force?: boolean, allowEnded?: boolean) => void;
  refreshActiveCalls: (opts?: { silent?: boolean }) => Promise<void>;
  refreshCallHistory: (opts?: { silent?: boolean }) => Promise<void>;
  dismissAlert: () => void;
  openInvestigation: (call: Call) => void;
  closeInvestigation: () => void;
  openEvidence: (evidence: Evidence) => void;
  closeEvidence: () => void;
  toggleDemoMode: () => void;
  triggerHighRiskDemo: () => void;
  resetDemoCall: () => void;
  connectWebSocket: () => void;
  disconnectWebSocket: () => void;
}

const CallContext = createContext<CallContextType | undefined>(undefined);

/** Prompt 8 list sync state: idle → loading → ready | error. */
export type CallListStatus = 'idle' | 'loading' | 'ready' | 'error';

/**
 * Honest idle status for live mode. No backend data yet means zeros —
 * never the illustrative demo counters (those live in mockData and are
 * seeded only when demo mode is explicitly enabled).
 */
const INITIAL_LIVE_SYSTEM_STATUS: SystemStatus = {
  serviceStatus: 'OUTAGE',
  activeCallsCount: 0,
  totalCallsAnalyzed: 0,
  highRiskCallsCount: 0,
  aiEngineLatencyMs: 0,
  modelAccuracy: 0,
  modelVersion: '—',
  webrtcNodesHealthy: 0,
  webrtcNodesTotal: 0,
  wsConnections: 0,
  uptimeSeconds: 0,
};

export const CallProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  // Live state starts empty: no backend data exists yet, so nothing is
  // shown until a real call starts or demo mode is explicitly enabled.
  // Demo fixtures (MOCK_*) are seeded only via toggleDemoMode/resetDemoCall.
  const [activeCalls, setActiveCalls] = useState<Call[]>([]);
  const [callHistory, setCallHistory] = useState<Call[]>([]);
  const [currentCallId, setCurrentCallId] = useState<string>('');
  const [securityAlert, setSecurityAlert] = useState<SecurityAlert | null>(null);
  const [investigationCall, setInvestigationCall] = useState<Call | null>(null);
  const [evidenceModal, setEvidenceModal] = useState<Evidence | null>(null);
  const [wsStatus, setWsStatus] = useState<WSConnectionStatus>('DISCONNECTED');
  const [wsMessage, setWsMessage] = useState<string>('');
  // Live-first: demo theater (simulator + fixtures) runs only after the
  // user explicitly enables demo mode via toggleDemoMode.
  const [isDemoMode, setIsDemoMode] = useState<boolean>(false);
  const [systemStatus, setSystemStatus] = useState<SystemStatus>(INITIAL_LIVE_SYSTEM_STATUS);
  // B4-authoritative intel. Alerts carry their own call_id (filtered at
  // render); evidence is snapshotted per call id (replaced on refresh).
  const [backendAlerts, setBackendAlerts] = useState<BackendAlert[]>([]);
  const [backendEvidence, setBackendEvidence] = useState<Record<string, BackendEvidenceRecord[]>>({});
  const [intelErrors, setIntelErrors] = useState<Record<string, string>>({});
  // Prompt 8: B4 list sync state. idle = never fetched; loading = fetch in
  // flight; ready = last fetch succeeded (list may honestly be empty);
  // error = last explicit fetch failed (message in callsError).
  const [activeCallsStatus, setActiveCallsStatus] = useState<CallListStatus>('idle');
  const [callHistoryStatus, setCallHistoryStatus] = useState<CallListStatus>('idle');
  const [callsError, setCallsError] = useState<string | null>(null);

  // Mirrors for async callbacks (avoid stale closures over state).
  const activeIdsRef = useRef<string[]>([]);
  const lastIntelFetchRef = useRef<Record<string, number>>({});
  const intelInflightRef = useRef<Set<string>>(new Set());
  const listsInflightRef = useRef<{ active: boolean; history: boolean }>({ active: false, history: false });

  useEffect(() => {
    activeIdsRef.current = activeCalls.map(c => c.id);
  }, [activeCalls]);

  const selectedCall = useMemo(() => {
    return activeCalls.find(c => c.id === currentCallId) || null;
  }, [activeCalls, currentCallId]);

  const detectionEventsLog = useMemo(() => {
    const events: DetectionEvent[] = [];
    activeCalls.forEach(c => events.push(...c.detectionEvents));
    return events.sort((a, b) => b.timestamp - a.timestamp);
  }, [activeCalls]);

  // Handle incoming RiskUpdate from WebSocket or Simulator
  const handleRiskUpdate = useCallback((update: RiskUpdate) => {
    setActiveCalls(prevCalls => {
      const callIndex = prevCalls.findIndex(c => isRiskUpdateForCall(update, c.id));
      if (callIndex === -1) {
        // Call-id isolation: never apply one call's risk to another call
        // (or to an empty state). The sender keeps its data; we drop ours.
        if (import.meta.env.DEV) {
          // eslint-disable-next-line no-console
          console.warn(
            `[CallContext] Ignoring RiskUpdate for unknown call ${update.callId} ` +
              `(${prevCalls.length} active call(s))`,
          );
        }
        return prevCalls;
      }

      const current = prevCalls[callIndex];
      const newRiskLevel = getRiskLevel(update.risk);
      const formattedTime = formatSeconds(update.timestamp);

      // Backend omits absent ML signals by design (never zero-filled);
      // retain the last known values so state never degrades to undefined.
      const syntheticProbability = update.syntheticProbability ?? current.syntheticProbability;
      const speakerConsistency = update.speakerConsistency ?? current.speakerConsistency;
      const contextRisk = update.contextRisk ?? current.contextRisk;

      // Demo mode only: synthesize illustrative detection events for the
      // hackathon theater. In live mode backend RiskUpdates are applied
      // as-is — the frontend must never fabricate events, alerts, or
      // evidence for a real call.
      const existingEvents = [...current.detectionEvents];

      if (isDemoMode) {
        const isNewTimestamp = !existingEvents.some(e => Math.abs(e.timestamp - update.timestamp) < 2);

        if (isNewTimestamp && (update.risk >= 40 || update.timestamp === 4 || update.timestamp === 18)) {
          let desc = `Acoustic variance monitored: risk ${update.risk}%`;
          let eventType: DetectionEvent['eventType'] = 'acoustic_drift';

          if (update.risk >= 70) {
            desc = `POSSIBLE SYNTHETIC VOICE: High-probability vocoder artifacts detected (${syntheticProbability}%).`;
            eventType = 'deepfake_confirmed';
          } else if (update.risk >= 40) {
            desc = `Harmonics anomaly: Pitch flattening variance outside biological vocal tract standard.`;
            eventType = 'pitch_flattening';
          }

          existingEvents.push({
            id: `evt-${update.callId}-${update.timestamp}`,
            callId: update.callId,
            timestamp: update.timestamp,
            formattedTime,
            risk: update.risk,
            syntheticProbability,
            severity: newRiskLevel,
            eventType,
            description: desc,
            confidence: update.confidence,
            audioSegmentAvailable: update.risk >= 70
          });
        }
      }

      // Append the B4 point verbatim (no interpolation/smoothing).
      const updatedHistory = appendRiskPoint(current.riskHistory, {
        timestamp: update.timestamp,
        risk: update.risk,
        syntheticProbability,
      });

      const updatedCall: Call = {
        ...current,
        durationSeconds: Math.max(current.durationSeconds, update.timestamp),
        currentRisk: update.risk,
        currentRiskLevel: newRiskLevel,
        syntheticProbability,
        speakerConsistency,
        contextRisk,
        confidence: update.confidence,
        // Latch the additive B4 provenance flag: true while the scoring
        // detector is the development heuristic. Absent on older backends
        // means unknown — never assumed real, never assumed mock.
        detectorIsMock: update.is_mock ?? current.detectorIsMock,
        monitoringState: update.monitoringState || (update.risk >= 70 ? 'ALERT_TRIGGERED' : update.risk >= 40 ? 'SUSPICIOUS' : 'MONITORING_ACTIVE'),
        status: update.risk >= 70 ? 'FLAGGED' : current.status === 'FLAGGED' ? 'FLAGGED' : 'ACTIVE',
        detectionEvents: existingEvents,
        riskHistory: updatedHistory,
        // Demo theater only: attach the illustrative fixture evidence.
        // A live call shows evidence only when the backend provides it.
        evidence: isDemoMode && update.risk >= 70 ? (current.evidence || INITIAL_EVIDENCE_1042) : current.evidence
      };

      // Demo theater only: the frontend never raises security alerts for
      // live calls. Backend alerts will arrive over the risk WebSocket.
      if (isDemoMode && update.risk >= 70 && (!securityAlert || securityAlert.callId !== update.callId)) {
        setSecurityAlert({
          id: `alert-${update.callId}-${Date.now()}`,
          callId: update.callId,
          callerName: current.caller.name,
          risk: update.risk,
          syntheticProbability,
          detectionTime: formattedTime,
          confidence: update.confidence,
          message: 'POSSIBLE SYNTHETIC VOICE DETECTED',
          timestamp: new Date().toLocaleTimeString(),
          status: 'ACTIVE',
          suggestedAction: 'Isolate Call & Force Secondary Multi-Factor Verification'
        });
      }

      const nextCalls = [...prevCalls];
      nextCalls[callIndex] = updatedCall;
      return nextCalls;
    });

    // Update system status
    setSystemStatus(prev => ({
      ...prev,
      totalCallsAnalyzed: prev.totalCallsAnalyzed + (update.timestamp % 10 === 0 ? 1 : 0),
      highRiskCallsCount: update.risk >= 70 ? 2 : 1
    }));
  }, [securityAlert, isDemoMode]);

  /**
   * Refresh one call's B4 evidence + alerts (Prompt 7). Bounded: at most
   * one in-flight fetch per call and at most one refresh per 10 s per
   * call unless forced (see resolveIntelFetch). Failures record an
   * explicit per-call error and keep previous state — never fixtures,
   * never fabricated records.
   *
   * allowEnded: explicit ended/history-call retrieval. B4 keeps serving
   * evidence/alerts after terminate, but endCall purges caches and the
   * live path only tracks active calls — so without this flag, ended
   * calls could never show their B4 records again.
   */
  const refreshBackendIntel = useCallback((callId: string, force = false, allowEnded = false) => {
    const verdict = resolveIntelFetch({
      callId,
      isActive: activeIdsRef.current.includes(callId),
      allowEnded,
      nowMs: Date.now(),
      lastFetchMs: lastIntelFetchRef.current[callId],
      inflight: intelInflightRef.current.has(callId),
      force,
    });
    if (verdict.decision !== 'fetch') return;
    const now = Date.now();
    intelInflightRef.current.add(callId);
    lastIntelFetchRef.current[callId] = now;
    setIntelErrors(prev => {
      if (!(callId in prev)) return prev;
      const rest = { ...prev };
      delete rest[callId];
      return rest;
    });
    void Promise.allSettled([getCallEvidence(callId), getCallAlerts(callId)]).then(
      ([ev, al]) => {
        intelInflightRef.current.delete(callId);
        // Live path only: results landing after the call ended mid-flight
        // must not resurrect its caches (explicit ended fetches bypass by
        // re-entering through allowEnded on the next user action).
        if (!allowEnded && !activeIdsRef.current.includes(callId)) return; // ended mid-flight
        if (ev.status === 'fulfilled') {
          setBackendEvidence(prev => ({ ...prev, [callId]: ev.value }));
        } else {
          const message = ev.reason instanceof Error ? ev.reason.message : 'Evidence unavailable.';
          setIntelErrors(prev => ({ ...prev, [callId]: message }));
          if (import.meta.env.DEV) {
            // eslint-disable-next-line no-console
            console.warn(`[CallContext] evidence fetch failed for ${callId}:`, ev.reason);
          }
        }
        if (al.status === 'fulfilled') {
          setBackendAlerts(prev => mergeBackendAlerts(prev, al.value, callId));
        } else if (import.meta.env.DEV) {
          // eslint-disable-next-line no-console
          console.warn(`[CallContext] alerts fetch failed for ${callId}:`, al.reason);
        }
      },
    );
  }, []);

  /**
   * Real-time B4 `security_alert` event (Prompt 7). Validates the call is
   * active, then converges via authoritative fetch (force: alerts are
   * rare and B4 cooldown-dedups). The event itself is never stored —
   * only full GET records enter state, so WS and REST converge by id.
   */
  const handleBackendAlertEvent = useCallback((event: BackendSecurityAlertEvent) => {
    if (!activeIdsRef.current.includes(event.callId)) {
      if (import.meta.env.DEV) {
        // eslint-disable-next-line no-console
        console.warn(
          `[CallContext] Ignoring security_alert ${event.alert_id} for unknown call ${event.callId}`,
        );
      }
      return;
    }
    refreshBackendIntel(event.callId, true);
  }, [refreshBackendIntel]);

  /**
   * Acknowledge one B4 alert by its authoritative id. Marks acknowledged
   * ONLY on B4 success — a failed POST leaves state untouched (no fake ack).
   */
  const acknowledgeBackendAlert = useCallback(async (alertId: string) => {
    const updated = await acknowledgeBackendAlertApi(alertId);
    setBackendAlerts(prev =>
      prev.map(a => (a.alert_id === updated.alert_id ? updated : a)),
    );
  }, []);

  /**
   * Refresh the authoritative active-call list (Prompt 8). Skipped
   * entirely in demo mode (fixtures own the state there). Silent mode
   * updates data without touching loading/error UI (used after
   * terminate/reconnect); explicit mode drives loading → ready | error.
   * Merge preserves local `local-` sessions and drops records B4 no
   * longer lists. Failures never substitute fixtures.
   */
  const refreshActiveCalls = useCallback(async (opts?: { silent?: boolean }) => {
    if (isDemoMode) return;
    const silent = opts?.silent ?? false;
    if (listsInflightRef.current.active) return;
    listsInflightRef.current.active = true;
    if (!silent) {
      setActiveCallsStatus('loading');
      setCallsError(null);
    }
    try {
      const raw = await getActiveCalls();
      setActiveCalls(prev => mergeCallLists(prev, raw, true));
      setActiveCallsStatus('ready');
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Active calls unavailable.';
      if (!silent) {
        setActiveCallsStatus('error');
        setCallsError(`Active calls: ${message}`);
      } else if (import.meta.env.DEV) {
        // eslint-disable-next-line no-console
        console.warn(`[CallContext] silent active refresh failed:`, message);
      }
    } finally {
      listsInflightRef.current.active = false;
    }
  }, [isDemoMode]);

  /**
   * Refresh the authoritative call-history list (Prompt 8). Same
   * contract as active: demo-skipped, silent-capable, merge retains
   * local-only rows B4 never recorded, failures never fabricate.
   */
  const refreshCallHistory = useCallback(async (opts?: { silent?: boolean }) => {
    if (isDemoMode) return;
    const silent = opts?.silent ?? false;
    if (listsInflightRef.current.history) return;
    listsInflightRef.current.history = true;
    if (!silent) {
      setCallHistoryStatus('loading');
      setCallsError(null);
    }
    try {
      const raw = await getCallHistory();
      setCallHistory(prev => mergeCallLists(prev, raw, false));
      setCallHistoryStatus('ready');
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Call history unavailable.';
      if (!silent) {
        setCallHistoryStatus('error');
        setCallsError(`Call history: ${message}`);
      } else if (import.meta.env.DEV) {
        // eslint-disable-next-line no-console
        console.warn(`[CallContext] silent history refresh failed:`, message);
      }
    } finally {
      listsInflightRef.current.history = false;
    }
  }, [isDemoMode]);

  // Subscribe to WebSocket updates and status
  useEffect(() => {
    const unsubMsg = wsService.onMessage((update) => {
      handleRiskUpdate(update);
      // Live intel follows the B4 cadence (throttled inside); demo mode
      // never touches the backend.
      if (!isDemoMode) {
        refreshBackendIntel(update.callId);
      }
    });
    const unsubAlert = wsService.onAlert(handleBackendAlertEvent);
    const unsubStatus = wsService.onStatusChange((status, message) => {
      setWsStatus(status);
      setWsMessage(message || '');
      // Reconnect convergence (§19): a fresh risk stream re-syncs intel
      // and re-confirms the authoritative active list.
      if (status === 'CONNECTED' && !isDemoMode) {
        const bound = wsService.getCallId();
        if (bound) refreshBackendIntel(bound, true);
        void refreshActiveCalls({ silent: true });
      }
    });

    // Start Demo Simulator on mount if in demo mode.
    // Live mode never auto-connects here: the risk socket opens per real
    // call (PeerCallScreen) with that call's B4 id, never on startup.
    // Live mode DOES fetch the authoritative lists once, so Active Calls
    // and History start from Backend 4 data (honest empty when none).
    if (isDemoMode) {
      demoSimulator.start('1042');
    } else {
      void refreshActiveCalls();
      void refreshCallHistory();
    }

    return () => {
      unsubMsg();
      unsubAlert();
      unsubStatus();
      demoSimulator.stop();
      wsService.disconnect();
    };
  }, [handleRiskUpdate, handleBackendAlertEvent, refreshBackendIntel, refreshActiveCalls, refreshCallHistory, isDemoMode]);

  // Backend 1 live-audio teardown on provider unmount ONLY. This must stay a
  // mount/unmount effect: depending on risk updates here (securityAlert /
  // handleRiskUpdate / isDemoMode / demo timeline) would kill a live
  // microphone + audio socket mid-call whenever a security alert fires.
  useEffect(() => {
    return () => {
      audioCapture.stop();
      audioStream.disconnect();
    };
  }, []);

  const selectCall = (callId: string) => {
    setCurrentCallId(callId);
  };

  const startCall = (callerName: string = 'Unknown caller'): string => {
    // Local live session. No backend exists yet, so this record is
    // deliberately minimal and unvalidated: a unique session id the audio
    // transport can attach to, zeroed metrics, and no history — never a
    // fabricated backend call. Risk/events/evidence appear only when the
    // backend starts sending RiskUpdates.
    const newId = `local-${Date.now().toString(36)}-${Math.floor(Math.random() * 1e6).toString(36)}`;
    const newCall: Call = {
      id: newId,
      caller: {
        id: `usr-${newId}`,
        name: callerName,
        phone: '—',
        organization: 'Unverified caller',
        department: '—',
        trustScore: 0,
        language: 'Unknown',
        isKnownContact: false
      },
      receiver: 'Security Operations',
      startTime: new Date().toISOString(),
      durationSeconds: 0,
      currentRisk: 0,
      currentRiskLevel: 'LOW',
      syntheticProbability: 0,
      speakerConsistency: 0,
      contextRisk: 0,
      confidence: 'LOW',
      status: 'ACTIVE',
      monitoringState: 'INITIALIZING',
      detectionEvents: [],
      riskHistory: [],
      protocol: 'WebRTC',
      codec: 'Opus/48kHz',
      packetLoss: 0,
      latencyMs: 0,
      isSimulatedDemo: false
    };

    setActiveCalls(prev => [newCall, ...prev]);
    setCurrentCallId(newId);

    if (isDemoMode) {
      demoSimulator.start(newId);
    }

    return newId;
  };

  const endCall = (callId?: string) => {
    const targetId = callId || currentCallId;
    // Close the risk stream bound to this call FIRST (stops its reconnect
    // loop and unbinds the id), even if the record is already gone.
    if (wsService.getCallId() === targetId) {
      wsService.disconnect(true);
    }
    // Purge B4 intel caches so a later call never inherits them
    // (isolation across call lifetimes).
    setBackendAlerts(prev => prev.filter(a => a.call_id !== targetId));
    setBackendEvidence(prev => {
      if (!(targetId in prev)) return prev;
      const rest = { ...prev };
      delete rest[targetId];
      return rest;
    });
    delete lastIntelFetchRef.current[targetId];
    const callToEnd = activeCalls.find(c => c.id === targetId);
    if (!callToEnd) return;

    // Backend 1 live-audio teardown (idempotent by design of both services).
    // Centralized here so audio cleanup cannot be skipped when a call is
    // terminated from another existing path (Dashboard terminate,
    // InvestigationModal, MobileApp). Order: capture first, then socket.
    audioCapture.stop();
    audioStream.disconnect();

    if (!isDemoMode && !targetId.startsWith('local-')) {
      // Authoritative B4 termination (best-effort): without this, B4 keeps
      // listing the call and the next refresh would resurrect it. Local
      // removal below proceeds regardless; transport failures only warn.
      // Server-side terminate is idempotent, so paths that already called
      // it (PeerCallScreen) are safe.
      void terminateBackendCall(targetId).catch((err: unknown) => {
        if (import.meta.env.DEV) {
          // eslint-disable-next-line no-console
          console.warn(`[CallContext] B4 terminate failed for ${targetId}:`, err);
        }
      });
    }

    const endedCall: Call = {
      ...callToEnd,
      status: 'ENDED',
      monitoringState: 'COMPLETED'
    };

    setActiveCalls(prev => prev.filter(c => c.id !== targetId));
    setCallHistory(prev => [endedCall, ...prev]);

    if (!isDemoMode) {
      // Re-converge on B4 after local teardown: the terminated call is now
      // recorded server-side (history) and gone from active. Silent: no
      // loading flicker, failures only warn — local state already updated.
      void refreshActiveCalls({ silent: true });
      void refreshCallHistory({ silent: true });
    }

    if (targetId === currentCallId) {
      // Pick next active call if any
      const remaining = activeCalls.filter(c => c.id !== targetId);
      if (remaining.length > 0) {
        setCurrentCallId(remaining[0].id);
      }
    }

    if (isDemoMode && targetId === '1042') {
      demoSimulator.stop();
    }
  };

  const dismissAlert = () => {
    setSecurityAlert(null);
  };

  const KNOWN_MONITORING_STATES: MonitoringState[] = [
    'INITIALIZING',
    'ANALYZING',
    'MONITORING_ACTIVE',
    'SUSPICIOUS',
    'ALERT_TRIGGERED',
    'COMPLETED',
  ];

  /**
   * Register a REAL B4-created call into live state (Prompt 6). Called
   * once per peer call with the POST /calls response (or its id for a
   * joined call). Backend nulls are coalesced to empty/zero display
   * placeholders — transport normalization, never telemetry: risk,
   * history, events and evidence arrive only via real RiskUpdates.
   * Re-registering an existing id keeps state and just selects it.
   */
  const registerBackendCall = (summary: BackendCallSummary) => {
    const id = summary.id;
    const monitoringState: MonitoringState = KNOWN_MONITORING_STATES.includes(
      summary.monitoringState as MonitoringState,
    )
      ? (summary.monitoringState as MonitoringState)
      : 'MONITORING_ACTIVE';
    const record: Call = {
      id,
      caller: {
        id,
        name: summary.callerName || 'Unknown caller',
        phone: '',
        organization: '',
        department: '',
        trustScore: 0,
        language: '',
        isKnownContact: false,
      },
      receiver: summary.receiver || '',
      startTime: summary.startTime || new Date().toISOString(),
      durationSeconds: 0,
      currentRisk: 0,
      currentRiskLevel: 'LOW',
      syntheticProbability: 0,
      speakerConsistency: 0,
      contextRisk: 0,
      confidence: 'LOW',
      status: summary.status === 'ENDED' ? 'ENDED' : 'ACTIVE',
      monitoringState,
      detectionEvents: [],
      riskHistory: [],
      evidence: undefined,
      protocol: 'WebRTC',
      codec: 'Opus/48kHz',
      packetLoss: 0,
      latencyMs: 0,
      isSimulatedDemo: false,
    };
    setActiveCalls(prev =>
      prev.some(c => c.id === id) ? prev : [record, ...prev],
    );
    setCurrentCallId(id);
  };

  const openInvestigation = (call: Call) => {
    setInvestigationCall(call);
  };

  const closeInvestigation = () => {
    setInvestigationCall(null);
  };

  const openEvidence = (evidence: Evidence) => {
    setEvidenceModal(evidence);
  };

  const closeEvidence = () => {
    setEvidenceModal(null);
  };

  const toggleDemoMode = () => {
    const nextMode = !isDemoMode;
    setIsDemoMode(nextMode);
    if (nextMode) {
      // Demo theater: seed illustrative fixtures, isolated from live state.
      wsService.disconnect();
      setActiveCalls(MOCK_ACTIVE_CALLS);
      setCallHistory(MOCK_CALL_HISTORY);
      setCurrentCallId('1042');
      setSecurityAlert(null);
      setSystemStatus(INITIAL_SYSTEM_STATUS);
      demoSimulator.start('1042');
    } else {
      // Back to live: stop the simulator and drop every demo fixture so
      // the UI returns to the honest empty state, then re-fetch the
      // authoritative lists. No auto-connect: the risk socket opens per
      // real call only (PeerCallScreen).
      demoSimulator.stop();
      setActiveCalls([]);
      setCallHistory([]);
      setCurrentCallId('');
      setSecurityAlert(null);
      setSystemStatus(INITIAL_LIVE_SYSTEM_STATUS);
      void refreshActiveCalls();
      void refreshCallHistory();
    }
  };

  const triggerHighRiskDemo = () => {
    demoSimulator.jumpToSecond(18);
  };

  const resetDemoCall = () => {
    setActiveCalls(MOCK_ACTIVE_CALLS);
    setCurrentCallId('1042');
    setSecurityAlert(null);
    demoSimulator.start('1042');
  };

  const connectWebSocket = () => {
    wsService.connect();
  };

  const disconnectWebSocket = () => {
    wsService.disconnect();
  };

  return (
    <CallContext.Provider
      value={{
        activeCalls,
        selectedCall,
        currentCallId,
        securityAlert,
        investigationCall,
        evidenceModal,
        wsStatus,
        wsMessage,
        isDemoMode,
        systemStatus,
        callHistory,
        detectionEventsLog,
        backendAlerts,
        backendEvidence,
        intelErrors,
        activeCallsStatus,
        callHistoryStatus,
        callsError,
        selectCall,
        startCall,
        endCall,
        registerBackendCall,
        acknowledgeBackendAlert,
        refreshBackendIntel,
        refreshActiveCalls,
        refreshCallHistory,
        dismissAlert,
        openInvestigation,
        closeInvestigation,
        openEvidence,
        closeEvidence,
        toggleDemoMode,
        triggerHighRiskDemo,
        resetDemoCall,
        connectWebSocket,
        disconnectWebSocket
      }}
    >
      {children}
    </CallContext.Provider>
  );
};

export const useCallContext = (): CallContextType => {
  const context = useContext(CallContext);
  if (!context) {
    throw new Error('useCallContext must be used within a CallProvider');
  }
  return context;
};
