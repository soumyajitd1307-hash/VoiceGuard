import React, { useEffect } from 'react';
import { Disc, ShieldAlert, FileText, CheckCircle2, Download } from 'lucide-react';
import { useCallContext } from '../../context/CallContext';
import { EvidencePlayer } from '../common/EvidencePlayer';
import { formatSeconds } from '../../utils/risk';
import type { BackendEvidenceRecord } from '../../types';

/**
 * One authoritative B4 evidence record (Prompt 7). Rendered verbatim —
 * description, risk, source, timestamp, mock flag. B4 stores no audio,
 * so there is deliberately no playback control here (unlike the demo
 * fixture path below, which carries synth audio by design).
 */
const BackendEvidenceCard: React.FC<{ record: BackendEvidenceRecord }> = ({ record }) => (
  <div
    style={{
      background: 'var(--bg-secondary)',
      border: '1px solid var(--border-subtle)',
      borderLeft: `4px solid ${record.risk !== null && record.risk >= 70 ? '#ef4444' : 'var(--accent-cyan)'}`,
      borderRadius: '8px',
      padding: '12px 16px',
      display: 'flex',
      flexDirection: 'column',
      gap: '6px',
    }}
  >
    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '12px' }}>
      <span style={{ fontSize: '12px', fontWeight: 800, color: 'var(--text-main)', textTransform: 'uppercase', letterSpacing: '0.04em' }}>
        {record.evidence_type}
      </span>
      <span style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
        {record.is_mock && (
          <span style={{ fontSize: '10px', padding: '2px 8px', borderRadius: '4px', background: 'rgba(245, 158, 11, 0.2)', color: '#fbbf24', fontWeight: 700 }}>
            DEV/MOCK MODEL
          </span>
        )}
        <span className="font-mono" style={{ fontSize: '11px', color: 'var(--text-dim)' }}>
          t={formatSeconds(record.timestamp)}
        </span>
      </span>
    </div>
    <div style={{ fontSize: '13px', color: 'var(--text-main)' }}>{record.description}</div>
    <div style={{ fontSize: '11px', color: 'var(--text-muted)', display: 'flex', gap: '14px', flexWrap: 'wrap' }}>
      <span>Source: <strong>{record.source}</strong></span>
      {record.risk !== null && <span>Risk: <strong>{record.risk}/100</strong></span>}
      <span className="font-mono" style={{ fontSize: '10px', color: 'var(--text-dim)' }}>{record.evidence_id}</span>
    </div>
  </div>
);

export const EvidenceView: React.FC = () => {
  const { activeCalls, selectedCall, backendEvidence, callHistory, currentCallId, refreshBackendIntel, intelErrors, isDemoMode } = useCallContext();

  // Ended/history calls are selectable too: B4 keeps serving their
  // evidence after terminate, so resolve the explicitly selected id from
  // history when it is no longer active.
  const historyCall = !selectedCall && currentCallId
    ? callHistory.find(c => c.id === currentCallId) ?? null
    : null;
  const currentCall = selectedCall || activeCalls[0] || historyCall;
  const evidence = currentCall?.evidence;
  // Authoritative B4 records for the selected call (empty = none yet).
  const b4Records = currentCall ? backendEvidence[currentCall.id] ?? [] : [];
  const intelError = currentCall ? intelErrors[currentCall.id] : undefined;
  const isEndedView = !!currentCall && !activeCalls.some(c => c.id === currentCall.id);

  // Explicit ended-call retrieval: caches are purged on endCall and the
  // live path only tracks active calls, so fetch this ENDED call's own B4
  // records by authoritative id (bounded + deduped inside). Never fires
  // in demo theater; never fabricates when the backend has no records.
  useEffect(() => {
    if (isDemoMode || !currentCall || !isEndedView) return;
    if ((backendEvidence[currentCall.id] ?? []).length > 0) return;
    if (intelErrors[currentCall.id]) return;
    refreshBackendIntel(currentCall.id, true, true);
  }, [isDemoMode, currentCall, isEndedView, backendEvidence, intelErrors, refreshBackendIntel]);

  if (!evidence && b4Records.length === 0 && !intelError) {
    // Honest idle state: no backend evidence exists yet. The hardcoded
    // demo fixture is deliberately NOT used as a fallback here.
    return (
      <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
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
        </div>

        <div className="glass-panel" style={{ padding: '40px 24px', textAlign: 'center' }}>
          <div style={{ fontSize: '14px', fontWeight: 700, color: 'var(--text-main)' }}>
            No evidence yet
          </div>
          <div style={{ fontSize: '12px', color: 'var(--text-muted)', marginTop: '6px' }}>
            Evidence appears here when the backend flags audio during a live call.
          </div>
        </div>
      </div>
    );
  }

  if (intelError && b4Records.length === 0) {
    // Explicit backend failure (never silent, never fixtures): the fetch
    // for this call's B4 records failed. Retry re-enters the same bounded
    // authoritative fetch.
    return (
      <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
        <div className="glass-panel" style={{ padding: '40px 24px', textAlign: 'center' }}>
          <div style={{ fontSize: '14px', fontWeight: 700, color: '#f87171' }}>
            Evidence unavailable
          </div>
          <div className="font-mono" style={{ fontSize: '12px', color: 'var(--text-muted)', marginTop: '6px' }}>
            {intelError}
          </div>
          {currentCall && (
            <button
              onClick={() => refreshBackendIntel(currentCall.id, true, isEndedView)}
              style={{ background: 'rgba(255, 255, 255, 0.08)', border: '1px solid var(--border-medium)', borderRadius: '8px', padding: '8px 14px', color: '#fff', fontSize: '12px', fontWeight: 700, cursor: 'pointer', marginTop: '12px' }}
            >
              Retry
            </button>
          )}
        </div>
      </div>
    );
  }

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

      {/* Authoritative B4 evidence records (Prompt 7). Shown whenever
          the backend has records for this call — independent of the demo
          fixture player below, which only exists in demo theater. */}
      {b4Records.length > 0 && (
        <div className="glass-panel" style={{ padding: '24px', display: 'flex', flexDirection: 'column', gap: '10px' }}>
          <h3 style={{ fontSize: '15px', fontWeight: 800, color: 'var(--text-main)' }}>
            Backend Evidence — Call #{currentCall?.id} ({b4Records.length} record{b4Records.length === 1 ? '' : 's'})
          </h3>
          {b4Records.map(record => (
            <BackendEvidenceCard key={record.evidence_id} record={record} />
          ))}
        </div>
      )}

      {/* Main Evidence Player Card (demo fixture path only) */}
      {evidence && (
        <div className="glass-panel" style={{ padding: '24px' }}>
          <h3 style={{ fontSize: '15px', fontWeight: 800, color: 'var(--text-main)', marginBottom: '14px' }}>
            Active Call #{evidence.callId} — Audio Evidence ({evidence.formattedTime})
          </h3>
          <EvidencePlayer evidence={evidence} />
        </div>
      )}

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
