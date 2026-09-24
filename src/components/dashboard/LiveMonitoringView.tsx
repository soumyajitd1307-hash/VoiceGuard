import React, { useState, useEffect } from 'react';
import { Activity, Radio, Cpu, Network, Volume2, ShieldAlert } from 'lucide-react';
import { useCallContext } from '../../context/CallContext';
import { RiskGauge } from '../common/RiskGauge';
import { RiskBadge } from '../common/RiskBadge';
import { CallTimer } from '../common/CallTimer';
import { getRiskTheme } from '../../utils/risk';

export const LiveMonitoringView: React.FC = () => {
  const { selectedCall, activeCalls, isDemoMode } = useCallContext();
  const call = selectedCall || activeCalls[0];

  // Spectrogram animates ONLY in demo theater mode. In live mode there is
  // no spectral telemetry yet, so bars stay static — random motion would
  // fake a signal that isn't there.
  const FLAT_SPECTRUM = Array.from({ length: 32 }, () => 12);
  const [spectrogramBars, setSpectrogramBars] = useState<number[]>(FLAT_SPECTRUM);

  useEffect(() => {
    if (!isDemoMode) {
      setSpectrogramBars(FLAT_SPECTRUM);
      return;
    }
    const interval = setInterval(() => {
      setSpectrogramBars(prev =>
        prev.map(() => Math.floor(Math.random() * 65) + 10)
      );
    }, 120);
    return () => clearInterval(interval);
  }, [isDemoMode]);

  if (!call) {
    return <div style={{ padding: '40px', textAlign: 'center' }}>No active monitoring streams.</div>;
  }

  const isHigh = call.currentRiskLevel === 'HIGH';
  const theme = getRiskTheme(call.currentRiskLevel);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
      {/* Top Stream Header */}
      <div className="glass-panel" style={{ padding: '20px', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '14px' }}>
          <div
            style={{
              width: '12px',
              height: '12px',
              borderRadius: '50%',
              backgroundColor: theme.primary,
              boxShadow: `0 0 10px ${theme.primary}`,
              animation: isHigh ? 'pulse-high-threat 1s infinite' : 'pulse-radar 2s infinite'
            }}
          />
          <div>
            <div style={{ fontSize: '18px', fontWeight: 800, color: 'var(--text-main)' }}>
              Live Telemetry Stream: {call.caller.name} (Call #{call.id})
            </div>
            <div style={{ fontSize: '12px', color: 'var(--text-muted)' }}>
              Codec: {call.codec} • Jitter: 1.4ms • Packet Loss: {call.packetLoss}% • AI Latency: {call.latencyMs}ms
            </div>
          </div>
        </div>

        <RiskBadge score={call.currentRisk} level={call.currentRiskLevel} size="lg" showScore={true} />
      </div>

      {/* Acoustic Spectrum & Neural Inspection Grid */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(340px, 1fr))', gap: '16px' }}>
        {/* Spectrum Visualizer */}
        <div className="glass-panel" style={{ padding: '20px', display: 'flex', flexDirection: 'column', gap: '14px' }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
            <span style={{ fontSize: '13px', fontWeight: 700, color: 'var(--text-main)', display: 'flex', alignItems: 'center', gap: '8px' }}>
              <Volume2 size={16} color="var(--accent-cyan)" />
              Real-Time High-Band Audio Spectrogram (0 - 24kHz)
            </span>
            <span className="font-mono" style={{ fontSize: '11px', color: 'var(--accent-cyan)' }}>
              48kHz PCM
            </span>
          </div>

          <div
            style={{
              height: '140px',
              background: 'rgba(0, 0, 0, 0.4)',
              borderRadius: '8px',
              padding: '12px',
              display: 'flex',
              alignItems: 'flex-end',
              justifyContent: 'space-between',
              gap: '4px'
            }}
          >
            {spectrogramBars.map((height, i) => {
              const isVocoderBand = i >= 18 && i <= 26 && isHigh;
              return (
                <div
                  key={i}
                  style={{
                    flex: 1,
                    height: `${height}%`,
                    backgroundColor: isVocoderBand ? '#ef4444' : theme.primary,
                    borderRadius: '2px 2px 0 0',
                    transition: 'height 0.1s ease',
                    boxShadow: isVocoderBand ? '0 0 8px #ef4444' : 'none'
                  }}
                  title={`Band ${i * 750}Hz: ${height}%`}
                />
              );
            })}
          </div>

          <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '10px', color: 'var(--text-dim)', fontFamily: 'var(--font-mono)' }}>
            <span>0 Hz</span>
            <span>4 kHz</span>
            <span>8 kHz</span>
            <span>16 kHz</span>
            <span>24 kHz</span>
          </div>
        </div>

        {/* AI Vocoder Metrics */}
        <div className="glass-panel" style={{ padding: '20px', display: 'flex', flexDirection: 'column', gap: '14px' }}>
          <span style={{ fontSize: '13px', fontWeight: 700, color: 'var(--text-main)', display: 'flex', alignItems: 'center', gap: '8px' }}>
            <Cpu size={16} color="var(--accent-blue)" />
            Neural Vocoder Deepfake Signatures
          </span>

          <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
            <div>
              <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '12px', marginBottom: '4px' }}>
                <span style={{ color: 'var(--text-muted)' }}>F0 Fundamental Pitch Entropy</span>
                <span className="font-mono" style={{ color: isHigh ? '#ef4444' : '#10b981', fontWeight: 700 }}>
                  {isHigh ? '3.2 Hz (Abnormal Flatness)' : '18.4 Hz (Natural Human Jitter)'}
                </span>
              </div>
              <div style={{ height: '6px', background: 'rgba(255,255,255,0.08)', borderRadius: '3px', overflow: 'hidden' }}>
                <div style={{ height: '100%', width: isHigh ? '92%' : '24%', background: isHigh ? '#ef4444' : '#10b981' }} />
              </div>
            </div>

            <div>
              <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '12px', marginBottom: '4px' }}>
                <span style={{ color: 'var(--text-muted)' }}>High-Frequency Comb Filter Artifacts</span>
                <span className="font-mono" style={{ color: isHigh ? '#ef4444' : '#10b981', fontWeight: 700 }}>
                  {isHigh ? '88% Residual Power' : '4% Noise Floor'}
                </span>
              </div>
              <div style={{ height: '6px', background: 'rgba(255,255,255,0.08)', borderRadius: '3px', overflow: 'hidden' }}>
                <div style={{ height: '100%', width: isHigh ? '88%' : '8%', background: isHigh ? '#ef4444' : 'var(--accent-cyan)' }} />
              </div>
            </div>

            <div>
              <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '12px', marginBottom: '4px' }}>
                <span style={{ color: 'var(--text-muted)' }}>Biometric Voiceprint Match</span>
                <span className="font-mono" style={{ color: isHigh ? '#ef4444' : '#10b981', fontWeight: 700 }}>
                  {call.speakerConsistency}% Confidence
                </span>
              </div>
              <div style={{ height: '6px', background: 'rgba(255,255,255,0.08)', borderRadius: '3px', overflow: 'hidden' }}>
                <div style={{ height: '100%', width: `${call.speakerConsistency}%`, background: '#10b981' }} />
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};
