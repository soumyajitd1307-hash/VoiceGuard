import React from 'react';
import { ArrowLeft, Play, Clock, ShieldCheck, ShieldAlert, Cpu } from 'lucide-react';
import { Call, Evidence } from '../../types';
import { CallerAvatar } from '../common/CallerAvatar';
import { RiskBadge } from '../common/RiskBadge';
import { RiskChart } from '../common/RiskChart';
import { DetectionTimeline } from '../common/DetectionTimeline';
import { formatSeconds, getRiskTheme } from '../../utils/risk';

interface CallDetailsScreenProps {
  call: Call;
  onBack: () => void;
  onOpenEvidence: (evidence: Evidence) => void;
}

export const CallDetailsScreen: React.FC<CallDetailsScreenProps> = ({
  call,
  onBack,
  onOpenEvidence
}) => {
  const isHigh = call.currentRiskLevel === 'HIGH';
  const theme = getRiskTheme(call.currentRiskLevel);
  const maxRisk = Math.max(call.currentRisk, ...call.riskHistory.map(h => h.risk));

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
          Forensic Call Inspection
        </span>
        <div style={{ width: '36px' }} />
      </div>

      {/* Caller Header Card */}
      <div
        style={{
          background: 'var(--bg-card)',
          border: '1px solid var(--border-subtle)',
          borderRadius: '16px',
          padding: '16px',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between'
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
          <CallerAvatar caller={call.caller} size={48} isHighRisk={isHigh} />
          <div>
            <h3 style={{ fontSize: '16px', fontWeight: 800, color: 'var(--text-main)' }}>
              {call.caller.name}
            </h3>
            <div style={{ fontSize: '11px', color: 'var(--text-dim)' }}>
              #{call.id} • {call.protocol} • {formatSeconds(call.durationSeconds)}
            </div>
          </div>
        </div>

        <RiskBadge score={call.currentRisk} level={call.currentRiskLevel} size="md" showScore={true} />
      </div>

      {/* Triad Metric Tiles */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '8px' }}>
        <div style={{ background: 'var(--bg-card)', padding: '10px 8px', borderRadius: '10px', textAlign: 'center', border: '1px solid var(--border-subtle)' }}>
          <span style={{ fontSize: '10px', color: 'var(--text-dim)', textTransform: 'uppercase' }}>Synthetic</span>
          <div className="font-mono" style={{ fontSize: '15px', fontWeight: 800, color: isHigh ? '#ef4444' : 'var(--text-main)', marginTop: '2px' }}>
            {call.syntheticProbability}%
          </div>
        </div>

        <div style={{ background: 'var(--bg-card)', padding: '10px 8px', borderRadius: '10px', textAlign: 'center', border: '1px solid var(--border-subtle)' }}>
          <span style={{ fontSize: '10px', color: 'var(--text-dim)', textTransform: 'uppercase' }}>Consistency</span>
          <div className="font-mono" style={{ fontSize: '15px', fontWeight: 800, color: '#10b981', marginTop: '2px' }}>
            {call.speakerConsistency}%
          </div>
        </div>

        <div style={{ background: 'var(--bg-card)', padding: '10px 8px', borderRadius: '10px', textAlign: 'center', border: '1px solid var(--border-subtle)' }}>
          <span style={{ fontSize: '10px', color: 'var(--text-dim)', textTransform: 'uppercase' }}>Context</span>
          <div className="font-mono" style={{ fontSize: '15px', fontWeight: 800, color: call.contextRisk >= 70 ? '#ef4444' : '#f59e0b', marginTop: '2px' }}>
            {call.contextRisk}%
          </div>
        </div>
      </div>

      {/* Risk-over-time Chart */}
      <div style={{ background: 'var(--bg-card)', borderRadius: '14px', padding: '14px', border: '1px solid var(--border-subtle)' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
          <span style={{ fontSize: '12px', fontWeight: 700, color: 'var(--text-main)' }}>
            Risk Over Time (Max: {maxRisk}/100)
          </span>
          <span className="font-mono" style={{ fontSize: '11px', color: theme.primary }}>
            {call.monitoringState}
          </span>
        </div>
        <RiskChart data={call.riskHistory} height={120} />
      </div>

      {/* Evidence Banner if available */}
      {call.evidence && (
        <button
          onClick={() => onOpenEvidence(call.evidence!)}
          style={{
            background: 'linear-gradient(135deg, rgba(239, 68, 68, 0.2), rgba(127, 29, 29, 0.3))',
            border: '1px solid #ef4444',
            borderRadius: '12px',
            padding: '14px',
            color: '#ffffff',
            cursor: 'pointer',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between'
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px', textAlign: 'left' }}>
            <Play size={18} color="#ef4444" />
            <div>
              <div style={{ fontSize: '13px', fontWeight: 800 }}>Play Captured Audio Evidence</div>
              <div style={{ fontSize: '11px', color: '#fca5a5' }}>Neural vocoder artifacts identified at {call.evidence.formattedTime}</div>
            </div>
          </div>
        </button>
      )}

      {/* Detection Timeline */}
      <div style={{ background: 'var(--bg-card)', borderRadius: '14px', padding: '16px', border: '1px solid var(--border-subtle)' }}>
        <span style={{ fontSize: '12px', fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase', display: 'block', marginBottom: '14px' }}>
          Detection Milestones
        </span>
        <DetectionTimeline events={call.detectionEvents} />
      </div>
    </div>
  );
};
