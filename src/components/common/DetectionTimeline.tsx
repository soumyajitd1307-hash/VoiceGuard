import React from 'react';
import { ShieldCheck, ShieldAlert, Cpu, AlertTriangle, Disc } from 'lucide-react';
import { DetectionEvent } from '../../types';
import { getRiskTheme } from '../../utils/risk';

interface DetectionTimelineProps {
  events: DetectionEvent[];
  onSelectEvent?: (event: DetectionEvent) => void;
}

export const DetectionTimeline: React.FC<DetectionTimelineProps> = ({ events, onSelectEvent }) => {
  if (events.length === 0) {
    return (
      <div style={{ padding: '16px', textAlign: 'center', color: 'var(--text-dim)', fontSize: '12px' }}>
        No detection flags recorded. Voice baseline continuous.
      </div>
    );
  }

  const sortedEvents = [...events].sort((a, b) => a.timestamp - b.timestamp);

  return (
    <div style={{ position: 'relative', paddingLeft: '20px', display: 'flex', flexDirection: 'column', gap: '16px' }}>
      {/* Vertical Timeline Axis */}
      <div
        style={{
          position: 'absolute',
          top: '6px',
          bottom: '6px',
          left: '7px',
          width: '2px',
          background: 'rgba(255, 255, 255, 0.1)'
        }}
      />

      {sortedEvents.map((evt, idx) => {
        const theme = getRiskTheme(evt.severity);
        const isCritical = evt.severity === 'HIGH';

        return (
          <div
            key={evt.id || idx}
            onClick={() => onSelectEvent?.(evt)}
            style={{
              position: 'relative',
              display: 'flex',
              flexDirection: 'column',
              gap: '4px',
              cursor: onSelectEvent ? 'pointer' : 'default'
            }}
          >
            {/* Timeline Node Marker */}
            <div
              style={{
                position: 'absolute',
                left: '-20px',
                top: '2px',
                width: '16px',
                height: '16px',
                borderRadius: '50%',
                background: theme.primary,
                border: '2px solid #080c14',
                boxShadow: `0 0 8px ${theme.primary}`,
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                zIndex: 2
              }}
            >
              {isCritical ? (
                <ShieldAlert size={9} color="#fff" />
              ) : (
                <div style={{ width: 4, height: 4, borderRadius: '50%', background: '#fff' }} />
              )}
            </div>

            {/* Header info */}
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                <span className="font-mono" style={{ fontSize: '12px', fontWeight: 700, color: 'var(--accent-blue)' }}>
                  {evt.formattedTime}
                </span>
                <span
                  style={{
                    fontSize: '10px',
                    fontWeight: 800,
                    textTransform: 'uppercase',
                    padding: '1px 6px',
                    borderRadius: '4px',
                    background: theme.bgLight,
                    color: theme.text,
                    border: `1px solid ${theme.border}`
                  }}
                >
                  {evt.severity} RISK ({evt.risk}/100)
                </span>
              </div>

              <span className="font-mono" style={{ fontSize: '11px', color: 'var(--text-dim)' }}>
                Synthetic: {evt.syntheticProbability}%
              </span>
            </div>

            {/* Description card */}
            <div
              style={{
                background: 'rgba(255, 255, 255, 0.03)',
                border: '1px solid var(--border-subtle)',
                borderRadius: '6px',
                padding: '8px 10px',
                fontSize: '12px',
                color: 'var(--text-main)',
                lineHeight: 1.4
              }}
            >
              {evt.description}
              {evt.audioSegmentAvailable && (
                <div style={{ marginTop: '6px', display: 'flex', alignItems: 'center', gap: '6px', color: 'var(--accent-cyan)', fontSize: '11px', fontWeight: 600 }}>
                  <Disc size={12} />
                  Audio evidence segment captured for forensic review
                </div>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
};
