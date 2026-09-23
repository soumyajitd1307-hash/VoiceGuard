import React from 'react';
import { ArrowLeft, ShieldAlert, Cpu } from 'lucide-react';
import { Evidence } from '../../types';
import { EvidencePlayer } from '../common/EvidencePlayer';
import { RiskBadge } from '../common/RiskBadge';
import { getRiskTheme } from '../../utils/risk';

interface EvidenceScreenProps {
  evidence: Evidence;
  onBack: () => void;
}

export const EvidenceScreen: React.FC<EvidenceScreenProps> = ({
  evidence,
  onBack
}) => {
  const isHigh = evidence.overallRisk >= 70;
  const theme = getRiskTheme(evidence.overallRisk);

  return (
    <div
      style={{
        flex: 1,
        display: 'flex',
        flexDirection: 'column',
        padding: '20px 16px',
        overflowY: 'auto',
        gap: '16px'
      }}
    >
      {/* Top Header */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', paddingTop: '6px' }}>
        <button
          onClick={onBack}
          style={{
            background: 'rgba(255, 255, 255, 0.08)',
            border: 'none',
            borderRadius: '50%',
            width: '36px',
            height: '36px',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            color: 'var(--text-main)',
            cursor: 'pointer'
          }}
        >
          <ArrowLeft size={18} />
        </button>
        <span style={{ fontSize: '14px', fontWeight: 700, color: 'var(--text-main)' }}>
          Acoustic Evidence Clip
        </span>
        <div style={{ width: '36px' }} />
      </div>

      {/* Top Banner Alert */}
      <div
        style={{
          background: isHigh ? 'rgba(239, 68, 68, 0.15)' : 'rgba(16, 185, 129, 0.15)',
          border: `1px solid ${isHigh ? 'rgba(239, 68, 68, 0.5)' : 'rgba(16, 185, 129, 0.5)'}`,
          borderRadius: '14px',
          padding: '16px',
          display: 'flex',
          flexDirection: 'column',
          gap: '8px'
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <ShieldAlert size={18} color={theme.primary} />
            <span style={{ fontSize: '13px', fontWeight: 800, color: theme.text, textTransform: 'uppercase' }}>
              Anomaly Flagged @ {evidence.formattedTime}
            </span>
          </div>
          <RiskBadge score={evidence.overallRisk} size="sm" showScore={true} />
        </div>

        <p style={{ fontSize: '12px', color: '#fca5a5', lineHeight: 1.4 }}>
          Glottal waveform perturbation and spectral comb filtering artifacts indicate synthetic speech synthesis.
        </p>
      </div>

      {/* Interactive Evidence Player */}
      <EvidencePlayer evidence={evidence} />

      {/* Recommended Action Checklist */}
      <div
        style={{
          background: 'var(--bg-card)',
          border: '1px solid var(--border-subtle)',
          borderRadius: '14px',
          padding: '16px',
          display: 'flex',
          flexDirection: 'column',
          gap: '10px'
        }}
      >
        <span style={{ fontSize: '12px', fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase' }}>
          Security Protocol Recommendation:
        </span>
        <div style={{ fontSize: '12px', color: 'var(--text-main)', lineHeight: 1.5, background: 'rgba(0, 0, 0, 0.25)', padding: '10px', borderRadius: '8px', borderLeft: '3px solid #ef4444' }}>
          {evidence.recommendedAction}
        </div>
      </div>
    </div>
  );
};
