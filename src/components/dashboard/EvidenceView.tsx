import React from 'react';
import { Disc, ShieldAlert, FileText, CheckCircle2, Download } from 'lucide-react';
import { useCallContext } from '../../context/CallContext';
import { EvidencePlayer } from '../common/EvidencePlayer';
import { INITIAL_EVIDENCE_1042 } from '../../services/mockData';

export const EvidenceView: React.FC = () => {
  const { activeCalls, selectedCall } = useCallContext();

  const currentCall = selectedCall || activeCalls[0];
  const evidence = currentCall?.evidence || INITIAL_EVIDENCE_1042;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
      {/* Evidence Banner */}
      <div className="glass-panel" style={{ padding: '20px', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <div>
          <h2 style={{ fontSize: '18px', fontWeight: 800, color: 'var(--text-main)', display: 'flex', alignItems: 'center', gap: '8px' }}>
            <Disc size={20} color="var(--accent-cyan)" />
            Cryptographic Voice Evidence Vault
          </h2>
          <span style={{ fontSize: '12px', color: 'var(--text-muted)' }}>
            Tamper-evident audio captures with neural vocoder acoustic signatures
          </span>
        </div>

        <button
          style={{
            background: 'rgba(255, 255, 255, 0.08)',
            border: '1px solid var(--border-medium)',
            borderRadius: '8px',
            padding: '8px 14px',
            color: '#fff',
            fontSize: '12px',
            fontWeight: 700,
            cursor: 'pointer',
            display: 'flex',
            alignItems: 'center',
            gap: '6px'
          }}
        >
          <Download size={14} />
          Export WAV & Metadata JSON
        </button>
      </div>

      {/* Main Evidence Player Card */}
      <div className="glass-panel" style={{ padding: '24px' }}>
        <h3 style={{ fontSize: '15px', fontWeight: 800, color: 'var(--text-main)', marginBottom: '14px' }}>
          Active Call #{evidence.callId} — Audio Evidence ({evidence.formattedTime})
        </h3>
        <EvidencePlayer evidence={evidence} />
      </div>

      {/* Forensic Chain of Custody */}
      <div
        className="glass-panel"
        style={{
          padding: '20px',
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))',
          gap: '16px'
        }}
      >
        <div>
          <span style={{ fontSize: '11px', color: 'var(--text-dim)', textTransform: 'uppercase' }}>Hashing Algorithm</span>
          <div className="font-mono" style={{ fontSize: '13px', fontWeight: 700, color: 'var(--text-main)', marginTop: '2px' }}>
            SHA-256 (HMAC-Verified)
          </div>
          <div className="font-mono" style={{ fontSize: '11px', color: 'var(--text-dim)', wordBreak: 'break-all' }}>
            e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
          </div>
        </div>

        <div>
          <span style={{ fontSize: '11px', color: 'var(--text-dim)', textTransform: 'uppercase' }}>Sample Rate / Depth</span>
          <div className="font-mono" style={{ fontSize: '13px', fontWeight: 700, color: 'var(--text-main)', marginTop: '2px' }}>
            48,000 Hz • 24-bit PCM
          </div>
          <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>Raw WebRTC Opus RTP frame dump</div>
        </div>

        <div>
          <span style={{ fontSize: '11px', color: 'var(--text-dim)', textTransform: 'uppercase' }}>Classifier Model</span>
          <div style={{ fontSize: '13px', fontWeight: 700, color: 'var(--accent-blue)', marginTop: '2px' }}>
            VoiceGuard Neural-v3.4.2
          </div>
          <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>Trained on 1.2M synthetic & human audio hours</div>
        </div>
      </div>
    </div>
  );
};
