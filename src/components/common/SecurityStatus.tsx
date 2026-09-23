import React from 'react';
import { Shield, ShieldAlert, ShieldCheck } from 'lucide-react';
import { MonitoringState } from '../../types';

interface SecurityStatusProps {
  state?: MonitoringState;
  showDetails?: boolean;
}

export const SecurityStatus: React.FC<SecurityStatusProps> = ({
  state = 'MONITORING_ACTIVE',
  showDetails = true
}) => {
  const isAlert = state === 'ALERT_TRIGGERED';
  const isSuspicious = state === 'SUSPICIOUS';

  const badgeColor = isAlert ? '#ef4444' : isSuspicious ? '#f59e0b' : '#10b981';
  const badgeBg = isAlert ? 'rgba(239, 68, 68, 0.15)' : isSuspicious ? 'rgba(245, 158, 11, 0.15)' : 'rgba(16, 185, 129, 0.12)';
  const border = isAlert ? 'rgba(239, 68, 68, 0.4)' : isSuspicious ? 'rgba(245, 158, 11, 0.4)' : 'rgba(16, 185, 129, 0.3)';

  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: '10px',
        padding: '8px 14px',
        borderRadius: '10px',
        background: badgeBg,
        border: `1px solid ${border}`
      }}
    >
      <div
        style={{
          width: '10px',
          height: '10px',
          borderRadius: '50%',
          backgroundColor: badgeColor,
          boxShadow: `0 0 10px ${badgeColor}`,
          animation: isAlert ? 'pulse-high-threat 1.2s infinite' : 'pulse-radar 2.5s infinite'
        }}
      />

      <div style={{ display: 'flex', flexDirection: 'column' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
          {isAlert ? (
            <ShieldAlert size={14} color={badgeColor} />
          ) : isSuspicious ? (
            <Shield size={14} color={badgeColor} />
          ) : (
            <ShieldCheck size={14} color={badgeColor} />
          )}
          <span
            style={{
              fontSize: '11px',
              fontWeight: 800,
              letterSpacing: '0.08em',
              textTransform: 'uppercase',
              color: badgeColor
            }}
          >
            {isAlert ? 'HIGH THREAT DETECTED' : isSuspicious ? 'SUSPICIOUS STREAM' : 'PROTECTED / MONITORING ACTIVE'}
          </span>
        </div>

        {showDetails && (
          <span style={{ fontSize: '11px', color: 'var(--text-muted)' }}>
            {isAlert 
              ? 'Deepfake synthesis markers triggered' 
              : isSuspicious 
              ? 'Analyzing spectral distortion' 
              : 'Real-time AI voice integrity engine engaged'}
          </span>
        )}
      </div>
    </div>
  );
};
