import React from 'react';
import { ShieldAlert, ShieldCheck, Activity, AlertCircle } from 'lucide-react';
import { DetectionEvent } from '../../types';
import { getRiskTheme } from '../../utils/risk';

interface EventFeedProps {
  events: DetectionEvent[];
  maxItems?: number;
}

export const EventFeed: React.FC<EventFeedProps> = ({ events, maxItems = 10 }) => {
  const displayEvents = events.slice(0, maxItems);

  if (displayEvents.length === 0) {
    return (
      <div style={{ padding: '20px', textAlign: 'center', color: 'var(--text-dim)', fontSize: '13px' }}>
        No detection events recorded yet. Continuous audio stream monitoring active.
      </div>
    );
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
      {displayEvents.map(evt => {
        const theme = getRiskTheme(evt.severity);
        const isHigh = evt.severity === 'HIGH';

        return (
          <div
            key={evt.id}
            style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              padding: '10px 14px',
              borderRadius: '8px',
              background: isHigh ? 'rgba(239, 68, 68, 0.1)' : 'var(--bg-secondary)',
              borderLeft: `3px solid ${theme.primary}`,
              borderTop: '1px solid var(--border-subtle)',
              borderRight: '1px solid var(--border-subtle)',
              borderBottom: '1px solid var(--border-subtle)',
              gap: '12px'
            }}
          >
            {/* Timestamp & Type */}
            <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
              <span
                className="font-mono"
                style={{
                  fontSize: '12px',
                  fontWeight: 700,
                  color: 'var(--text-dim)',
                  minWidth: '42px'
                }}
              >
                {evt.formattedTime}
              </span>

              <div>
                <div style={{ fontSize: '12px', fontWeight: 600, color: isHigh ? '#fca5a5' : 'var(--text-main)' }}>
                  Synthetic probability: <strong style={{ color: theme.text }}>{evt.syntheticProbability}%</strong>
                  {isHigh && (
                    <span
                      style={{
                        marginLeft: '8px',
                        padding: '1px 6px',
                        borderRadius: '4px',
                        background: '#ef4444',
                        color: '#ffffff',
                        fontSize: '10px',
                        fontWeight: 800
                      }}
                    >
                      HIGH RISK
                    </span>
                  )}
                </div>
                <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>
                  {evt.description}
                </div>
              </div>
            </div>

            {/* Risk Tag */}
            <div style={{ textAlign: 'right' }}>
              <span
                className="font-mono"
                style={{
                  fontSize: '11px',
                  fontWeight: 700,
                  color: theme.primary
                }}
              >
                Risk: {evt.risk}/100
              </span>
            </div>
          </div>
        );
      })}
    </div>
  );
};
