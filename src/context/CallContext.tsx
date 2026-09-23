import React, { createContext, useContext, useState, useEffect, useCallback, useMemo } from 'react';
import { Call, RiskUpdate, DetectionEvent, SecurityAlert, Evidence, WSConnectionStatus, SystemStatus } from '../types';
import { wsService } from '../services/websocket';
import { demoSimulator } from '../services/demoSimulator';
import { audioCapture } from '../services/audioCapture';
import { audioStream } from '../services/audioStream';
import { MOCK_ACTIVE_CALLS, MOCK_CALL_HISTORY, INITIAL_SYSTEM_STATUS, INITIAL_EVIDENCE_1042 } from '../services/mockData';
import { getRiskLevel, formatSeconds } from '../utils/risk';

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
  // Actions
  selectCall: (callId: string) => void;
  startCall: (callerName?: string) => string;
  endCall: (callId?: string) => void;
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

export const CallProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [activeCalls, setActiveCalls] = useState<Call[]>(MOCK_ACTIVE_CALLS);
  const [callHistory, setCallHistory] = useState<Call[]>(MOCK_CALL_HISTORY);
  const [currentCallId, setCurrentCallId] = useState<string>('1042');
  const [securityAlert, setSecurityAlert] = useState<SecurityAlert | null>(null);
  const [investigationCall, setInvestigationCall] = useState<Call | null>(null);
  const [evidenceModal, setEvidenceModal] = useState<Evidence | null>(null);
  const [wsStatus, setWsStatus] = useState<WSConnectionStatus>('DISCONNECTED');
  const [wsMessage, setWsMessage] = useState<string>('');
  const [isDemoMode, setIsDemoMode] = useState<boolean>(true);
  const [systemStatus, setSystemStatus] = useState<SystemStatus>(INITIAL_SYSTEM_STATUS);

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
      const callIndex = prevCalls.findIndex(c => c.id === update.callId);
      if (callIndex === -1) return prevCalls;

      const current = prevCalls[callIndex];
      const newRiskLevel = getRiskLevel(update.risk);
      const formattedTime = formatSeconds(update.timestamp);

      // Check if new detection event should be added
      const existingEvents = [...current.detectionEvents];
      const isNewTimestamp = !existingEvents.some(e => Math.abs(e.timestamp - update.timestamp) < 2);

      if (isNewTimestamp && (update.risk >= 40 || update.timestamp === 4 || update.timestamp === 18)) {
        let desc = `Acoustic variance monitored: risk ${update.risk}%`;
        let eventType: DetectionEvent['eventType'] = 'acoustic_drift';

        if (update.risk >= 70) {
          desc = `POSSIBLE SYNTHETIC VOICE: High-probability vocoder artifacts detected (${update.syntheticProbability}%).`;
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
          syntheticProbability: update.syntheticProbability,
          severity: newRiskLevel,
          eventType,
          description: desc,
          confidence: update.confidence,
          audioSegmentAvailable: update.risk >= 70
        });
      }

      // Append to risk history
      const updatedHistory = [
        ...current.riskHistory,
        {
          timestamp: update.timestamp,
          risk: update.risk,
          syntheticProbability: update.syntheticProbability
        }
      ].slice(-30); // keep last 30 data points

      const updatedCall: Call = {
        ...current,
        durationSeconds: Math.max(current.durationSeconds, update.timestamp),
        currentRisk: update.risk,
        currentRiskLevel: newRiskLevel,
        syntheticProbability: update.syntheticProbability,
        speakerConsistency: update.speakerConsistency,
        contextRisk: update.contextRisk,
        confidence: update.confidence,
        monitoringState: update.monitoringState || (update.risk >= 70 ? 'ALERT_TRIGGERED' : update.risk >= 40 ? 'SUSPICIOUS' : 'MONITORING_ACTIVE'),
        status: update.risk >= 70 ? 'FLAGGED' : current.status === 'FLAGGED' ? 'FLAGGED' : 'ACTIVE',
        detectionEvents: existingEvents,
        riskHistory: updatedHistory,
        evidence: update.risk >= 70 ? (current.evidence || INITIAL_EVIDENCE_1042) : current.evidence
      };

      // Trigger High Risk Security Alert if >= 70 and not already acknowledged
      if (update.risk >= 70 && (!securityAlert || securityAlert.callId !== update.callId)) {
        setSecurityAlert({
          id: `alert-${update.callId}-${Date.now()}`,
          callId: update.callId,
          callerName: current.caller.name,
          risk: update.risk,
          syntheticProbability: update.syntheticProbability,
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
  }, [securityAlert]);

  // Subscribe to WebSocket updates and status
  useEffect(() => {
    const unsubMsg = wsService.onMessage(handleRiskUpdate);
    const unsubStatus = wsService.onStatusChange((status, message) => {
      setWsStatus(status);
      setWsMessage(message || '');
    });

    // Start Demo Simulator on mount if in demo mode
    if (isDemoMode) {
      demoSimulator.start('1042');
    } else {
      wsService.connect();
    }

    return () => {
      unsubMsg();
      unsubStatus();
      demoSimulator.stop();
      wsService.disconnect();
    };
  }, [handleRiskUpdate, isDemoMode]);

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

  const startCall = (callerName: string = 'Rahul'): string => {
    const newId = (1045 + Math.floor(Math.random() * 100)).toString();
    const newCall: Call = {
      id: newId,
      caller: {
        id: `usr-${newId}`,
        name: callerName,
        phone: '+1 (555) 019-4821',
        organization: 'Verified Client',
        department: 'Operations',
        trustScore: 90,
        language: 'English (US)',
        isKnownContact: true
      },
      receiver: 'Security Operations',
      startTime: new Date().toISOString(),
      durationSeconds: 0,
      currentRisk: 18,
      currentRiskLevel: 'LOW',
      syntheticProbability: 20,
      speakerConsistency: 95,
      contextRisk: 15,
      confidence: 'LOW',
      status: 'ACTIVE',
      monitoringState: 'INITIALIZING',
      detectionEvents: [],
      riskHistory: [{ timestamp: 0, risk: 18, syntheticProbability: 20 }],
      protocol: 'WebRTC',
      codec: 'Opus/48kHz',
      packetLoss: 0.05,
      latencyMs: 18,
      isSimulatedDemo: isDemoMode
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
    const callToEnd = activeCalls.find(c => c.id === targetId);
    if (!callToEnd) return;

    // Backend 1 live-audio teardown (idempotent by design of both services).
    // Centralized here so audio cleanup cannot be skipped when a call is
    // terminated from another existing path (Dashboard terminate,
    // InvestigationModal, MobileApp). Order: capture first, then socket.
    audioCapture.stop();
    audioStream.disconnect();

    const endedCall: Call = {
      ...callToEnd,
      status: 'ENDED',
      monitoringState: 'COMPLETED'
    };

    setActiveCalls(prev => prev.filter(c => c.id !== targetId));
    setCallHistory(prev => [endedCall, ...prev]);

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
      wsService.disconnect();
      demoSimulator.start('1042');
    } else {
      demoSimulator.stop();
      wsService.connect();
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
        selectCall,
        startCall,
        endCall,
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
