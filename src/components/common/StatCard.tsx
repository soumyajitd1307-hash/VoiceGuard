import React from 'react';

interface StatCardProps {
  title: string;
  value: string | number;
  subvalue?: string;
  icon: React.ReactNode;
  trend?: string;
  trendPositive?: boolean;
  statusColor?: string;
}

export const StatCard: React.FC<StatCardProps> = ({
  title,
  value,
  subvalue,
  icon,
  trend,
  trendPositive = true,
  statusColor
}) => {
  return (
    <div
      className="glass-panel"
      style={{
        padding: '16px 20px',
        display: 'flex',
        flexDirection: 'column',
        gap: '8px',
        position: 'relative',
        overflow: 'hidden'
      }}
    >
      {/* Top row with title and icon */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <span
          style={{
            fontSize: '12px',
            fontWeight: 700,
            textTransform: 'uppercase',
            letterSpacing: '0.06em',
            color: 'var(--text-muted)'
          }}
        >
          {title}
        </span>
        <div
          style={{
            width: '32px',
            height: '32px',
            borderRadius: '8px',
            background: 'rgba(255, 255, 255, 0.05)',
            border: '1px solid var(--border-subtle)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            color: statusColor || 'var(--accent-blue)'
          }}
        >
          {icon}
        </div>
      </div>

      {/* Main Metric Value */}
      <div style={{ display: 'flex', alignItems: 'baseline', gap: '8px' }}>
        <span
          className="font-mono"
          style={{
            fontSize: '28px',
            fontWeight: 800,
            color: statusColor || 'var(--text-main)',
            lineHeight: 1.1
          }}
        >
          {value}
        </span>
        {subvalue && (
          <span style={{ fontSize: '13px', color: 'var(--text-dim)', fontWeight: 600 }}>
            {subvalue}
          </span>
        )}
      </div>

      {/* Bottom Trend or detail */}
      {trend && (
        <div style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '11px' }}>
          <span style={{ color: trendPositive ? '#10b981' : '#ef4444', fontWeight: 700 }}>
            {trend}
          </span>
          <span style={{ color: 'var(--text-dim)' }}>vs past 24h</span>
        </div>
      )}
    </div>
  );
};
