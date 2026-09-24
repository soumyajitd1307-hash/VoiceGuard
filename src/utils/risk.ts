import { RiskLevel, ConfidenceLevel } from '../types';

/**
 * VoiceGuard Risk Classification Engine
 * 0–39 = LOW
 * 40–69 = MEDIUM
 * 70–100 = HIGH
 */

export function getRiskLevel(score: number): RiskLevel {
  if (score < 40) return 'LOW';
  if (score < 70) return 'MEDIUM';
  return 'HIGH';
}

export interface RiskTheme {
  primary: string;
  bgLight: string;
  bgDark: string;
  border: string;
  text: string;
  badgeBg: string;
  glow: string;
  pulseColor: string;
}

export function getRiskTheme(scoreOrLevel: number | RiskLevel): RiskTheme {
  const level: RiskLevel = typeof scoreOrLevel === 'number' 
    ? getRiskLevel(scoreOrLevel) 
    : scoreOrLevel;

  switch (level) {
    case 'LOW':
      return {
        primary: '#10b981', // emerald-500
        bgLight: 'rgba(16, 185, 129, 0.12)',
        bgDark: 'rgba(6, 78, 59, 0.35)',
        border: 'rgba(16, 185, 129, 0.35)',
        text: '#34d399',
        badgeBg: '#064e3b',
        glow: '0 0 15px rgba(16, 185, 129, 0.4)',
        pulseColor: '#10b981',
      };
    case 'MEDIUM':
      return {
        primary: '#f59e0b', // amber-500
        bgLight: 'rgba(245, 158, 11, 0.12)',
        bgDark: 'rgba(120, 53, 15, 0.35)',
        border: 'rgba(245, 158, 11, 0.4)',
        text: '#fbbf24',
        badgeBg: '#78350f',
        glow: '0 0 15px rgba(245, 158, 11, 0.4)',
        pulseColor: '#f59e0b',
      };
    case 'HIGH':
      return {
        primary: '#ef4444', // red-500
        bgLight: 'rgba(239, 68, 68, 0.16)',
        bgDark: 'rgba(127, 29, 29, 0.45)',
        border: 'rgba(239, 68, 68, 0.5)',
        text: '#f87171',
        badgeBg: '#7f1d1d',
        glow: '0 0 20px rgba(239, 68, 68, 0.6)',
        pulseColor: '#ef4444',
      };
  }
}

export interface RiskStatusSummary {
  title: string;
  subtitle: string;
  recommendation: string;
  isThreat: boolean;
  level: RiskLevel;
}

export function getRiskStatusSummary(score: number, confidence: ConfidenceLevel = 'HIGH'): RiskStatusSummary {
  const level = getRiskLevel(score);

  if (level === 'LOW') {
    return {
      title: 'VOICE INTEGRITY VERIFIED',
      subtitle: 'Voice appears natural',
      recommendation: 'Biometric harmonics consistent with human vocal tract. No synthetic artifacts detected.',
      isThreat: false,
      level,
    };
  }

  if (level === 'MEDIUM') {
    return {
      title: 'ACOUSTIC ANOMALY DETECTED',
      subtitle: 'Potential synthetic distortion',
      recommendation: 'Elevated spectral flatness and robotic timbre detected. Exercise caution on sensitive disclosures.',
      isThreat: false,
      level,
    };
  }

  return {
    title: 'POSSIBLE SYNTHETIC VOICE',
    subtitle: `HIGH RISK (${score}/100) • Confidence: ${confidence}`,
    recommendation: 'Independent verification recommended. Neural vocoder markers and cloned speech patterns detected.',
    isThreat: true,
    level,
  };
}

export interface RiskHistoryPoint {
  timestamp: number;
  risk: number;
  syntheticProbability: number;
}

export function formatSeconds(seconds: number): string {
  const mins = Math.floor(seconds / 60);
  const secs = seconds % 60;
  return `${mins.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`;
}

export function formatPercent(value: number): string {
  return `${Math.round(value)}%`;
}

/**
 * Append one B4 RiskUpdate to a call's risk history, verbatim.
 * Values are copied exactly as received — no interpolation, no
 * smoothing, no normalization, no fabricated points. History is capped
 * at the newest 30 points. Pure (headless-testable).
 */
export function appendRiskPoint(
  history: RiskHistoryPoint[],
  point: { timestamp: number; risk: number; syntheticProbability: number },
  cap = 30,
): RiskHistoryPoint[] {
  return [
    ...history,
    {
      timestamp: point.timestamp,
      risk: point.risk,
      syntheticProbability: point.syntheticProbability,
    },
  ].slice(-cap);
}
