import React, { useState } from 'react';
import { ArrowLeft, Search, Filter, Disc, ChevronRight } from 'lucide-react';
import { Call, RiskLevel } from '../../types';
import { CallerAvatar } from '../common/CallerAvatar';
import { RiskBadge } from '../common/RiskBadge';
import { formatSeconds } from '../../utils/risk';

interface CallHistoryScreenProps {
  calls: Call[];
  onBack: () => void;
  onSelectCall: (call: Call) => void;
}

export const CallHistoryScreen: React.FC<CallHistoryScreenProps> = ({
  calls,
  onBack,
  onSelectCall
}) => {
  const [searchTerm, setSearchTerm] = useState('');
  const [filterLevel, setFilterLevel] = useState<RiskLevel | 'ALL'>('ALL');

  const filteredCalls = calls.filter(call => {
    const matchesSearch = call.caller.name.toLowerCase().includes(searchTerm.toLowerCase()) ||
                          call.id.includes(searchTerm);
    const matchesFilter = filterLevel === 'ALL' || call.currentRiskLevel === filterLevel;
    return matchesSearch && matchesFilter;
  });

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
          Call History & Archives
        </span>
        <div style={{ width: '36px' }} />
      </div>

      {/* Search Input */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: '8px',
          background: 'var(--bg-card)',
          border: '1px solid var(--border-subtle)',
          borderRadius: '12px',
          padding: '8px 12px'
        }}
      >
        <Search size={16} color="var(--text-dim)" />
        <input
          type="text"
          placeholder="Search by caller name or ID..."
          value={searchTerm}
          onChange={(e) => setSearchTerm(e.target.value)}
          style={{
            background: 'transparent',
            border: 'none',
            color: '#ffffff',
            fontSize: '13px',
            outline: 'none',
            width: '100%'
          }}
        />
      </div>

      {/* Filter Tabs: ALL / LOW / MEDIUM / HIGH */}
      <div style={{ display: 'flex', gap: '6px' }}>
        {(['ALL', 'LOW', 'MEDIUM', 'HIGH'] as const).map(lvl => {
          const active = filterLevel === lvl;
          return (
            <button
              key={lvl}
              onClick={() => setFilterLevel(lvl)}
              style={{
                flex: 1,
                padding: '6px 4px',
                borderRadius: '8px',
                background: active ? 'var(--accent-blue)' : 'var(--bg-card)',
                color: active ? '#ffffff' : 'var(--text-muted)',
                border: '1px solid var(--border-subtle)',
                fontSize: '11px',
                fontWeight: 700,
                cursor: 'pointer'
              }}
            >
              {lvl}
            </button>
          );
        })}
      </div>

      {/* Call List */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
        {filteredCalls.length === 0 ? (
          <div style={{ textAlign: 'center', padding: '40px 10px', color: 'var(--text-dim)', fontSize: '13px' }}>
            No calls match your search and filter criteria.
          </div>
        ) : (
          filteredCalls.map(call => {
            const isHigh = call.currentRiskLevel === 'HIGH';
            return (
              <div
                key={call.id}
                onClick={() => onSelectCall(call)}
                style={{
                  background: 'var(--bg-card)',
                  border: `1px solid ${isHigh ? 'rgba(239, 68, 68, 0.35)' : 'var(--border-subtle)'}`,
                  borderRadius: '12px',
                  padding: '12px 14px',
                  display: 'flex',
                  flexDirection: 'column',
                  gap: '8px',
                  cursor: 'pointer'
                }}
              >
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                    <CallerAvatar caller={call.caller} size={38} isHighRisk={isHigh} />
                    <div>
                      <div style={{ fontSize: '13px', fontWeight: 700, color: 'var(--text-main)' }}>
                        {call.caller.name}
                      </div>
                      <div style={{ fontSize: '11px', color: 'var(--text-dim)' }}>
                        #{call.id} • {new Date(call.startTime).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                      </div>
                    </div>
                  </div>

                  <RiskBadge score={call.currentRisk} level={call.currentRiskLevel} size="sm" showScore={true} />
                </div>

                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', fontSize: '11px', color: 'var(--text-muted)', borderTop: '1px solid rgba(255, 255, 255, 0.05)', paddingTop: '6px' }}>
                  <span>Duration: <strong className="font-mono" style={{ color: 'var(--text-main)' }}>{formatSeconds(call.durationSeconds)}</strong></span>
                  <span>AI Synth: <strong className="font-mono" style={{ color: isHigh ? '#ef4444' : 'var(--text-main)' }}>{call.syntheticProbability}%</strong></span>
                  {call.evidence ? (
                    <span style={{ color: 'var(--accent-cyan)', display: 'flex', alignItems: 'center', gap: '3px' }}>
                      <Disc size={11} /> Evidence Available
                    </span>
                  ) : (
                    <span>No Anomalies</span>
                  )}
                </div>
              </div>
            );
          })
        )}
      </div>
    </div>
  );
};
