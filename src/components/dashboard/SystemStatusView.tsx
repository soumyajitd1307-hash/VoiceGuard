import React from 'react';
import { useCallContext } from '../../context/CallContext';
import { SystemStatus } from '../common/SystemStatus';
import { Server, Activity, ShieldCheck, Cpu, HardDrive, Network } from 'lucide-react';

export const SystemStatusView: React.FC = () => {
  const { systemStatus, wsStatus } = useCallContext();

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
      <SystemStatus status={systemStatus} />

      {/* Cluster Nodes Health */}
      <div className="glass-panel" style={{ padding: '20px' }}>
        <h3 style={{ fontSize: '15px', fontWeight: 800, color: 'var(--text-main)', marginBottom: '14px' }}>
          Real-Time VoiceGuard Cluster Topology
        </h3>

        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))', gap: '12px' }}>
          {[
            { name: 'Node-US-East-1 (Primary)', role: 'WebRTC Gateway', status: 'Healthy', load: '18%' },
            { name: 'Node-US-East-2', role: 'Neural Classifier', status: 'Healthy', load: '32%' },
            { name: 'Node-EU-Central-1', role: 'Acoustic Model Relay', status: 'Healthy', load: '14%' },
            { name: 'Node-AP-South-1', role: 'Evidence Vault Storage', status: 'Healthy', load: '21%' }
          ].map((node, i) => (
            <div key={i} style={{ background: 'var(--bg-secondary)', padding: '14px', borderRadius: '8px', border: '1px solid var(--border-subtle)' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <span style={{ fontSize: '13px', fontWeight: 700, color: 'var(--text-main)' }}>{node.name}</span>
                <span style={{ fontSize: '10px', color: '#34d399', fontWeight: 700, background: 'rgba(16,185,129,0.15)', padding: '2px 6px', borderRadius: '4px' }}>
                  {node.status}
                </span>
              </div>
              <div style={{ fontSize: '11px', color: 'var(--text-dim)', marginTop: '4px' }}>Role: {node.role}</div>
              <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: '8px', fontSize: '11px' }}>
                <span style={{ color: 'var(--text-muted)' }}>GPU/Inference Load</span>
                <span className="font-mono" style={{ color: 'var(--accent-blue)', fontWeight: 700 }}>{node.load}</span>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
};
