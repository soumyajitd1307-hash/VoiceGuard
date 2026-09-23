import { Call, DetectionEvent, Evidence, SystemStatus, SecurityAlert } from '../types';

export const INITIAL_EVIDENCE_1042: Evidence = {
  id: 'ev-1042-01',
  callId: '1042',
  timestamp: 18,
  formattedTime: '00:18',
  durationSeconds: 4.5,
  waveform: [
    0.15, 0.28, 0.45, 0.72, 0.95, 0.88, 0.65, 0.42, 0.81, 0.94,
    0.98, 0.75, 0.58, 0.32, 0.48, 0.68, 0.89, 0.96, 0.91, 0.72,
    0.54, 0.38, 0.62, 0.84, 0.97, 0.86, 0.64, 0.45, 0.31, 0.18
  ],
  syntheticProbability: 91,
  speakerConsistency: 64,
  contextRisk: 90,
  overallRisk: 84,
  detectionType: 'Neural Vocoder Residuals & Pitch Quantization',
  anomalyNotes: [
    'Unnatural phase coherence in 3.5kHz - 7kHz high-frequency band',
    'Robotic pitch flattening: F0 standard deviation below human threshold (3.2Hz vs expected 18Hz)',
    'High context risk: Caller requested urgent wire transfer authentication bypass'
  ],
  recommendedAction: 'Immediate Call Disconnect & Mandatory Multi-Factor Biometric Verification'
};

export const INITIAL_DETECTION_EVENTS_1042: DetectionEvent[] = [
  {
    id: 'evt-1',
    callId: '1042',
    timestamp: 4,
    formattedTime: '00:04',
    risk: 18,
    syntheticProbability: 42,
    severity: 'LOW',
    eventType: 'baseline',
    description: 'Initial voice stream baseline established. Speaker pitch: 142Hz.',
    confidence: 'LOW'
  },
  {
    id: 'evt-2',
    callId: '1042',
    timestamp: 9,
    formattedTime: '00:09',
    risk: 27,
    syntheticProbability: 58,
    severity: 'LOW',
    eventType: 'acoustic_drift',
    description: 'Micro-drift in vocal tract resonances detected during continuous vowel phonation.',
    confidence: 'MEDIUM'
  },
  {
    id: 'evt-3',
    callId: '1042',
    timestamp: 14,
    formattedTime: '00:14',
    risk: 43,
    syntheticProbability: 73,
    severity: 'MEDIUM',
    eventType: 'vocoder_artifact',
    description: 'Comb filtering artifacts detected. Harmonics mismatch with human glottal pulse.',
    confidence: 'MEDIUM'
  },
  {
    id: 'evt-4',
    callId: '1042',
    timestamp: 18,
    formattedTime: '00:18',
    risk: 84,
    syntheticProbability: 89,
    severity: 'HIGH',
    eventType: 'deepfake_confirmed',
    description: 'High-confidence neural speech synthesis detected. F0 perturbation exceeds synthetic threshold.',
    confidence: 'HIGH',
    audioSegmentAvailable: true
  }
];

