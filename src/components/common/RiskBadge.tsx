import React from 'react';
import { RiskLevel } from '../../types';
import { getRiskLevel, getRiskTheme } from '../../utils/risk';

interface RiskBadgeProps {
  score?: number;
  level?: RiskLevel;
  size?: 'sm' | 'md' | 'lg';
  showScore?: boolean;
}

export const RiskBadge: React.FC<RiskBadgeProps> = ({
  score,
  level,
  size = 'md',
  showScore = false
}) => {
  const currentLevel: RiskLevel = level || (score !== undefined ? getRiskLevel(score) : 'LOW');
  const theme = getRiskTheme(currentLevel);

  const sizeStyles = {
    sm: { padding: '2px 8px', fontSize: '11px', gap: '4px' },
    md: { padding: '4px 12px', fontSize: '12px', gap: '6px' },
    lg: { padding: '6px 16px', fontSize: '14px', gap: '8px' }
  }[size];

  return (
    <span
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        background: theme.bgLight,
        color: theme.text,
        border: `1px solid ${theme.border}`,
        borderRadius: '9999px',
        fontWeight: 700,
        letterSpacing: '0.05em',
        textTransform: 'uppercase',
        boxShadow: currentLevel === 'HIGH' ? theme.glow : 'none',
        ...sizeStyles
      }}
    >
      <span
        style={{
          width: size === 'sm' ? 6 : 8,
          height: size === 'sm' ? 6 : 8,
          borderRadius: '50%',
          backgroundColor: theme.primary,
          boxShadow: `0 0 8px ${theme.primary}`
        }}
      />
      {currentLevel} RISK {showScore && score !== undefined ? `(${score})` : ''}
    </span>
  );
};
