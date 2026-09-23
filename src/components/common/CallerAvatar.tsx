import React from 'react';
import { ShieldCheck, ShieldAlert, User } from 'lucide-react';
import { Caller } from '../../types';

interface CallerAvatarProps {
  caller: Caller;
  size?: number;
  showStatusBadge?: boolean;
  isHighRisk?: boolean;
}

export const CallerAvatar: React.FC<CallerAvatarProps> = ({
  caller,
  size = 48,
  showStatusBadge = true,
  isHighRisk = false
}) => {
  // Generate consistent initials
  const initials = caller.name
    .split(' ')
    .map(p => p[0])
    .join('')
    .substring(0, 2)
    .toUpperCase();

  const isVerified = caller.trustScore >= 70 && !isHighRisk;

  return (
    <div
      style={{
        position: 'relative',
        width: size,
        height: size,
        minWidth: size,
        minHeight: size,
        borderRadius: '50%',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        background: isHighRisk 
          ? 'linear-gradient(135deg, #7f1d1d, #450a0a)' 
          : 'linear-gradient(135deg, #1e293b, #0f172a)',
        border: `2px solid ${isHighRisk ? '#ef4444' : isVerified ? '#10b981' : 'rgba(255, 255, 255, 0.15)'}`,
        boxShadow: isHighRisk ? '0 0 12px rgba(239, 68, 68, 0.5)' : 'none',
        color: '#f8fafc',
        fontWeight: 700,
        fontSize: size * 0.38,
        letterSpacing: '0.04em'
      }}
    >
      {initials ? initials : <User size={size * 0.5} />}

      {showStatusBadge && (
        <div
          style={{
            position: 'absolute',
            bottom: -2,
            right: -2,
            width: size * 0.38,
            height: size * 0.38,
            borderRadius: '50%',
            background: isHighRisk ? '#ef4444' : isVerified ? '#10b981' : '#f59e0b',
            border: '2px solid #070a12',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            color: '#fff'
          }}
          title={isHighRisk ? 'High Security Risk' : isVerified ? 'Verified Biometric Identity' : 'Unverified Caller'}
        >
          {isHighRisk ? (
            <ShieldAlert size={size * 0.22} />
          ) : (
            <ShieldCheck size={size * 0.22} />
          )}
        </div>
      )}
    </div>
  );
};