export const MOCK_ACTIVE_CALLS: Call[] = [
  {
    id: '1042',
    caller: {
      id: 'usr-1042',
      name: 'Rahul',
      phone: '+1 (555) 382-9014',
      organization: 'FinCorp Treasury',
      department: 'Finance Ops',
      trustScore: 32,
      language: 'English (US)',
      isKnownContact: true
    },
    receiver: 'Security Dispatch (VoIP Line 1)',
    startTime: new Date(Date.now() - 18000).toISOString(),
    durationSeconds: 18,
    currentRisk: 84,
    currentRiskLevel: 'HIGH',
    syntheticProbability: 91,
    speakerConsistency: 64,
    contextRisk: 90,
    confidence: 'HIGH',
    status: 'FLAGGED',
    monitoringState: 'ALERT_TRIGGERED',
    detectionEvents: INITIAL_DETECTION_EVENTS_1042,
    riskHistory: [
      { timestamp: 0, risk: 18, syntheticProbability: 25 },
      { timestamp: 4, risk: 24, syntheticProbability: 42 },
      { timestamp: 9, risk: 36, syntheticProbability: 58 },
      { timestamp: 14, risk: 61, syntheticProbability: 73 },
      { timestamp: 18, risk: 84, syntheticProbability: 91 }
    ],
    evidence: INITIAL_EVIDENCE_1042,
    protocol: 'WebRTC',
    codec: 'Opus/48kHz',
    packetLoss: 0.12,
    latencyMs: 24,
    isSimulatedDemo: true
  },
  {
    id: '1043',
    caller: {
      id: 'usr-1043',
      name: 'Souvik',
      phone: '+1 (555) 891-2309',
      organization: 'Engineering',
      department: 'Core Infra',
      trustScore: 94,
      language: 'English / Bengali',
      isKnownContact: true
    },
    receiver: 'Customer Support (VoIP Line 2)',
    startTime: new Date(Date.now() - 65000).toISOString(),
    durationSeconds: 65,
    currentRisk: 21,
    currentRiskLevel: 'LOW',
    syntheticProbability: 14,
    speakerConsistency: 96,
    contextRisk: 12,
    confidence: 'HIGH',
    status: 'ACTIVE',
    monitoringState: 'MONITORING_ACTIVE',
    detectionEvents: [
      {
        id: 'evt-1043-1',
        callId: '1043',
        timestamp: 10,
        formattedTime: '00:10',
        risk: 20,
        syntheticProbability: 14,
        severity: 'LOW',
        eventType: 'baseline',
        description: 'Natural voice profile matched with authenticated voiceprint template.',
        confidence: 'HIGH'
      }
    ],
    riskHistory: [
      { timestamp: 0, risk: 15, syntheticProbability: 10 },
      { timestamp: 20, risk: 19, syntheticProbability: 12 },
      { timestamp: 45, risk: 22, syntheticProbability: 15 },
      { timestamp: 65, risk: 21, syntheticProbability: 14 }
    ],
    protocol: 'WebRTC',
    codec: 'Opus/48kHz',
    packetLoss: 0.05,
    latencyMs: 19
  },
  {
    id: '1044',
    caller: {
      id: 'usr-1044',
      name: 'Unknown Caller',
      phone: '+44 20 7946 0912',
      organization: 'Unverified External IP',
      department: 'Inbound SIP Gateway',
      trustScore: 48,
      language: 'English (UK)',
      isKnownContact: false
    },
    receiver: 'Executive Desk (Direct Line)',
    startTime: new Date(Date.now() - 42000).toISOString(),
    durationSeconds: 42,
    currentRisk: 57,
    currentRiskLevel: 'MEDIUM',
    syntheticProbability: 61,
    speakerConsistency: 71,
    contextRisk: 68,
    confidence: 'MEDIUM',
    status: 'ACTIVE',
    monitoringState: 'SUSPICIOUS',
    detectionEvents: [
      {
        id: 'evt-1044-1',
        callId: '1044',
        timestamp: 12,
        formattedTime: '00:12',
        risk: 42,
        syntheticProbability: 49,
        severity: 'MEDIUM',
        eventType: 'pitch_flattening',
        description: 'Vocal pitch perturbation variance unusually low. Evaluating prosody.',
        confidence: 'MEDIUM'
      },
      {
        id: 'evt-1044-2',
        callId: '1044',
        timestamp: 30,
        formattedTime: '00:30',
        risk: 57,
        syntheticProbability: 61,
        severity: 'MEDIUM',
        eventType: 'acoustic_drift',
        description: 'Suspected real-time voice conversion filter active.',
        confidence: 'MEDIUM'
      }
    ],
    riskHistory: [
      { timestamp: 0, risk: 30, syntheticProbability: 35 },
      { timestamp: 15, risk: 44, syntheticProbability: 48 },
      { timestamp: 30, risk: 55, syntheticProbability: 59 },
      { timestamp: 42, risk: 57, syntheticProbability: 61 }
    ],
    protocol: 'SIP',
    codec: 'G.711',
    packetLoss: 0.45,
    latencyMs: 62
  }
];

