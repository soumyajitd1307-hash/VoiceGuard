import React, { useState } from 'react';
import { Search, Filter, Clock, Disc, ArrowRight } from 'lucide-react';
import { useCallContext } from '../../context/CallContext';
import { RiskBadge } from '../common/RiskBadge';
import { CallerAvatar } from '../common/CallerAvatar';
import { formatSeconds } from '../../utils/risk';

export const CallHistoryView: React.FC = () => {
  const { callHistory, openInvestigation } = useCallContext();
  const [searchTerm, setSearchTerm] = useState('');

  const filtered = callHistory.filter(c =>
    c.caller.name.toLowerCase().includes(searchTerm.toLowerCase()) ||
    c.id.includes(searchTerm)
  );

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
      <div className="glass-panel" style={{ padding: '16px 20px', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '10px', width: '320px' }}>
          <Search size={16} color="var(--text-dim)" />
          <input
            type="text"
            placeholder="Search past calls..."
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
            style={{
              background: 'transparent',
              border: 'none',
              outline: 'none',
              color: '#fff',
              fontSize: '13px',
              width: '100%'
            }}
          />
        </div>
        <span style={{ fontSize: '12px', color: 'var(--text-dim)' }}>
          {filtered.length} Archived Sessions
        </span>
      </div>

      <div className="glass-panel" style={{ padding: '20px' }}>
        <h3 style={{ fontSize: '15px', fontWeight: 800, color: 'var(--text-main)', marginBottom: '14px' }}>
          Completed & Terminated Voice Calls Archive
        </h3>

        <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
          {filtered.map(call => {
            const isHigh = call.currentRiskLevel === 'HIGH';

            return (
              <div
                key={call.id}
                onClick={() => openInvestigation(call)}
                style={{
                  background: 'var(--bg-secondary)',
                  border: `1px solid ${isHigh ? 'rgba(239, 68, 68, 0.3)' : 'var(--border-subtle)'}`,
                  borderRadius: '10px',
                  padding: '14px 18px',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'space-between',
                  cursor: 'pointer',
                  transition: 'background 0.2s ease'
                }}
              >
                <div style={{ display: 'flex', alignItems: 'center', gap: '14px' }}>
                  <CallerAvatar caller={call.caller} size={40} isHighRisk={isHigh} />
                  <div>
                    <div style={{ fontSize: '14px', fontWeight: 700, color: 'var(--text-main)' }}>
                      {call.caller.name}
                    </div>
                    <div style={{ fontSize: '11px', color: 'var(--text-dim)' }}>
                      Call #{call.id} • {new Date(call.startTime).toLocaleDateString()} {new Date(call.startTime).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })} • {call.protocol}
                    </div>
                  </div>
                </div>

                <div style={{ display: 'flex', alignItems: 'center', gap: '14px' }}>
                  <div style={{ textAlign: 'right' }}>
                    <div className="font-mono" style={{ fontSize: '12px', color: 'var(--text-muted)' }}>
                      Duration: {formatSeconds(call.durationSeconds)}
                    </div>
                    <div className="font-mono" style={{ fontSize: '11px', color: 'var(--text-dim)' }}>
                      Synth Prob: {call.syntheticProbability}%
                    </div>
                  </div>

                  <RiskBadge score={call.currentRisk} level={call.currentRiskLevel} size="sm" showScore={true} />
                  <ArrowRight size={16} color="var(--text-dim)" />
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
};
