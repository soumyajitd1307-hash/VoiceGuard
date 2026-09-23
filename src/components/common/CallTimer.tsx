import React, { useState, useEffect } from 'react';
import { formatSeconds } from '../../utils/risk';

interface CallTimerProps {
  initialSeconds?: number;
  isRunning?: boolean;
  className?: string;
  style?: React.CSSProperties;
}

export const CallTimer: React.FC<CallTimerProps> = ({
  initialSeconds = 0,
  isRunning = true,
  className = '',
  style = {}
}) => {
  const [seconds, setSeconds] = useState(initialSeconds);

  useEffect(() => {
    setSeconds(initialSeconds);
  }, [initialSeconds]);

  useEffect(() => {
    if (!isRunning) return;
    const interval = window.setInterval(() => {
      setSeconds(prev => prev + 1);
    }, 1000);
    return () => clearInterval(interval);
  }, [isRunning]);

  return (
    <span
      className={`font-mono ${className}`}
      style={{
        fontSize: '13px',
        fontWeight: 600,
        color: 'var(--text-muted)',
        letterSpacing: '0.04em',
        ...style
      }}
    >
      {formatSeconds(seconds)}
    </span>
  );
};
