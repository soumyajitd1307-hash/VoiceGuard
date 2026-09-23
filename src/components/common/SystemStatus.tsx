import React from 'react';
import { Server, Activity, ShieldCheck, Database, Radio, Cpu } from 'lucide-react';
import { SystemStatus as SystemStatusType } from '../../types';

interface SystemStatusProps {
  status: SystemStatusType;
}

export const SystemStatus: React.FC<SystemStatusProps> = ({ status }) => {
  return (
    <div
      className="glass-panel"
      style={{
        padding: '20px',
        display: 'flex',
        flexDirection: 'column',
        gap: '16px'
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <Server size={18} color="var(--accent-blue)" />
          <h3 style={{ fontSize: '15px', fontWeight: 700, color: 'var(--text-main)' }}>
            System Infrastructure & Model Health
          </h3>
        </div>
        <span
          style={{
            fontSize: '11px',
            fontWeight: 800,
            padding: '3px 8px',
            borderRadius: '4px',
            background: 'rgba(16, 185, 129, 0.15)',
            color: '#34d399',
            border: '1px solid rgba(16, 185, 129, 0.3)'
          }}
        >
          {status.serviceStatus}
        </span>
      </div>

      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))',
          gap: '12px'
        }}
      >
        <div style={{ background: 'var(--bg-secondary)', padding: '12px', borderRadius: '8px' }}>
          <div style={{ fontSize: '11px', color: 'var(--text-dim)', textTransform: 'uppercase' }}>AI Detector Latency</div>
          <div className="font-mono" style={{ fontSize: '18px', fontWeight: 800, color: '#38bdf8' }}>
            {status.aiEngineLatencyMs} ms
          </div>
          <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>Real-time packet inference</div>
        </div>

        <div style={{ background: 'var(--bg-secondary)', padding: '12px', borderRadius: '8px' }}>
          <div style={{ fontSize: '11px', color: 'var(--text-dim)', textTransform: 'uppercase' }}>Model Version</div>
          <div style={{ fontSize: '14px', fontWeight: 700, color: 'var(--text-main)', marginTop: '2px' }}>
            {status.modelVersion}
          </div>
          <div style={{ fontSize: '11px', color: '#10b981' }}>{status.modelAccuracy}% Benchmark accuracy</div>
        </div>

        <div style={{ background: 'var(--bg-secondary)', padding: '12px', borderRadius: '8px' }}>
          <div style={{ fontSize: '11px', color: 'var(--text-dim)', textTransform: 'uppercase' }}>WebRTC Mesh Nodes</div>
          <div className="font-mono" style={{ fontSize: '18px', fontWeight: 800, color: '#34d399' }}>
            {status.webrtcNodesHealthy} / {status.webrtcNodesTotal}
          </div>
          <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>Opus 48kHz RTP streams</div>
        </div>

        <div style={{ background: 'var(--bg-secondary)', padding: '12px', borderRadius: '8px' }}>
          <div style={{ fontSize: '11px', color: 'var(--text-dim)', textTransform: 'uppercase' }}>Active WS Sockets</div>
          <div className="font-mono" style={{ fontSize: '18px', fontWeight: 800, color: 'var(--accent-cyan)' }}>
            {status.wsConnections} Clients
          </div>
          <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>Zero-loss telemetry sync</div>
        </div>
      </div>
    </div>
  );
};
