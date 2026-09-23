import React from 'react';
import { Wifi, WifiOff, RefreshCw } from 'lucide-react';
import { WSConnectionStatus } from '../../types';

interface WebSocketStatusProps {
  status: WSConnectionStatus;
  message?: string;
  onReconnect?: () => void;
  isDemoMode?: boolean;
}

export const WebSocketStatus: React.FC<WebSocketStatusProps> = ({
  status,
  message,
  onReconnect,
  isDemoMode = false
}) => {
  const isConnected = status === 'CONNECTED';
  const isConnecting = status === 'CONNECTING' || status === 'RECONNECTING';

  const statusColor = isConnected ? '#10b981' : isConnecting ? '#f59e0b' : '#ef4444';
  const statusBg = isConnected ? 'rgba(16, 185, 129, 0.12)' : isConnecting ? 'rgba(245, 158, 11, 0.12)' : 'rgba(239, 68, 68, 0.12)';

  return (
    <div
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: '8px',
        background: statusBg,
        border: `1px solid ${statusColor}40`,
        borderRadius: '20px',
        padding: '4px 12px',
        fontSize: '11px',
        fontWeight: 600
      }}
    >
      <span
        style={{
          width: '7px',
          height: '7px',
          borderRadius: '50%',
          backgroundColor: statusColor,
          boxShadow: `0 0 6px ${statusColor}`
        }}
      />

      <span style={{ color: 'var(--text-main)' }}>
        {isDemoMode ? (
          <>
            <strong style={{ color: 'var(--accent-cyan)' }}>DEMO SIMULATION:</strong> Stream Synced
          </>
        ) : (
          <>
            WS: <strong style={{ color: statusColor }}>{status}</strong>
          </>
        )}
      </span>

      {(!isConnected && !isDemoMode && onReconnect) && (
        <button
          onClick={onReconnect}
          style={{
            background: 'transparent',
            border: 'none',
            color: 'var(--accent-blue)',
            cursor: 'pointer',
            display: 'flex',
            alignItems: 'center',
            padding: '2px'
          }}
          title="Retry WebSocket connection"
        >
          <RefreshCw size={11} className={isConnecting ? 'animate-spin' : ''} />
        </button>
      )}
    </div>
  );
};
