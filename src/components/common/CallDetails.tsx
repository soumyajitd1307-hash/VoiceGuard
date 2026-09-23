import React from 'react';
import { Phone, Clock, ShieldCheck, ShieldAlert, Cpu, Network, FileText, Play, CheckCircle } from 'lucide-react';
import { Call } from '../../types';
import { RiskGauge } from './RiskGauge';
import { RiskBadge } from './RiskBadge';
import { RiskChart } from './RiskChart';
import { DetectionTimeline } from './DetectionTimeline';
import { CallerAvatar } from './CallerAvatar';
import { CallTimer } from './CallTimer';
import { EvidencePlayer } from './EvidencePlayer';
import { getRiskStatusSummary } from '../../utils/risk';

interface CallDetailsProps {
  call: Call;
  onOpenEvidence?: () => void;
  onTerminateCall?: () => void;
  isCompact?: boolean;
}

export const CallDetails: React.FC<CallDetailsProps> = ({
  call,
  onOpenEvidence,
  onTerminateCall,
  isCompact = false
}) => {
  const isHigh = call.currentRiskLevel === 'HIGH';
  const summary = getRiskStatusSummary(call.currentRisk, call.confidence);

  // Maximum risk reached in history
  const maxRisk = Math.max(call.currentRisk, ...call.riskHistory.map(h => h.risk));

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
      {/* Top Banner / Call Header */}
      <div
        className="glass-panel"
        style={{
          padding: '20px',
          display: 'flex',
          flexWrap: 'wrap',
          alignItems: 'center',
          justifyContent: 'space-between',
          gap: '16px'
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: '14px' }}>
          <CallerAvatar caller={call.caller} size={54} isHighRisk={isHigh} />
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
              <h2 style={{ fontSize: '20px', fontWeight: 800, color: 'var(--text-main)' }}>
                {call.caller.name}
              </h2>
              <RiskBadge score={call.currentRisk} level={call.currentRiskLevel} size="md" showScore={true} />
            </div>
            <div style={{ fontSize: '13px', color: 'var(--text-muted)', marginTop: '2px' }}>
              Call ID: #{call.id} • {call.caller.organization || 'External SIP'} • {call.caller.phone}
            </div>
          </div>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
          <div style={{ textAlign: 'right' }}>
            <span style={{ fontSize: '11px', color: 'var(--text-dim)', textTransform: 'uppercase' }}>Session Duration</span>
            <div style={{ fontSize: '16px', fontWeight: 700, color: 'var(--text-main)' }}>
              <CallTimer initialSeconds={call.durationSeconds} />
            </div>
          </div>

          {onTerminateCall && (
            <button
              onClick={onTerminateCall}
              style={{
                background: '#dc2626',
                color: '#fff',
                border: 'none',
                borderRadius: '8px',
                padding: '8px 16px',
                fontWeight: 700,
                fontSize: '12px',
                cursor: 'pointer',
                display: 'flex',
                alignItems: 'center',
                gap: '6px'
              }}
            >
              Terminate Session
            </button>
          )}
        </div>
      </div>

      {/* Main Analysis Grid */}
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: isCompact ? '1fr' : 'repeat(auto-fit, minmax(280px, 1fr))',
          gap: '16px'
        }}
      >
        {/* Risk Gauge Card */}
        <div
          className="glass-panel"
          style={{
            padding: '20px',
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            justifyContent: 'center',
            textAlign: 'center'
          }}
        >
          <RiskGauge score={call.currentRisk} size={180} />
          <div style={{ marginTop: '12px', fontSize: '13px', fontWeight: 700, color: isHigh ? '#f87171' : 'var(--text-main)' }}>
            {summary.title}
          </div>
          <div style={{ fontSize: '11px', color: 'var(--text-muted)', maxWidth: '240px', marginTop: '4px' }}>
            {summary.recommendation}
          </div>
        </div>

        {/* Biometric & Acoustic Breakdown */}
        <div
          className="glass-panel"
          style={{
            padding: '20px',
            display: 'flex',
            flexDirection: 'column',
            justifyContent: 'space-between',
            gap: '14px'
          }}
        >
          <span style={{ fontSize: '12px', fontWeight: 700, textTransform: 'uppercase', color: 'var(--text-dim)' }}>
            Biometric Telemetry Breakdown
          </span>

          {/* Metric 1 */}
          <div>
            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '12px', marginBottom: '4px' }}>
              <span style={{ color: 'var(--text-muted)' }}>Synthetic Speech Probability</span>
              <span className="font-mono" style={{ fontWeight: 700, color: isHigh ? '#ef4444' : 'var(--text-main)' }}>
                {call.syntheticProbability}%
              </span>
            </div>
            <div style={{ height: '6px', background: 'rgba(255, 255, 255, 0.1)', borderRadius: '3px', overflow: 'hidden' }}>
              <div
                style={{
                  height: '100%',
                  width: `${call.syntheticProbability}%`,
                  background: isHigh ? '#ef4444' : 'var(--accent-cyan)',
                  transition: 'width 0.4s ease'
                }}
              />
            </div>
          </div>

          {/* Metric 2 */}
          <div>
            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '12px', marginBottom: '4px' }}>
              <span style={{ color: 'var(--text-muted)' }}>Speaker Voiceprint Consistency</span>
              <span className="font-mono" style={{ fontWeight: 700, color: 'var(--text-main)' }}>
                {call.speakerConsistency}%
              </span>
            </div>
            <div style={{ height: '6px', background: 'rgba(255, 255, 255, 0.1)', borderRadius: '3px', overflow: 'hidden' }}>
              <div
                style={{
                  height: '100%',
                  width: `${call.speakerConsistency}%`,
                  background: '#10b981',
                  transition: 'width 0.4s ease'
                }}
              />
            </div>
          </div>

          {/* Metric 3 */}
          <div>
            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '12px', marginBottom: '4px' }}>
              <span style={{ color: 'var(--text-muted)' }}>Conversational Context Risk</span>
              <span className="font-mono" style={{ fontWeight: 700, color: call.contextRisk >= 70 ? '#ef4444' : '#f59e0b' }}>
                {call.contextRisk}%
              </span>
            </div>
            <div style={{ height: '6px', background: 'rgba(255, 255, 255, 0.1)', borderRadius: '3px', overflow: 'hidden' }}>
              <div
                style={{
                  height: '100%',
                  width: `${call.contextRisk}%`,
                  background: call.contextRisk >= 70 ? '#ef4444' : '#f59e0b',
                  transition: 'width 0.4s ease'
                }}
              />
            </div>
          </div>

          {/* Stats footer */}
          <div style={{ display: 'flex', justifyContent: 'space-between', borderTop: '1px solid var(--border-subtle)', paddingTop: '10px', fontSize: '11px', color: 'var(--text-dim)' }}>
            <span>Max Risk Peak: <strong className="font-mono" style={{ color: 'var(--text-main)' }}>{maxRisk}/100</strong></span>
            <span>Confidence: <strong style={{ color: 'var(--accent-blue)' }}>{call.confidence}</strong></span>
            <span>Protocol: <strong style={{ color: 'var(--text-main)' }}>{call.protocol}</strong></span>
          </div>
        </div>
      </div>

      {/* Real-Time Risk Line Chart */}
      <div className="glass-panel" style={{ padding: '20px' }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '16px' }}>
          <div>
            <h4 style={{ fontSize: '14px', fontWeight: 700, color: 'var(--text-main)' }}>
              Real-Time Voice Risk Progression
            </h4>
            <span style={{ fontSize: '12px', color: 'var(--text-dim)' }}>
              Continuous sliding window tracking acoustic and neural vocoder probability
            </span>
          </div>
          <span className="font-mono" style={{ fontSize: '12px', color: 'var(--accent-cyan)' }}>
            ● LIVE STREAM
          </span>
        </div>

        <RiskChart data={call.riskHistory} height={160} />
      </div>

      {/* Audio Evidence Segment if available */}
      {call.evidence && (
        <div>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '10px' }}>
            <h4 style={{ fontSize: '14px', fontWeight: 700, color: 'var(--text-main)', display: 'flex', alignItems: 'center', gap: '8px' }}>
              <Play size={16} color="var(--accent-cyan)" />
              Captured Audio Evidence & Spectrogram
            </h4>
            {onOpenEvidence && (
              <button
                onClick={onOpenEvidence}
                style={{
                  background: 'transparent',
                  border: '1px solid var(--border-medium)',
                  borderRadius: '6px',
                  color: 'var(--accent-blue)',
                  padding: '4px 10px',
                  fontSize: '11px',
                  fontWeight: 600,
                  cursor: 'pointer'
                }}
              >
                Open Full Forensic View
              </button>
            )}
          </div>
          <EvidencePlayer evidence={call.evidence} />
        </div>
      )}

      {/* Detection Timeline */}
      <div className="glass-panel" style={{ padding: '20px' }}>
        <h4 style={{ fontSize: '14px', fontWeight: 700, color: 'var(--text-main)', marginBottom: '16px' }}>
          Chronological Detection Timeline ({call.detectionEvents.length} Events)
        </h4>
        <DetectionTimeline events={call.detectionEvents} />
      </div>
    </div>
  );
};
