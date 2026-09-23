import React, { useState } from 'react';
import { Search, Filter, ShieldAlert, ShieldCheck, Disc } from 'lucide-react';
import { useCallContext } from '../../context/CallContext';
import { RiskLevel } from '../../types';
import { getRiskTheme } from '../../utils/risk';

export const DetectionEventsView: React.FC = () => {
  const { detectionEventsLog, openInvestigation, activeCalls } = useCallContext();
  const [searchTerm, setSearchTerm] = useState('');
  const [filterSeverity, setFilterSeverity] = useState<RiskLevel | 'ALL'>('ALL');

  const filtered = detectionEventsLog.filter(evt => {
    const matchesSearch = evt.description.toLowerCase().includes(searchTerm.toLowerCase()) ||
                          evt.callId.includes(searchTerm);
    const matchesSev = filterSeverity === 'ALL' || evt.severity === filterSeverity;
    return matchesSearch && matchesSev;
  });

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
      {/* Top Filter Bar */}
      <div className="glass-panel" style={{ padding: '16px 20px', display: 'flex', flexWrap: 'wrap', alignItems: 'center', justifyContent: 'space-between', gap: '12px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '10px', minWidth: '280px', flex: 1 }}>
          <Search size={16} color="var(--text-dim)" />
          <input
            type="text"
            placeholder="Search events by keyword or call ID..."
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

        <div style={{ display: 'flex', gap: '8px' }}>
          {(['ALL', 'LOW', 'MEDIUM', 'HIGH'] as const).map(sev => (
            <button
              key={sev}
              onClick={() => setFilterSeverity(sev)}
              style={{
                padding: '6px 14px',
                borderRadius: '8px',
                background: filterSeverity === sev ? 'var(--accent-blue)' : 'var(--bg-secondary)',
                color: filterSeverity === sev ? '#fff' : 'var(--text-muted)',
                border: '1px solid var(--border-subtle)',
                fontSize: '11px',
                fontWeight: 700,
                cursor: 'pointer'
              }}
            >
              {sev}
            </button>
          ))}
        </div>
      </div>

      {/* Events Table */}
      <div className="glass-panel" style={{ padding: '20px' }}>
        <h3 style={{ fontSize: '15px', fontWeight: 800, color: 'var(--text-main)', marginBottom: '14px' }}>
          Security Audit Trail ({filtered.length} Recorded Flags)
        </h3>

        <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
          {filtered.map(evt => {
            const theme = getRiskTheme(evt.severity);
            const isHigh = evt.severity === 'HIGH';

            return (
              <div
                key={evt.id}
                style={{
                  background: isHigh ? 'rgba(239, 68, 68, 0.08)' : 'var(--bg-secondary)',
                  borderLeft: `4px solid ${theme.primary}`,
                  borderTop: '1px solid var(--border-subtle)',
                  borderRight: '1px solid var(--border-subtle)',
                  borderBottom: '1px solid var(--border-subtle)',
                  borderRadius: '8px',
                  padding: '14px 18px',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'space-between',
                  gap: '16px'
                }}
              >
                <div style={{ display: 'flex', alignItems: 'center', gap: '14px' }}>
                  <div style={{ minWidth: '70px' }}>
                    <div className="font-mono" style={{ fontSize: '13px', fontWeight: 700, color: 'var(--accent-blue)' }}>
                      {evt.formattedTime}
                    </div>
                    <div style={{ fontSize: '11px', color: 'var(--text-dim)' }}>
                      Call #{evt.callId}
                    </div>
                  </div>

                  <div>
                    <div style={{ fontSize: '13px', fontWeight: 600, color: 'var(--text-main)' }}>
                      {evt.description}
                    </div>
                    <div style={{ fontSize: '11px', color: 'var(--text-dim)', marginTop: '2px' }}>
                      Event Type: <strong>{evt.eventType}</strong> • Confidence: <strong>{evt.confidence}</strong>
                    </div>
                  </div>
                </div>

                <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                  <div style={{ textAlign: 'right' }}>
                    <div className="font-mono" style={{ fontSize: '13px', fontWeight: 800, color: theme.text }}>
                      Risk: {evt.risk}/100
                    </div>
                    <div className="font-mono" style={{ fontSize: '11px', color: 'var(--text-dim)' }}>
                      Synth: {evt.syntheticProbability}%
                    </div>
                  </div>

                  {evt.audioSegmentAvailable && (
                    <button
                      onClick={() => {
                        const target = activeCalls.find(c => c.id === evt.callId);
                        if (target) openInvestigation(target);
                      }}
                      style={{
                        background: 'rgba(239, 68, 68, 0.2)',
                        border: '1px solid rgba(239, 68, 68, 0.4)',
                        borderRadius: '6px',
                        color: '#f87171',
                        padding: '6px 10px',
                        fontSize: '11px',
                        fontWeight: 700,
                        cursor: 'pointer',
                        display: 'flex',
                        alignItems: 'center',
                        gap: '4px'
                      }}
                    >
                      <Disc size={12} />
                      Inspect Audio
                    </button>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
};
