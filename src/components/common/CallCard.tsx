import React from 'react';
import { Phone, Clock, ShieldCheck, ShieldAlert, ChevronRight, Activity } from 'lucide-react';
import { Call } from '../../types';
import { RiskBadge } from './RiskBadge';
import { CallerAvatar } from './CallerAvatar';
import { CallTimer } from './CallTimer';
import { getRiskTheme } from '../../utils/risk';

interface CallCardProps {
  call: Call;
  isSelected?: boolean;
  onClick?: () => void;
}

export const CallCard: React.FC<CallCardProps> = ({ call, isSelected = false, onClick }) => {
  const isHigh = call.currentRiskLevel === 'HIGH';
  const theme = getRiskTheme(call.currentRiskLevel);

  return (
    <div
      onClick={onClick}
      className="glass-panel"
      style={{
        padding: '14px 16px',
        cursor: 'pointer',
        borderLeft: isSelected 
          ? '3px solid var(--accent-blue)' 
          : isHigh 
          ? '3px solid #ef4444' 
          : '3px solid transparent',
        background: isSelected 
          ? 'rgba(56, 189, 248, 0.08)' 
          : isHigh 
          ? 'rgba(239, 68, 68, 0.05)' 
          : 'var(--bg-card)',
        display: 'flex',
        flexDirection: 'column',
        gap: '10px',
        transition: 'all 0.2s ease'
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
          <CallerAvatar caller={call.caller} size={36} isHighRisk={isHigh} />
          <div>
            <div style={{ fontSize: '14px', fontWeight: 700, color: 'var(--text-main)' }}>
              {call.caller.name}
            </div>
            <div style={{ fontSize: '11px', color: 'var(--text-dim)' }}>
              Call #{call.id} • {call.protocol}
            </div>
          </div>
        </div>

        <RiskBadge score={call.currentRisk} level={call.currentRiskLevel} size="sm" showScore={true} />
      </div>

      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', fontSize: '12px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '6px', color: 'var(--text-muted)' }}>
          <Clock size={13} />
          <CallTimer initialSeconds={call.durationSeconds} />
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: '4px', color: theme.text, fontSize: '11px', fontWeight: 600 }}>
          <Activity size={12} />
          {call.monitoringState}
        </div>
      </div>
    </div>
  );
};
