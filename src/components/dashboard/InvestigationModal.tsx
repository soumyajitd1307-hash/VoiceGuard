import React from 'react';
import { X, ShieldAlert, AlertTriangle, CheckSquare, PhoneOff, Lock, UserCheck, Download } from 'lucide-react';
import { Call } from '../../types';
import { CallDetails } from '../common/CallDetails';
import { getRiskTheme } from '../../utils/risk';

interface InvestigationModalProps {
  call: Call | null;
  onClose: () => void;
  onTerminate: (callId: string) => void;
}

export const InvestigationModal: React.FC<InvestigationModalProps> = ({
  call,
  onClose,
  onTerminate
}) => {
  if (!call) return null;

  const isHigh = call.currentRiskLevel === 'HIGH';
  const theme = getRiskTheme(call.currentRiskLevel);

  return (
    <div
      style={{
        position: 'fixed',
        top: 0,
        left: 0,
        right: 0,
        bottom: 0,
        backgroundColor: 'rgba(0, 0, 0, 0.85)',
        backdropFilter: 'blur(8px)',
        zIndex: 1000,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        padding: '24px'
      }}
      onClick={onClose}
    >
      <div
        className="glass-panel-elevated"
        style={{
          width: '100%',
          maxWidth: '1000px',
          maxHeight: '90vh',
          overflowY: 'auto',
          padding: '24px',
          display: 'flex',
          flexDirection: 'column',
          gap: '20px',
          position: 'relative',
          border: `1px solid ${isHigh ? '#ef4444' : 'var(--border-medium)'}`,
          boxShadow: isHigh ? '0 0 50px rgba(239, 68, 68, 0.4)' : '0 10px 40px rgba(0,0,0,0.8)'
        }}
        onClick={(e) => e.stopPropagation()}
      >
        {/* Modal Top Bar */}
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', borderBottom: '1px solid var(--border-subtle)', paddingBottom: '16px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
            <div
              style={{
                width: '40px',
                height: '40px',
                borderRadius: '10px',
                background: isHigh ? '#ef4444' : 'var(--accent-blue)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                color: '#fff',
                boxShadow: isHigh ? '0 0 15px rgba(239, 68, 68, 0.6)' : 'none'
              }}
            >
              <ShieldAlert size={22} />
            </div>

            <div>
              <h2 style={{ fontSize: '18px', fontWeight: 800, color: 'var(--text-main)', letterSpacing: '0.02em' }}>
                SOC Security Incident Investigation — Call #{call.id}
              </h2>
              <span style={{ fontSize: '12px', color: 'var(--text-muted)' }}>
                Target: {call.caller.name} • Protocol: {call.protocol} • Codec: {call.codec}
              </span>
            </div>
          </div>

          <button
            onClick={onClose}
            style={{
              background: 'rgba(255, 255, 255, 0.08)',
              border: '1px solid var(--border-subtle)',
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
            <X size={18} />
          </button>
        </div>

        {/* Detailed Forensic Inspection */}
        <CallDetails call={call} />

        {/* SOC Analyst Recommended Security Actions */}
        <div
          style={{
            background: 'var(--bg-secondary)',
            border: '1px solid var(--border-subtle)',
            borderRadius: '12px',
            padding: '18px',
            display: 'flex',
            flexDirection: 'column',
            gap: '12px'
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <AlertTriangle size={18} color="#ef4444" />
            <h3 style={{ fontSize: '14px', fontWeight: 800, color: 'var(--text-main)', textTransform: 'uppercase' }}>
              Incident Response & Containment Protocol
            </h3>
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: '10px' }}>
            <button
              onClick={() => {
                onTerminate(call.id);
                onClose();
              }}
              style={{
                background: '#dc2626',
                border: 'none',
                borderRadius: '8px',
                padding: '10px 14px',
                color: '#fff',
                fontSize: '12px',
                fontWeight: 700,
                cursor: 'pointer',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                gap: '8px'
              }}
            >
              <PhoneOff size={15} />
              Terminate Active Session
            </button>

            <button
              style={{
                background: 'rgba(245, 158, 11, 0.15)',
                border: '1px solid rgba(245, 158, 11, 0.4)',
                borderRadius: '8px',
                padding: '10px 14px',
                color: '#fbbf24',
                fontSize: '12px',
                fontWeight: 700,
                cursor: 'pointer',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                gap: '8px'
              }}
            >
              <Lock size={15} />
              Require Secondary Out-of-Band MFA
            </button>

            <button
              style={{
                background: 'rgba(56, 189, 248, 0.15)',
                border: '1px solid rgba(56, 189, 248, 0.4)',
                borderRadius: '8px',
                padding: '10px 14px',
                color: 'var(--accent-blue)',
                fontSize: '12px',
                fontWeight: 700,
                cursor: 'pointer',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                gap: '8px'
              }}
            >
              <Download size={15} />
              Export Cryptographic Audit Package
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};
