export type RiskLevel = 'LOW' | 'MEDIUM' | 'HIGH';

export type MonitoringState = 
  | 'INITIALIZING'
  | 'ANALYZING'
  | 'MONITORING_ACTIVE'
  | 'SUSPICIOUS'
  | 'ALERT_TRIGGERED'
  | 'COMPLETED';

export type ConfidenceLevel = 'LOW' | 'MEDIUM' | 'HIGH';

export interface Caller {
  id: string;
  name: string;
  phone: string;
  avatarUrl?: string;
  organization?: string;
  department?: string;
  trustScore: number; // 0-100
  language: string;
  isKnownContact: boolean;
}

export interface RiskUpdate {
  type: 'risk_update';
  callId: string;
  timestamp: number; // seconds from call start
  risk: number; // 0-100
  syntheticProbability: number; // 0-100 %
  speakerConsistency: number; // 0-100 %
  contextRisk: number; // 0-100 %
  confidence: ConfidenceLevel;
  monitoringState?: MonitoringState;
  frequencyArtifacts?: number; // 0-100 %
  prosodyAnomaly?: number; // 0-100 %
  spectralFlux?: number;
}

export interface DetectionEvent {
  id: string;
  callId: string;
  timestamp: number; // seconds into call
  formattedTime: string; // e.g. "00:18"
  risk: number;
  syntheticProbability: number;
  severity: RiskLevel;
  eventType: 'baseline' | 'acoustic_drift' | 'vocoder_artifact' | 'pitch_flattening' | 'synthetic_detection' | 'deepfake_confirmed';
  description: string;
  confidence: ConfidenceLevel;
  audioSegmentAvailable?: boolean;
}

export interface Evidence {
  id: string;
  callId: string;
  timestamp: number; // seconds
  formattedTime: string;
  durationSeconds: number;
  audioUrl?: string; // Real or synthetic Web Audio API source
  waveform: number[]; // Array of normalized amplitude points
  syntheticProbability: number;
  speakerConsistency: number;
  contextRisk: number;
  overallRisk: number;
  detectionType: string;
  anomalyNotes: string[];
  spectrogramUrl?: string;
  recommendedAction: string;
}

export interface Call {
  id: string;
  caller: Caller;
  receiver: string;
  startTime: string; // ISO date string
  durationSeconds: number;
  currentRisk: number; // 0-100
  currentRiskLevel: RiskLevel;
  syntheticProbability: number;
  speakerConsistency: number;
  contextRisk: number;
  confidence: ConfidenceLevel;
  status: 'ACTIVE' | 'ENDED' | 'FLAGGED' | 'INVESTIGATING';
  monitoringState: MonitoringState;
  detectionEvents: DetectionEvent[];
  riskHistory: { timestamp: number; risk: number; syntheticProbability: number }[];
  evidence?: Evidence;
  protocol: 'WebRTC' | 'SIP' | 'VoIP-TLS';
  codec: 'Opus/48kHz' | 'G.711' | 'AAC-LD';
  packetLoss: number;
  latencyMs: number;
  isSimulatedDemo?: boolean;
}

export interface SecurityAlert {
  id: string;
  callId: string;
  callerName: string;
  risk: number;
  syntheticProbability: number;
  detectionTime: string;
  confidence: ConfidenceLevel;
  message: string;
  timestamp: string;
  status: 'ACTIVE' | 'ACKNOWLEDGED' | 'RESOLVED' | 'DISMISSED';
  suggestedAction: string;
}

export interface SystemStatus {
  serviceStatus: 'OPERATIONAL' | 'DEGRADED' | 'OUTAGE';
  activeCallsCount: number;
  totalCallsAnalyzed: number;
  highRiskCallsCount: number;
  aiEngineLatencyMs: number;
  modelAccuracy: number;
  modelVersion: string;
  webrtcNodesHealthy: number;
  webrtcNodesTotal: number;
  wsConnections: number;
  uptimeSeconds: number;
}

export type WSConnectionStatus = 'CONNECTING' | 'CONNECTED' | 'DISCONNECTED' | 'RECONNECTING' | 'ERROR';
