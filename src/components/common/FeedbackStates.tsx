import React from 'react';
import { Loader2, AlertCircle, Inbox, RefreshCw } from 'lucide-react';

export const LoadingState: React.FC<{ message?: string }> = ({ message = 'Initializing VoiceGuard AI Engine...' }) => (
  <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', padding: '40px', gap: '14px' }}>
    <Loader2 size={32} className="animate-spin" color="var(--accent-blue)" />
    <span style={{ fontSize: '13px', color: 'var(--text-muted)', fontWeight: 600 }}>{message}</span>
  </div>
);

export const ErrorState: React.FC<{ title?: string; message?: string; onRetry?: () => void }> = ({
  title = 'System Connection Error',
  message = 'Unable to establish secure telemetry connection with the backend detector node.',
  onRetry
}) => (
  <div
    style={{
      background: 'rgba(239, 68, 68, 0.08)',
      border: '1px solid rgba(239, 68, 68, 0.3)',
      borderRadius: '12px',
      padding: '24px',
      display: 'flex',
      flexDirection: 'column',
      alignItems: 'center',
      textAlign: 'center',
      gap: '12px'
    }}
  >
    <AlertCircle size={32} color="#ef4444" />
    <h4 style={{ fontSize: '15px', fontWeight: 700, color: '#f87171' }}>{title}</h4>
    <p style={{ fontSize: '13px', color: 'var(--text-muted)', maxWidth: '420px' }}>{message}</p>
    {onRetry && (
      <button
        onClick={onRetry}
        style={{
          background: 'rgba(255, 255, 255, 0.1)',
          border: '1px solid var(--border-medium)',
          borderRadius: '6px',
          padding: '6px 14px',
          color: '#ffffff',
          fontSize: '12px',
          fontWeight: 600,
          cursor: 'pointer',
          display: 'flex',
          alignItems: 'center',
          gap: '6px',
          marginTop: '6px'
        }}
      >
        <RefreshCw size={12} />
        Retry Connection
      </button>
    )}
  </div>
);

export const EmptyState: React.FC<{ title?: string; message?: string; icon?: React.ReactNode }> = ({
  title = 'No Data Available',
  message = 'There are no active records matching your security filters.',
  icon
}) => (
  <div
    style={{
      padding: '40px 20px',
      display: 'flex',
      flexDirection: 'column',
      alignItems: 'center',
      justifyContent: 'center',
      textAlign: 'center',
      color: 'var(--text-dim)',
      gap: '10px'
    }}
  >
    {icon || <Inbox size={36} color="var(--text-dim)" />}
    <h5 style={{ fontSize: '14px', fontWeight: 700, color: 'var(--text-muted)' }}>{title}</h5>
    <p style={{ fontSize: '12px', maxWidth: '320px' }}>{message}</p>
  </div>
);
