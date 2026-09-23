import React from 'react';
import { ShieldCheck, PhoneCall, History, Settings, Bell, ChevronRight, User, PhoneIncoming, AlertTriangle } from 'lucide-react';
import { Call } from '../../types';
import { CallerAvatar } from '../common/CallerAvatar';
import { RiskBadge } from '../common/RiskBadge';
import { formatSeconds } from '../../utils/risk';

interface HomeScreenProps {
  onStartCall: () => void;
  startDisabled?: boolean;
  onOpenCallHistory: () => void;
  onOpenCallDetails: (call: Call) => void;
  recentCalls: Call[];
}

export const HomeScreen: React.FC<HomeScreenProps> = ({
  onStartCall,
  startDisabled = false,
  onOpenCallHistory,
  onOpenCallDetails,
  recentCalls
}) => {
  return (
    <div
      style={{
        flex: 1,
        display: 'flex',
        flexDirection: 'column',
        padding: '20px 16px',
        overflowY: 'auto',
        gap: '20px'
      }}
    >
      {/* Header Profile / Greeting */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', paddingTop: '10px' }}>
        <div>
          <span style={{ fontSize: '12px', color: 'var(--text-muted)', letterSpacing: '0.04em' }}>Welcome back,</span>
          <h2 style={{ fontSize: '20px', fontWeight: 800, color: 'var(--text-main)' }}>Subham Ray</h2>
        </div>
        <div style={{ display: 'flex', gap: '8px' }}>
          <div
            style={{
              width: '36px',
              height: '36px',
              borderRadius: '50%',
              background: 'var(--bg-card)',
              border: '1px solid var(--border-subtle)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              color: 'var(--text-muted)'
            }}
          >
            <Bell size={16} />
          </div>
        </div>
      </div>

      {/* Security Status Card */}
      <div
        style={{
          background: 'linear-gradient(135deg, rgba(6, 78, 59, 0.45), rgba(15, 23, 42, 0.7))',
          border: '1px solid rgba(16, 185, 129, 0.35)',
          borderRadius: '16px',
          padding: '16px',
          boxShadow: '0 4px 20px rgba(0, 0, 0, 0.3)',
          display: 'flex',
          flexDirection: 'column',
          gap: '10px'
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <div
              style={{
                width: '10px',
                height: '10px',
                borderRadius: '50%',
                backgroundColor: '#10b981',
                boxShadow: '0 0 10px #10b981',
                animation: 'pulse-radar 2s infinite'
              }}
            />
            <span style={{ fontSize: '11px', fontWeight: 800, color: '#34d399', letterSpacing: '0.08em', textTransform: 'uppercase' }}>
              Protected / Monitoring Active
            </span>
          </div>
          <ShieldCheck size={18} color="#10b981" />
        </div>

        <p style={{ fontSize: '12px', color: '#94a3b8', lineHeight: 1.4 }}>
          VoiceGuard neural shield is active. Inbound & outbound WebRTC calls are analyzed for deepfake synthesis.
        </p>

        <div style={{ display: 'flex', gap: '14px', fontSize: '11px', color: '#cbd5e1', paddingTop: '4px', borderTop: '1px solid rgba(255, 255, 255, 0.08)' }}>
          <span>AI Engine: <strong style={{ color: '#34d399' }}>Online</strong></span>
          <span>Latency: <strong style={{ color: '#38bdf8' }}>19ms</strong></span>
          <span>Zero-day clones: <strong style={{ color: '#34d399' }}>Filtered</strong></span>
        </div>
      </div>

      {/* Large Start Secure Call CTA Button */}
      <button
        onClick={onStartCall}
        disabled={startDisabled}
        style={{
          background: 'linear-gradient(135deg, #0284c7 0%, #0369a1 100%)',
          border: 'none',
          borderRadius: '16px',
          padding: '18px 20px',
          color: '#ffffff',
          cursor: startDisabled ? 'wait' : 'pointer',
          opacity: startDisabled ? 0.6 : 1,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          boxShadow: '0 8px 25px -4px rgba(2, 132, 199, 0.5)',
          transition: 'transform 0.15s ease'
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: '12px', textAlign: 'left' }}>
          <div
            style={{
              width: '44px',
              height: '44px',
              borderRadius: '12px',
              background: 'rgba(255, 255, 255, 0.2)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center'
            }}
          >
            <PhoneCall size={22} color="#ffffff" />
          </div>
          <div>
            <div style={{ fontSize: '16px', fontWeight: 800, letterSpacing: '0.02em' }}>
              Start Secure Call
            </div>
            <div style={{ fontSize: '12px', color: '#e0f2fe' }}>
              Launch live WebRTC session with Rahul (#1042)
            </div>
          </div>
        </div>

        <ChevronRight size={20} color="#ffffff" />
      </button>

      {/* Recent Calls Section */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <span style={{ fontSize: '13px', fontWeight: 700, color: 'var(--text-main)', textTransform: 'uppercase', letterSpacing: '0.04em' }}>
            Recent Monitored Calls
          </span>
          <button
            onClick={onOpenCallHistory}
            style={{
              background: 'transparent',
              border: 'none',
              color: 'var(--accent-blue)',
              fontSize: '12px',
              fontWeight: 600,
              cursor: 'pointer',
              display: 'flex',
              alignItems: 'center',
              gap: '4px'
            }}
          >
            View all
            <ChevronRight size={14} />
          </button>
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
          {recentCalls.slice(0, 3).map(call => {
            const isHigh = call.currentRiskLevel === 'HIGH';

            return (
              <div
                key={call.id}
                onClick={() => onOpenCallDetails(call)}
                style={{
                  background: 'var(--bg-card)',
                  border: `1px solid ${isHigh ? 'rgba(239, 68, 68, 0.3)' : 'var(--border-subtle)'}`,
                  borderRadius: '12px',
                  padding: '12px 14px',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'space-between',
                  cursor: 'pointer'
                }}
              >
                <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                  <CallerAvatar caller={call.caller} size={38} isHighRisk={isHigh} />
                  <div>
                    <div style={{ fontSize: '13px', fontWeight: 700, color: 'var(--text-main)' }}>
                      {call.caller.name}
                    </div>
                    <div style={{ fontSize: '11px', color: 'var(--text-dim)' }}>
                      {formatSeconds(call.durationSeconds)} • {call.protocol}
                    </div>
                  </div>
                </div>

                <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                  <RiskBadge score={call.currentRisk} level={call.currentRiskLevel} size="sm" showScore={true} />
                  <ChevronRight size={14} color="var(--text-dim)" />
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
};
