import React from 'react';
import { AlertTriangle, ArrowRight, X, ShieldAlert } from 'lucide-react';
import { SecurityAlert as SecurityAlertType } from '../../types';

interface SecurityAlertProps {
  alert: SecurityAlertType;
  onInvestigate: () => void;
  onDismiss?: () => void;
}

export const SecurityAlert: React.FC<SecurityAlertProps> = ({
  alert,
  onInvestigate,
  onDismiss
}) => {
  return (
    <div
      style={{
        position: 'relative',
        background: 'linear-gradient(135deg, rgba(127, 29, 29, 0.95), rgba(69, 10, 10, 0.95))',
        border: '1px solid #ef4444',
        borderRadius: '12px',
        padding: '16px 20px',
        boxShadow: '0 0 30px rgba(239, 68, 68, 0.45)',
        display: 'flex',
        flexDirection: 'column',
        gap: '12px',
        animation: 'pulse-high-threat 2s infinite ease-in-out'
      }}
    >
      {/* Top Banner Row */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
          <div
            style={{
              width: '32px',
              height: '32px',
              borderRadius: '8px',
              background: '#ef4444',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              color: '#ffffff',
              boxShadow: '0 0 12px #ef4444'
            }}
          >
            <ShieldAlert size={20} />
          </div>
          <div>
            <h4
              style={{
                fontSize: '15px',
                fontWeight: 800,
                letterSpacing: '0.04em',
                color: '#ffffff',
                textTransform: 'uppercase',
                display: 'flex',
                alignItems: 'center',
                gap: '8px'
              }}
            >
              {alert.message}
              <span
                style={{
                  fontSize: '10px',
                  padding: '2px 8px',
                  background: 'rgba(255, 255, 255, 0.2)',
                  borderRadius: '4px',
                  fontWeight: 700
                }}
              >
                LIVE ALERT
              </span>
            </h4>
            <span style={{ fontSize: '12px', color: '#fca5a5' }}>
              VoiceGuard neural engine flagged biometric inconsistency
            </span>
          </div>
        </div>

        {onDismiss && (
          <button
            onClick={onDismiss}
            style={{
              background: 'transparent',
              border: 'none',
              color: '#fca5a5',
              cursor: 'pointer',
              padding: '4px'
            }}
            title="Dismiss alert"
          >
            <X size={18} />
          </button>
        )}
      </div>

      {/* Metrics Row */}
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(110px, 1fr))',
          gap: '12px',
          background: 'rgba(0, 0, 0, 0.35)',
          padding: '12px',
          borderRadius: '8px',
          border: '1px solid rgba(239, 68, 68, 0.3)'
        }}
      >
        <div>
          <span style={{ fontSize: '11px', color: '#fca5a5', textTransform: 'uppercase', fontWeight: 600 }}>Call ID</span>
          <div className="font-mono" style={{ fontSize: '14px', fontWeight: 700, color: '#ffffff' }}>#{alert.callId}</div>
        </div>

        <div>
          <span style={{ fontSize: '11px', color: '#fca5a5', textTransform: 'uppercase', fontWeight: 600 }}>Caller</span>
          <div style={{ fontSize: '14px', fontWeight: 700, color: '#ffffff' }}>{alert.callerName}</div>
        </div>

        <div>
          <span style={{ fontSize: '11px', color: '#fca5a5', textTransform: 'uppercase', fontWeight: 600 }}>Risk Score</span>
          <div className="font-mono" style={{ fontSize: '15px', fontWeight: 800, color: '#f87171' }}>{alert.risk} / 100</div>
        </div>

        <div>
          <span style={{ fontSize: '11px', color: '#fca5a5', textTransform: 'uppercase', fontWeight: 600 }}>Synthetic Prob</span>
          <div className="font-mono" style={{ fontSize: '15px', fontWeight: 800, color: '#f87171' }}>{alert.syntheticProbability}%</div>
        </div>

        <div>
          <span style={{ fontSize: '11px', color: '#fca5a5', textTransform: 'uppercase', fontWeight: 600 }}>Detection</span>
          <div className="font-mono" style={{ fontSize: '14px', fontWeight: 700, color: '#ffffff' }}>{alert.detectionTime}</div>
        </div>

        <div>
          <span style={{ fontSize: '11px', color: '#fca5a5', textTransform: 'uppercase', fontWeight: 600 }}>Confidence</span>
          <div style={{ fontSize: '13px', fontWeight: 800, color: '#fecaca' }}>{alert.confidence}</div>
        </div>
      </div>

      {/* Action Row */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginTop: '2px' }}>
        <span style={{ fontSize: '12px', color: '#fecaca', display: 'flex', alignItems: 'center', gap: '6px' }}>
          <AlertTriangle size={14} color="#f87171" />
          Recommended: {alert.suggestedAction}
        </span>

        <button
          onClick={onInvestigate}
          style={{
            background: '#ffffff',
            color: '#991b1b',
            border: 'none',
            borderRadius: '6px',
            padding: '8px 16px',
            fontSize: '12px',
            fontWeight: 800,
            letterSpacing: '0.05em',
            textTransform: 'uppercase',
            cursor: 'pointer',
            display: 'flex',
            alignItems: 'center',
            gap: '6px',
            boxShadow: '0 2px 8px rgba(0, 0, 0, 0.4)'
          }}
        >
          INVESTIGATE
          <ArrowRight size={14} />
        </button>
      </div>
    </div>
  );
};
