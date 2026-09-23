import React from 'react';
import { ShieldAlert, ShieldCheck, Radio, Search, ExternalLink } from 'lucide-react';
import { Call } from '../../types';
import { RiskBadge } from './RiskBadge';
import { CallTimer } from './CallTimer';
import { CallerAvatar } from './CallerAvatar';

interface ActiveCallTableProps {
  calls: Call[];
  selectedCallId?: string;
  onSelectCall: (callId: string) => void;
  onInvestigateCall: (call: Call) => void;
}

export const ActiveCallTable: React.FC<ActiveCallTableProps> = ({
  calls,
  selectedCallId,
  onSelectCall,
  onInvestigateCall
}) => {
  return (
    <div style={{ width: '100%', overflowX: 'auto' }}>
      <table
        style={{
          width: '100%',
          borderCollapse: 'separate',
          borderSpacing: '0 6px',
          textAlign: 'left'
        }}
      >
        <thead>
          <tr style={{ color: 'var(--text-dim)', fontSize: '11px', textTransform: 'uppercase', letterSpacing: '0.08em' }}>
            <th style={{ padding: '8px 14px' }}>Call ID</th>
            <th style={{ padding: '8px 14px' }}>Caller</th>
            <th style={{ padding: '8px 14px' }}>Risk Score</th>
            <th style={{ padding: '8px 14px' }}>Status</th>
            <th style={{ padding: '8px 14px' }}>Duration</th>
            <th style={{ padding: '8px 14px' }}>Detection State</th>
            <th style={{ padding: '8px 14px', textAlign: 'right' }}>Actions</th>
          </tr>
        </thead>
        <tbody>
          {calls.map(call => {
            const isSelected = call.id === selectedCallId;
            const isHigh = call.currentRiskLevel === 'HIGH';

            return (
              <tr
                key={call.id}
                onClick={() => onSelectCall(call.id)}
                style={{
                  background: isSelected 
                    ? 'rgba(56, 189, 248, 0.08)' 
                    : isHigh 
                    ? 'rgba(239, 68, 68, 0.06)' 
                    : 'var(--bg-secondary)',
                  borderLeft: isSelected 
                    ? '3px solid var(--accent-blue)' 
                    : isHigh 
                    ? '3px solid #ef4444' 
                    : '3px solid transparent',
                  cursor: 'pointer',
                  transition: 'background 0.2s ease'
                }}
              >
                {/* Call ID */}
                <td style={{ padding: '12px 14px', borderRadius: '8px 0 0 8px' }}>
                  <span className="font-mono" style={{ fontWeight: 700, color: 'var(--text-main)', fontSize: '13px' }}>
                    #{call.id}
                  </span>
                </td>

                {/* Caller */}
                <td style={{ padding: '12px 14px' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                    <CallerAvatar caller={call.caller} size={32} showStatusBadge={false} isHighRisk={isHigh} />
                    <div>
                      <div style={{ fontWeight: 600, fontSize: '13px', color: 'var(--text-main)' }}>
                        {call.caller.name}
                      </div>
                      <div style={{ fontSize: '11px', color: 'var(--text-dim)' }}>
                        {call.caller.organization || 'Inbound'}
                      </div>
                    </div>
                  </div>
                </td>

                {/* Risk */}
                <td style={{ padding: '12px 14px' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                    <RiskBadge score={call.currentRisk} level={call.currentRiskLevel} size="sm" showScore={true} />
                  </div>
                </td>

                {/* Status */}
                <td style={{ padding: '12px 14px' }}>
                  <span
                    style={{
                      display: 'inline-flex',
                      alignItems: 'center',
                      gap: '5px',
                      fontSize: '11px',
                      fontWeight: 600,
                      color: call.status === 'FLAGGED' ? '#f87171' : '#38bdf8'
                    }}
                  >
                    <Radio size={12} className={call.status === 'ACTIVE' ? 'animate-pulse' : ''} />
                    {call.status}
                  </span>
                </td>

                {/* Duration */}
                <td style={{ padding: '12px 14px' }}>
                  <CallTimer initialSeconds={call.durationSeconds} />
                </td>

                {/* Detection State */}
                <td style={{ padding: '12px 14px' }}>
                  <span
                    style={{
                      fontSize: '11px',
                      fontWeight: 600,
                      padding: '3px 8px',
                      borderRadius: '4px',
                      background: isHigh 
                        ? 'rgba(239, 68, 68, 0.2)' 
                        : call.currentRiskLevel === 'MEDIUM' 
                        ? 'rgba(245, 158, 11, 0.2)' 
                        : 'rgba(16, 185, 129, 0.15)',
                      color: isHigh ? '#f87171' : call.currentRiskLevel === 'MEDIUM' ? '#fbbf24' : '#34d399'
                    }}
                  >
                    {call.monitoringState}
                  </span>
                </td>

                {/* Actions */}
                <td style={{ padding: '12px 14px', borderRadius: '0 8px 8px 0', textAlign: 'right' }}>
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      onInvestigateCall(call);
                    }}
                    style={{
                      background: 'rgba(255, 255, 255, 0.06)',
                      border: '1px solid var(--border-subtle)',
                      borderRadius: '6px',
                      color: 'var(--text-main)',
                      fontSize: '11px',
                      fontWeight: 600,
                      padding: '5px 10px',
                      cursor: 'pointer',
                      display: 'inline-flex',
                      alignItems: 'center',
                      gap: '4px'
                    }}
                  >
                    <Search size={12} />
                    Audit
                  </button>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
};
