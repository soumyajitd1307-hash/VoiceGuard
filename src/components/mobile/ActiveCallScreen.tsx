import React, { useState, useEffect } from 'react';
import { PhoneOff, Mic, Volume2, ShieldAlert, ShieldCheck, Activity, Globe, Info, AlertTriangle } from 'lucide-react';
import { Call } from '../../types';
import { CallerAvatar } from '../common/CallerAvatar';
import { RiskGauge } from '../common/RiskGauge';
import { CallTimer } from '../common/CallTimer';
import { getRiskLevel, getRiskTheme, getRiskStatusSummary } from '../../utils/risk';
import { useCallContext } from '../../context/CallContext';

/**
 * Real Backend 1 audio transport state, owned by MobileApp and derived
 * only from audioCapture/audioStream lifecycle events (never simulated).
 *   connecting    — start in progress (connect/capture awaiting)
 *   active        — capture running AND socket open (frames flowing)
 *   disconnected  — startup failure, mid-call drop, cleanup, or no session
 */
export type LiveAudioState = 'connecting' | 'active' | 'disconnected';

interface ActiveCallScreenProps {
  call: Call;
  onEndCall: () => void;
  onOpenEvidence?: () => void;
  audioState: LiveAudioState;
}

const AUDIO_STATUS_META: Record<
  LiveAudioState,
  { label: string; color: string; bg: string; border: string }
> = {
  connecting: {
    label: 'Microphone connecting',
    color: '#fbbf24',
    bg: 'rgba(245, 158, 11, 0.12)',
    border: 'rgba(245, 158, 11, 0.35)'
  },
  active: {
    label: 'Microphone active',
    color: '#34d399',
    bg: 'rgba(16, 185, 129, 0.12)',
    border: 'rgba(16, 185, 129, 0.35)'
  },
  disconnected: {
    label: 'Audio connection disconnected/error',
    color: '#f87171',
    bg: 'rgba(239, 68, 68, 0.12)',
    border: 'rgba(239, 68, 68, 0.4)'
  }
};

