import React, { useEffect } from 'react';
import { Shield, Radio, Sparkles } from 'lucide-react';

interface SplashScreenProps {
  onContinue: () => void;
}

export const SplashScreen: React.FC<SplashScreenProps> = ({ onContinue }) => {
  useEffect(() => {
    const timer = setTimeout(() => {
      onContinue();
    }, 2400);
    return () => clearTimeout(timer);
  }, [onContinue]);

  return (
    <div
      style={{
        flex: 1,
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        background: 'radial-gradient(circle at center, #0f1c36 0%, #060911 100%)',
        padding: '30px',
        textAlign: 'center',
        position: 'relative',
        cursor: 'pointer'
      }}
      onClick={onContinue}
    >
      {/* Animated glowing logo shield */}
      <div
        style={{
          position: 'relative',
          width: '96px',
          height: '96px',
          borderRadius: '26px',
          background: 'linear-gradient(135deg, #0284c7, #0369a1)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          boxShadow: '0 0 35px rgba(2, 132, 199, 0.6)',
          marginBottom: '24px'
        }}
      >
        <Shield size={52} color="#ffffff" />
        <div
          style={{
            position: 'absolute',
            bottom: '-4px',
            right: '-4px',
            width: '24px',
            height: '24px',
            borderRadius: '50%',
            background: '#10b981',
            border: '3px solid #060911',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center'
          }}
        >
          <Radio size={12} color="#fff" />
        </div>
      </div>

      <h1
        style={{
          fontSize: '28px',
          fontWeight: 800,
          letterSpacing: '-0.02em',
          color: '#ffffff',
          marginBottom: '6px'
        }}
      >
        Voice<span style={{ color: 'var(--accent-blue)' }}>Guard</span>
      </h1>

      <div
        style={{
          display: 'inline-flex',
          alignItems: 'center',
          gap: '6px',
          background: 'rgba(56, 189, 248, 0.1)',
          border: '1px solid rgba(56, 189, 248, 0.25)',
          padding: '4px 12px',
          borderRadius: '20px',
          fontSize: '12px',
          fontWeight: 700,
          color: 'var(--accent-blue)',
          letterSpacing: '0.08em',
          textTransform: 'uppercase',
          marginBottom: '28px'
        }}
      >
        <Sparkles size={12} />
        AI Voice Security
      </div>

      <p style={{ fontSize: '13px', color: 'var(--text-muted)', maxWidth: '240px', lineHeight: 1.4 }}>
        Real-time neural deepfake detection for WebRTC & VoIP calls
      </p>

      {/* Tap to enter hint */}
      <div
        style={{
          position: 'absolute',
          bottom: '40px',
          fontSize: '11px',
          color: 'var(--text-dim)',
          letterSpacing: '0.05em'
        }}
      >
        Tap anywhere or waiting for handshake...
      </div>
    </div>
  );
};
