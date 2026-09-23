import React from 'react';
import { getRiskTheme, getRiskLevel } from '../../utils/risk';

interface RiskGaugeProps {
  score: number; // 0-100
  size?: number;
  strokeWidth?: number;
  label?: string;
  sublabel?: string;
}

export const RiskGauge: React.FC<RiskGaugeProps> = ({
  score,
  size = 190,
  strokeWidth = 14,
  label = 'VOICE INTEGRITY',
  sublabel
}) => {
  const level = getRiskLevel(score);
  const theme = getRiskTheme(level);

  // SVG calculations for arc (260 degree arc)
  const radius = (size - strokeWidth * 2) / 2;
  const circumference = 2 * Math.PI * radius;
  const arcLength = circumference * 0.72; // ~260 degrees
  const offset = arcLength - (arcLength * Math.min(100, Math.max(0, score))) / 100;
  const center = size / 2;

  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        position: 'relative',
        width: size,
        height: size
      }}
    >
      <svg
        width={size}
        height={size}
        style={{ transform: 'rotate(140deg)', overflow: 'visible' }}
      >
        {/* Background Track Arc */}
        <circle
          cx={center}
          cy={center}
          r={radius}
          fill="none"
          stroke="rgba(255, 255, 255, 0.08)"
          strokeWidth={strokeWidth}
          strokeDasharray={`${arcLength} ${circumference}`}
          strokeLinecap="round"
        />

        {/* Active Risk Gauge Arc */}
        <circle
          cx={center}
          cy={center}
          r={radius}
          fill="none"
          stroke={theme.primary}
          strokeWidth={strokeWidth}
          strokeDasharray={`${arcLength} ${circumference}`}
          strokeDashoffset={offset}
          strokeLinecap="round"
          style={{
            transition: 'stroke-dashoffset 0.6s cubic-bezier(0.4, 0, 0.2, 1), stroke 0.4s ease',
            filter: `drop-shadow(0 0 10px ${theme.primary})`
          }}
        />
      </svg>

      {/* Center Score Display */}
      <div
        style={{
          position: 'absolute',
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          justifyContent: 'center',
          textAlign: 'center',
          pointerEvents: 'none'
        }}
      >
        <span
          style={{
            fontSize: '11px',
            fontWeight: 700,
            letterSpacing: '0.12em',
            textTransform: 'uppercase',
            color: 'var(--text-muted)',
            marginBottom: '2px'
          }}
        >
          {label}
        </span>
        <div style={{ display: 'flex', alignItems: 'baseline', gap: '3px' }}>
          <span
            className="font-mono"
            style={{
              fontSize: size > 160 ? '42px' : '30px',
              fontWeight: 800,
              color: theme.text,
              lineHeight: 1
            }}
          >
            {Math.round(score)}
          </span>
          <span
            style={{
              fontSize: '14px',
              color: 'var(--text-dim)',
              fontWeight: 600
            }}
          >
            /100
          </span>
        </div>
        <span
          style={{
            fontSize: '12px',
            fontWeight: 800,
            letterSpacing: '0.08em',
            color: theme.primary,
            marginTop: '4px',
            textTransform: 'uppercase'
          }}
        >
          {sublabel || `${level} RISK`}
        </span>
      </div>
    </div>
  );
};