export const ActiveCallScreen: React.FC<ActiveCallScreenProps> = ({
  call,
  onEndCall,
  onOpenEvidence,
  audioState
}) => {
  const isHigh = call.currentRiskLevel === 'HIGH';
  const isSuspicious = call.currentRiskLevel === 'MEDIUM';
  const theme = getRiskTheme(call.currentRiskLevel);
  const summary = getRiskStatusSummary(call.currentRisk, call.confidence);
  const audioStatus = AUDIO_STATUS_META[audioState];
  const { isDemoMode } = useCallContext();
  // No fabricated initial risk: until the first real RiskUpdate lands
  // (empty history, live mode), show a neutral monitoring state instead
  // of a "verified" claim the backend never made.
  const awaitingAnalysis = !isDemoMode && call.riskHistory.length === 0;
  const bannerTitle = awaitingAnalysis ? 'AWAITING ANALYSIS' : summary.title;
  const bannerRecommendation = awaitingAnalysis
    ? 'Monitoring live audio — first backend assessment pending.'
    : summary.recommendation;

  // Voice bars animate ONLY while real microphone frames are flowing
  // (audioState === 'active', set by MobileApp from the actual capture
  // lifecycle) or in demo theater mode. Otherwise they stay flat — random
  // motion would fake live audio that isn't there.
  const FLAT_BARS = [10, 10, 10, 10, 10, 10, 10, 10, 10];
  const [waveHeights, setWaveHeights] = useState<number[]>(FLAT_BARS);

  useEffect(() => {
    if (audioState !== 'active' && !isDemoMode) {
      setWaveHeights(FLAT_BARS);
      return;
    }
    const interval = setInterval(() => {
      setWaveHeights(prev =>
        prev.map(() => {
          const base = isHigh ? 36 : 20;
          return Math.floor(Math.random() * base) + 8;
        })
      );
    }, 180);
    return () => clearInterval(interval);
  }, [isHigh, audioState, isDemoMode]);

  return (
    <div
      style={{
        flex: 1,
        display: 'flex',
        flexDirection: 'column',
        justifyContent: 'space-between',
        padding: '16px 18px 24px',
        background: isHigh
          ? 'radial-gradient(circle at top, #2b0c0c 0%, #090e18 70%)'
          : 'radial-gradient(circle at top, #0f1c36 0%, #090e18 70%)',
        overflowY: 'auto',
        position: 'relative',
        transition: 'background 0.5s ease'
      }}
    >
      {/* Top Banner: LIVE MONITORING BEACON */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', paddingTop: '6px' }}>
        <div
          style={{
            display: 'inline-flex',
            alignItems: 'center',
            gap: '8px',
            background: isHigh ? 'rgba(239, 68, 68, 0.18)' : 'rgba(16, 185, 129, 0.15)',
            border: `1px solid ${isHigh ? 'rgba(239, 68, 68, 0.4)' : 'rgba(16, 185, 129, 0.3)'}`,
            padding: '4px 12px',
            borderRadius: '20px'
          }}
        >
          <span
            style={{
              width: '8px',
              height: '8px',
              borderRadius: '50%',
              backgroundColor: theme.primary,
              boxShadow: `0 0 8px ${theme.primary}`,
              animation: isHigh ? 'pulse-high-threat 1s infinite' : 'pulse-radar 2s infinite'
            }}
          />
          <span
            style={{
              fontSize: '11px',
              fontWeight: 800,
              letterSpacing: '0.08em',
              color: theme.text,
              textTransform: 'uppercase'
            }}
          >
            LIVE MONITORING
          </span>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '11px', color: 'var(--text-dim)' }}>
          <Globe size={12} />
          <span>{call.caller.language}</span>
        </div>
      </div>

      {/* Compact live audio/microphone status (real Backend 1 transport state) */}
      <div style={{ display: 'flex', justifyContent: 'center', marginTop: '8px' }}>
        <div
          style={{
            display: 'inline-flex',
            alignItems: 'center',
            gap: '6px',
            padding: '3px 10px',
            borderRadius: '14px',
            background: audioStatus.bg,
            border: `1px solid ${audioStatus.border}`
          }}
        >
          <Mic size={11} style={{ color: audioStatus.color, flexShrink: 0 }} />
          <span
            style={{
              fontSize: '10px',
              fontWeight: 800,
              letterSpacing: '0.06em',
              textTransform: 'uppercase',
              color: audioStatus.color
            }}
          >
            {audioStatus.label}
          </span>
        </div>
      </div>

      {/* Caller Info Header */}
      <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', textAlign: 'center', marginTop: '10px' }}>
        <CallerAvatar caller={call.caller} size={64} isHighRisk={isHigh} />
        <h2 style={{ fontSize: '18px', fontWeight: 800, color: 'var(--text-main)', marginTop: '8px' }}>
          {call.caller.name}
        </h2>
        <div style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '12px', color: 'var(--text-muted)', marginTop: '2px' }}>
          <span>Call #{call.id}</span>
          <span>•</span>
          <CallTimer initialSeconds={call.durationSeconds} />
        </div>
      </div>

      {/* Primary Voice Integrity Dial */}
      <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', margin: '4px 0' }}>
        <RiskGauge
          score={call.currentRisk}
          size={175}
          label={isHigh ? 'SYNTHETIC RISK' : 'VOICE INTEGRITY'}
          sublabel={isHigh ? 'HIGH RISK' : isSuspicious ? 'MEDIUM RISK' : 'LOW RISK'}
        />

        {/* State Banner: Normal vs Suspicious Transition */}
        <div
          style={{
            marginTop: '10px',
            padding: '8px 14px',
            borderRadius: '10px',
            background: isHigh ? 'rgba(239, 68, 68, 0.2)' : isSuspicious ? 'rgba(245, 158, 11, 0.15)' : 'rgba(16, 185, 129, 0.12)',
            border: `1px solid ${theme.border}`,
            textAlign: 'center',
            maxWidth: '290px'
          }}
        >
          <div style={{ fontSize: '12px', fontWeight: 800, color: theme.text, textTransform: 'uppercase', letterSpacing: '0.04em' }}>
            {bannerTitle}
          </div>
          <div style={{ fontSize: '11px', color: isHigh ? '#fca5a5' : 'var(--text-muted)', marginTop: '2px' }}>
            {bannerRecommendation}
          </div>
          {call.detectorIsMock === true && (
            <div style={{ marginTop: '6px', display: 'flex', justifyContent: 'center' }}>
              <span style={{ fontSize: '10px', padding: '2px 8px', borderRadius: '4px', background: 'rgba(245, 158, 11, 0.2)', color: '#fbbf24', fontWeight: 700 }}>
                Development heuristic — not a validated AI-voice verdict
              </span>
            </div>
          )}
        </div>
      </div>

      {/* Live Audio Frequency Spectrogram Wave */}
      <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '6px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '4px', height: '36px' }}>
          {waveHeights.map((h, i) => (
            <div
              key={i}
              style={{
                width: '4px',
                height: `${h}px`,
                backgroundColor: theme.primary,
                borderRadius: '2px',
                transition: 'height 0.18s ease-in-out',
                boxShadow: isHigh ? '0 0 6px #ef4444' : 'none'
              }}
            />
          ))}
        </div>
        <span style={{ fontSize: '10px', color: 'var(--text-dim)', textTransform: 'uppercase', letterSpacing: '0.06em' }}>
          Real-Time Neural Vocoder Analyzer
        </span>
      </div>

      {/* Biometric Telemetry Trio: Synthetic Prob, Speaker Consistency, Context Risk */}
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(3, 1fr)',
          gap: '8px',
          background: 'rgba(0, 0, 0, 0.45)',
          border: '1px solid var(--border-subtle)',
          borderRadius: '12px',
          padding: '10px 8px',
          textAlign: 'center'
        }}
      >
        <div>
          <span style={{ fontSize: '10px', color: 'var(--text-dim)', textTransform: 'uppercase' }}>Synthetic</span>
          <div className="font-mono" style={{ fontSize: '14px', fontWeight: 800, color: isHigh ? '#ef4444' : 'var(--text-main)' }}>
            {call.syntheticProbability}%
          </div>
        </div>

        <div>
          <span style={{ fontSize: '10px', color: 'var(--text-dim)', textTransform: 'uppercase' }}>Consistency</span>
          <div className="font-mono" style={{ fontSize: '14px', fontWeight: 800, color: '#10b981' }}>
            {call.speakerConsistency}%
          </div>
        </div>

        <div>
          <span style={{ fontSize: '10px', color: 'var(--text-dim)', textTransform: 'uppercase' }}>Context</span>
          <div className="font-mono" style={{ fontSize: '14px', fontWeight: 800, color: call.contextRisk >= 70 ? '#ef4444' : '#f59e0b' }}>
            {call.contextRisk}%
          </div>
        </div>
      </div>

      {/* Call Actions Footer */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '20px', marginTop: '12px' }}>
        {/* End Call Button */}
        <button
          onClick={onEndCall}
          style={{
            width: '60px',
            height: '60px',
            borderRadius: '50%',
            background: '#dc2626',
            border: 'none',
            color: '#ffffff',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            cursor: 'pointer',
            boxShadow: '0 0 20px rgba(220, 38, 38, 0.6)'
          }}
          title="End Call Session"
        >
          <PhoneOff size={24} />
        </button>

        {isHigh && onOpenEvidence && (
          <button
            onClick={onOpenEvidence}
            style={{
              padding: '8px 14px',
              borderRadius: '20px',
              background: '#ef4444',
              color: '#fff',
              border: 'none',
              fontSize: '11px',
              fontWeight: 800,
              letterSpacing: '0.04em',
              textTransform: 'uppercase',
              cursor: 'pointer',
              display: 'flex',
              alignItems: 'center',
              gap: '6px'
            }}
          >
            <ShieldAlert size={14} />
            Review Evidence
          </button>
        )}
      </div>
    </div>
  );
};