export const MOCK_CALL_HISTORY: Call[] = [
  {
    id: '1041',
    caller: {
      id: 'usr-1041',
      name: 'Anita Roy',
      phone: '+1 (555) 720-4491',
      organization: 'Acme Systems',
      trustScore: 82,
      language: 'English',
      isKnownContact: true
    },
    receiver: 'Billing Support',
    startTime: new Date(Date.now() - 3600000).toISOString(),
    durationSeconds: 245,
    currentRisk: 42,
    currentRiskLevel: 'MEDIUM',
    syntheticProbability: 45,
    speakerConsistency: 78,
    contextRisk: 38,
    confidence: 'MEDIUM',
    status: 'ENDED',
    monitoringState: 'COMPLETED',
    detectionEvents: [],
    riskHistory: [
      { timestamp: 0, risk: 20, syntheticProbability: 15 },
      { timestamp: 100, risk: 42, syntheticProbability: 45 },
      { timestamp: 245, risk: 38, syntheticProbability: 40 }
    ],
    protocol: 'WebRTC',
    codec: 'Opus/48kHz',
    packetLoss: 0.08,
    latencyMs: 22
  },
  {
    id: '1040',
    caller: {
      id: 'usr-1040',
      name: 'Amit Sharma',
      phone: '+1 (555) 439-0192',
      organization: 'Security Threat Actor',
      trustScore: 12,
      language: 'Hindi / English',
      isKnownContact: false
    },
    receiver: 'VIP Private Line',
    startTime: new Date(Date.now() - 7200000).toISOString(),
    durationSeconds: 94,
    currentRisk: 88,
    currentRiskLevel: 'HIGH',
    syntheticProbability: 95,
    speakerConsistency: 42,
    contextRisk: 94,
    confidence: 'HIGH',
    status: 'FLAGGED',
    monitoringState: 'COMPLETED',
    detectionEvents: [
      {
        id: 'evt-1040-1',
        callId: '1040',
        timestamp: 15,
        formattedTime: '00:15',
        risk: 88,
        syntheticProbability: 95,
        severity: 'HIGH',
        eventType: 'deepfake_confirmed',
        description: 'Zero-shot voice clone targeting C-Level executive.',
        confidence: 'HIGH',
        audioSegmentAvailable: true
      }
    ],
    riskHistory: [
      { timestamp: 0, risk: 25, syntheticProbability: 30 },
      { timestamp: 30, risk: 72, syntheticProbability: 80 },
      { timestamp: 60, risk: 88, syntheticProbability: 95 }
    ],
    protocol: 'WebRTC',
    codec: 'Opus/48kHz',
    packetLoss: 0.22,
    latencyMs: 31
  },
  {
    id: '1039',
    caller: {
      id: 'usr-1039',
      name: 'Priya Nair',
      phone: '+1 (555) 129-8472',
      organization: 'FinCorp Audit',
      trustScore: 98,
      language: 'English',
      isKnownContact: true
    },
    receiver: 'Compliance Hotline',
    startTime: new Date(Date.now() - 14400000).toISOString(),
    durationSeconds: 512,
    currentRisk: 15,
    currentRiskLevel: 'LOW',
    syntheticProbability: 9,
    speakerConsistency: 99,
    contextRisk: 8,
    confidence: 'HIGH',
    status: 'ENDED',
    monitoringState: 'COMPLETED',
    detectionEvents: [],
    riskHistory: [
      { timestamp: 0, risk: 12, syntheticProbability: 8 },
      { timestamp: 250, risk: 15, syntheticProbability: 10 },
      { timestamp: 512, risk: 14, syntheticProbability: 9 }
    ],
    protocol: 'WebRTC',
    codec: 'Opus/48kHz',
    packetLoss: 0.02,
    latencyMs: 16
  }
];

export const INITIAL_SYSTEM_STATUS: SystemStatus = {
  serviceStatus: 'OPERATIONAL',
  activeCallsCount: 3,
  totalCallsAnalyzed: 1428,
  highRiskCallsCount: 2,
  aiEngineLatencyMs: 24,
  modelAccuracy: 99.4,
  modelVersion: 'VoiceGuard Neural-v3.4.2',
  webrtcNodesHealthy: 12,
  webrtcNodesTotal: 12,
  wsConnections: 38,
  uptimeSeconds: 846200
};

export const INITIAL_SECURITY_ALERT_1042: SecurityAlert = {
  id: 'alt-1042',
  callId: '1042',
  callerName: 'Rahul',
  risk: 84,
  syntheticProbability: 91,
  detectionTime: '00:18',
  confidence: 'HIGH',
  message: 'POSSIBLE SYNTHETIC VOICE DETECTED',
  timestamp: new Date().toLocaleTimeString(),
  status: 'ACTIVE',
  suggestedAction: 'Isolate Call & Force Secondary Multi-Factor Verification'
};
