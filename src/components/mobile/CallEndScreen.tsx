import React from 'react';
import { CheckCircle2, ShieldAlert, ArrowLeft, Play, FileText, Home, RotateCcw } from 'lucide-react';
import { Call } from '../../types';
import { CallerAvatar } from '../common/CallerAvatar';
import { RiskBadge } from '../common/RiskBadge';
import { formatSeconds, getRiskTheme } from '../../utils/risk';

interface CallEndScreenProps {
  call: Call;
  onGoHome: () => void;
  onViewReport: () => void;
  onPlayEvidence?: () => void;
}

export const CallEndScreen: React.FC<CallEndScreenProps> = ({
  call,
  onGoHome,
  onViewReport,
  onPlayEvidence
}) => {
  const isHigh = call.currentRiskLevel === 'HIGH';
  const theme = getRiskTheme(call.currentRiskLevel);

  return (
    <div
      style={{
        flex: 1,
        display: 'flex',
        flexDirection: 'column',
        justifyContent: 'space-between',
        padding: '24px 20px',
        overflowY: 'auto',
        gap: '16px'
      }}
    >
      {/* Top Header */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <button
          onClick={onGoHome}
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
        <span style={{ fontSize: '13px', fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.06em' }}>
          Call Session Summary
        </span>
        <div style={{ width: '36px' }} />
      </div>

      {/* Outcome Banner */}
      <div
        style={{
          background: isHigh ? 'rgba(239, 68, 68, 0.12)' : 'rgba(16, 185, 129, 0.12)',
          border: `1px solid ${isHigh ? 'rgba(239, 68, 68, 0.4)' : 'rgba(16, 185, 129, 0.4)'}`,
          borderRadius: '16px',
          padding: '20px',
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          textAlign: 'center',
          gap: '10px'
        }}
      >
        <CallerAvatar caller={call.caller} size={64} isHighRisk={isHigh} />
        <div>
          <h2 style={{ fontSize: '18px', fontWeight: 800, color: 'var(--text-main)' }}>
            {call.caller.name}
          </h2>
          <div style={{ fontSize: '12px', color: 'var(--text-dim)', marginTop: '2px' }}>
            Session Duration: {formatSeconds(call.durationSeconds)} • Call #{call.id}
          </div>
        </div>

        <RiskBadge score={call.currentRisk} level={call.currentRiskLevel} size="lg" showScore={true} />
      </div>

      {/* Detection Stats & Summary */}
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: '1fr 1fr',
          gap: '10px'
        }}
      >
        <div style={{ background: 'var(--bg-card)', padding: '12px', borderRadius: '12px', border: '1px solid var(--border-subtle)' }}>
          <span style={{ fontSize: '11px', color: 'var(--text-dim)', textTransform: 'uppercase' }}>Final Risk Score</span>
          <div className="font-mono" style={{ fontSize: '20px', fontWeight: 800, color: theme.text, marginTop: '2px' }}>
            {call.currentRisk} <span style={{ fontSize: '12px', color: 'var(--text-dim)' }}>/100</span>
          </div>
        </div>

        <div style={{ background: 'var(--bg-card)', padding: '12px', borderRadius: '12px', border: '1px solid var(--border-subtle)' }}>
          <span style={{ fontSize: '11px', color: 'var(--text-dim)', textTransform: 'uppercase' }}>Synthetic Probability</span>
          <div className="font-mono" style={{ fontSize: '20px', fontWeight: 800, color: isHigh ? '#ef4444' : 'var(--text-main)', marginTop: '2px' }}>
            {call.syntheticProbability}%
          </div>
        </div>
      </div>

      {/* Detection Events Summary list */}
      <div style={{ background: 'var(--bg-card)', borderRadius: '12px', padding: '14px', border: '1px solid var(--border-subtle)' }}>
        <div style={{ fontSize: '12px', fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase', marginBottom: '8px' }}>
          Detection Events ({call.detectionEvents.length})
        </div>
        {call.detectionEvents.slice(0, 2).map((evt, idx) => (
          <div key={idx} style={{ fontSize: '12px', color: 'var(--text-main)', display: 'flex', gap: '8px', marginBottom: '6px' }}>
            <span className="font-mono" style={{ color: 'var(--accent-blue)', fontWeight: 700 }}>{evt.formattedTime}</span>
            <span>{evt.description}</span>
          </div>
        ))}
      </div>

      {/* CTAs */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
        {isHigh && onPlayEvidence && (
          <button
            onClick={onPlayEvidence}
            style={{
              background: '#ef4444',
              border: 'none',
              borderRadius: '12px',
              padding: '14px',
              color: '#ffffff',
              fontSize: '13px',
              fontWeight: 800,
              cursor: 'pointer',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              gap: '8px',
              boxShadow: '0 4px 15px rgba(239, 68, 68, 0.4)'
            }}
          >
            <Play size={16} />
            Play Audio Evidence Clip
          </button>
        )}

        <button
          onClick={onViewReport}
          style={{
            background: 'var(--bg-card)',
            border: '1px solid var(--border-medium)',
            borderRadius: '12px',
            padding: '14px',
            color: 'var(--text-main)',
            fontSize: '13px',
            fontWeight: 700,
            cursor: 'pointer',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            gap: '8px'
          }}
        >
          <FileText size={16} color="var(--accent-blue)" />
          View Detailed Forensic Report
        </button>

        <button
          onClick={onGoHome}
          style={{
            background: 'transparent',
            border: 'none',
            color: 'var(--text-dim)',
            fontSize: '12px',
            cursor: 'pointer',
            padding: '8px',
            textAlign: 'center'
          }}
        >
          Return to Home
        </button>
      </div>
    </div>
  );
};
