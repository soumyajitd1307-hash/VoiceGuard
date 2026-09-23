import { RiskUpdate, ConfidenceLevel, MonitoringState } from '../types';
import { wsService } from './websocket';

export interface DemoStep {
  second: number;
  risk: number;
  syntheticProbability: number;
  speakerConsistency: number;
  contextRisk: number;
  confidence: ConfidenceLevel;
  monitoringState: MonitoringState;
  logMessage: string;
}

export const DEMO_STAGES: DemoStep[] = [
  {
    second: 0,
    risk: 18,
    syntheticProbability: 22,
    speakerConsistency: 96,
    contextRisk: 15,
    confidence: 'LOW',
    monitoringState: 'INITIALIZING',
    logMessage: 'Establishing WebRTC Opus session. Baseline voice model initialized.'
  },
  {
    second: 5,
    risk: 27,
    syntheticProbability: 38,
    speakerConsistency: 92,
    contextRisk: 25,
    confidence: 'LOW',
    monitoringState: 'MONITORING_ACTIVE',
    logMessage: '00:05 Speech spectral analysis active. Jitter 1.2ms, formant tracks normal.'
  },
  {
    second: 10,
    risk: 43,
    syntheticProbability: 62,
    speakerConsistency: 79,
    contextRisk: 55,
    confidence: 'MEDIUM',
    monitoringState: 'SUSPICIOUS',
    logMessage: '00:10 Micro-acoustic drift detected in high-frequency spectral envelope.'
  },
  {
    second: 14,
    risk: 61,
    syntheticProbability: 78,
    speakerConsistency: 68,
    contextRisk: 74,
    confidence: 'MEDIUM',
    monitoringState: 'SUSPICIOUS',
    logMessage: '00:14 Neural vocoder artifacts identified. Glottal wave symmetry abnormal.'
  },
  {
    second: 18,
    risk: 84,
    syntheticProbability: 91,
    speakerConsistency: 64,
    contextRisk: 90,
    confidence: 'HIGH',
    monitoringState: 'ALERT_TRIGGERED',
    logMessage: '00:18 CRITICAL: High-probability synthetic speech verified. Deepfake alert triggered!'
  }
];

class DemoSimulator {
  private timer: number | null = null;
  private currentSecond = 0;
  private isRunning = false;
  private callId = '1042';
  private listeners: Set<(step: DemoStep, isRunning: boolean) => void> = new Set();

  public isSimulating(): boolean {
    return this.isRunning;
  }

  public getCurrentSecond(): number {
    return this.currentSecond;
  }

  public subscribe(cb: (step: DemoStep, isRunning: boolean) => void): () => void {
    this.listeners.add(cb);
    return () => this.listeners.delete(cb);
  }

  private notify(step: DemoStep): void {
    this.listeners.forEach(cb => cb(step, this.isRunning));
  }

  public start(callId: string = '1042'): void {
    this.stop();
    this.callId = callId;
    this.currentSecond = 0;
    this.isRunning = true;

    // Emit 0s immediately
    this.emitForSecond(0);

    this.timer = window.setInterval(() => {
      this.currentSecond += 1;
      this.emitForSecond(this.currentSecond);

      if (this.currentSecond >= 25) {
        // Hold at max or pause
        this.pause();
      }
    }, 1000);
  }

  public pause(): void {
    if (this.timer) {
      clearInterval(this.timer);
      this.timer = null;
    }
    this.isRunning = false;
    const step = this.calculateInterpolatedStep(this.currentSecond);
    this.notify(step);
  }

  public resume(): void {
    if (this.isRunning) return;
    this.isRunning = true;

    this.timer = window.setInterval(() => {
      this.currentSecond += 1;
      this.emitForSecond(this.currentSecond);

      if (this.currentSecond >= 30) {
        this.pause();
      }
    }, 1000);
  }

  public jumpToSecond(sec: number): void {
    this.currentSecond = sec;
    this.emitForSecond(sec);
  }

  public reset(): void {
    this.stop();
    this.currentSecond = 0;
    this.emitForSecond(0);
  }

  public stop(): void {
    if (this.timer) {
      clearInterval(this.timer);
      this.timer = null;
    }
    this.isRunning = false;
  }

  private emitForSecond(sec: number): void {
    const step = this.calculateInterpolatedStep(sec);

    const update: RiskUpdate = {
      type: 'risk_update',
      callId: this.callId,
      timestamp: sec,
      risk: step.risk,
      syntheticProbability: step.syntheticProbability,
      speakerConsistency: step.speakerConsistency,
      contextRisk: step.contextRisk,
      confidence: step.confidence,
      monitoringState: step.monitoringState
    };

    // Broadcast into the WebSocket event pipeline!
    wsService.broadcastMessage(update);
    this.notify(step);
  }

  private calculateInterpolatedStep(sec: number): DemoStep {
    if (sec <= 0) return DEMO_STAGES[0];
    if (sec >= 18) {
      // Add slight jitter around 84 to look alive
      const jitter = Math.sin(sec) * 1.5;
      const risk = Math.min(100, Math.max(75, Math.round(84 + jitter)));
      return {
        ...DEMO_STAGES[4],
        second: sec,
        risk,
        syntheticProbability: Math.min(99, Math.round(91 + jitter * 0.8))
      };
    }

    // Find bounding stages
    for (let i = 0; i < DEMO_STAGES.length - 1; i++) {
      const s1 = DEMO_STAGES[i];
      const s2 = DEMO_STAGES[i + 1];
      if (sec >= s1.second && sec <= s2.second) {
        const factor = (sec - s1.second) / (s2.second - s1.second);
        const risk = Math.round(s1.risk + factor * (s2.risk - s1.risk));
        const syntheticProbability = Math.round(s1.syntheticProbability + factor * (s2.syntheticProbability - s1.syntheticProbability));
        const speakerConsistency = Math.round(s1.speakerConsistency + factor * (s2.speakerConsistency - s1.speakerConsistency));
        const contextRisk = Math.round(s1.contextRisk + factor * (s2.contextRisk - s1.contextRisk));
        const confidence = factor > 0.5 ? s2.confidence : s1.confidence;
        const monitoringState = factor > 0.5 ? s2.monitoringState : s1.monitoringState;

        return {
          second: sec,
          risk,
          syntheticProbability,
          speakerConsistency,
          contextRisk,
          confidence,
          monitoringState,
          logMessage: `00:${sec < 10 ? '0' + sec : sec} Synthetic prob: ${syntheticProbability}%, Risk: ${risk}`
        };
      }
    }

    return DEMO_STAGES[DEMO_STAGES.length - 1];
  }
}

export const demoSimulator = new DemoSimulator();
