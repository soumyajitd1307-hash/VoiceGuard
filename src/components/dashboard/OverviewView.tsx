import React, { useState } from 'react';
import { PhoneCall, ShieldAlert, Cpu, Activity, Radio, AlertTriangle, CheckCircle2 } from 'lucide-react';
import { useCallContext } from '../../context/CallContext';
import { StatCard } from '../common/StatCard';
import { ActiveCallTable } from '../common/ActiveCallTable';
import { RiskChart } from '../common/RiskChart';
import { EventFeed } from '../common/EventFeed';
import { SecurityAlert } from '../common/SecurityAlert';
import { formatSeconds } from '../../utils/risk';
import type { BackendAlert } from '../../types';

/**
 * One authoritative B4 alert (Prompt 7). Renders B4 fields verbatim —
 * title/message/risk/timestamp/mock flag come straight from the record.
 * Acknowledge calls B4; the card flips ONLY on B4 success (no fake ack).
 */
const BackendAlertCard: React.FC<{
  alert: BackendAlert;
  onAcknowledge: (alertId: string) => Promise<void>;
  onInvestigate: () => void;
}> = ({ alert, onAcknowledge, onInvestigate }) => {
  const [acking, setAcking] = useState(false);
  const [ackError, setAckError] = useState<string | null>(null);

  const handleAck = async () => {
    if (acking || alert.acknowledged) return;
    setAcking(true);
    setAckError(null);
    try {
      await onAcknowledge(alert.alert_id);
    } catch (err) {
      // No fake success: stay unacknowledged, show the real failure.
      setAckError(err instanceof Error ? err.message : 'Acknowledge failed.');
    } finally {
      setAcking(false);
    }
  };

  return (
    <div
      style={{
        background: 'linear-gradient(135deg, rgba(127, 29, 29, 0.9), rgba(69, 10, 10, 0.9))',
        border: '1px solid #ef4444',
        borderRadius: '12px',
        padding: '14px 18px',
        display: 'flex',
        flexDirection: 'column',
        gap: '10px',
        opacity: alert.acknowledged ? 0.65 : 1,
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '12px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
          <ShieldAlert size={18} color="#f87171" />
          <div>
            <div style={{ fontSize: '14px', fontWeight: 800, color: '#ffffff' }}>
              {alert.title}
            </div>
            <div style={{ fontSize: '12px', color: '#fca5a5' }}>{alert.message}</div>
          </div>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          {alert.is_mock && (
            <span style={{ fontSize: '10px', padding: '2px 8px', borderRadius: '4px', background: 'rgba(245, 158, 11, 0.25)', color: '#fbbf24', fontWeight: 700 }}>
              DEV/MOCK MODEL
            </span>
          )}
          {alert.acknowledged ? (
            <span style={{ fontSize: '10px', padding: '2px 8px', borderRadius: '4px', background: 'rgba(16, 185, 129, 0.2)', color: '#34d399', fontWeight: 700, display: 'flex', alignItems: 'center', gap: '4px' }}>
              <CheckCircle2 size={11} /> ACKNOWLEDGED
            </span>
          ) : (
            <button
              onClick={() => void handleAck()}
              disabled={acking}
              style={{
                background: 'rgba(255, 255, 255, 0.12)',
                color: '#fff',
                border: '1px solid rgba(255, 255, 255, 0.25)',
                borderRadius: '6px',
                padding: '6px 12px',
                fontSize: '11px',
                fontWeight: 800,
                cursor: acking ? 'wait' : 'pointer',
                opacity: acking ? 0.6 : 1,
              }}
            >
              {acking ? 'SENDING…' : 'ACKNOWLEDGE'}
            </button>
          )}
          <button
            onClick={onInvestigate}
            style={{
              background: '#ffffff',
              color: '#991b1b',
              border: 'none',
              borderRadius: '6px',
              padding: '6px 12px',
              fontSize: '11px',
              fontWeight: 800,
              cursor: 'pointer',
            }}
          >
            INVESTIGATE
          </button>
        </div>
      </div>
      <div className="font-mono" style={{ fontSize: '11px', color: '#fca5a5', display: 'flex', gap: '14px', flexWrap: 'wrap' }}>
        <span>Call #{alert.call_id}</span>
        <span>Risk: {alert.risk}/100 ({alert.risk_level})</span>
        <span>t={formatSeconds(alert.timestamp)}</span>
        <span className="font-mono" style={{ fontSize: '10px', color: 'var(--text-dim)' }}>{alert.alert_id}</span>
      </div>
      {ackError && (
        <div style={{ fontSize: '11px', color: '#f87171' }}>{ackError}</div>
      )}
    </div>
  );
};

export const OverviewView: React.FC = () => {
  const {
    activeCalls,
    selectedCall,
    currentCallId,
    selectCall,
    securityAlert,
    dismissAlert,
    openInvestigation,
    systemStatus,
    detectionEventsLog,
    backendAlerts,
    acknowledgeBackendAlert,
    activeCallsStatus,
    callsError,
    refreshActiveCalls
  } = useCallContext();

  const primaryCall = selectedCall || activeCalls[0];
  // Authoritative B4 alerts for the selected call only (call-id
  // isolation at render; unacknowledged first, newest first).
  const primaryBackendAlerts = (primaryCall
    ? backendAlerts.filter(a => a.call_id === primaryCall.id)
    : []
  ).sort((a, b) => Number(a.acknowledged) - Number(b.acknowledged) || b.timestamp - a.timestamp);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
      {/* Prominent High-Risk Security Alert Banner */}
      {securityAlert && (
        <SecurityAlert
          alert={securityAlert}
          onInvestigate={() => {
            const target = activeCalls.find(c => c.id === securityAlert.callId) || primaryCall;
            if (target) openInvestigation(target);
          }}
          onDismiss={dismissAlert}
        />
      )}

      {/* Authoritative B4 alerts for the selected call (Prompt 7) */}
      {primaryBackendAlerts.map(alert => (
        <BackendAlertCard
          key={alert.alert_id}
          alert={alert}
          onAcknowledge={acknowledgeBackendAlert}
          onInvestigate={() => {
            if (primaryCall) openInvestigation(primaryCall);
          }}
        />
      ))}

      {/* Top 4 SOC Statistic Cards */}
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))',
          gap: '16px'
        }}
      >
        <StatCard
          title="Active Calls"
          value={activeCalls.length}
          subvalue="live WebRTC streams"
          icon={<PhoneCall size={18} />}
          trend="+2"
          trendPositive={true}
        />

        <StatCard
          title="Total Analyzed Calls"
          value={systemStatus.totalCallsAnalyzed.toLocaleString()}
          subvalue="sessions verified"
          icon={<Activity size={18} />}
          trend="+12%"
          trendPositive={true}
        />

        <StatCard
          title="High-Risk Deepfake Calls"
          value={systemStatus.highRiskCallsCount}
          subvalue="synthetic voice alerts"
          icon={<ShieldAlert size={18} />}
          trend="Flagged"
          trendPositive={false}
          statusColor="#ef4444"
        />

        <StatCard
          title="AI System Latency"
          value={`${systemStatus.aiEngineLatencyMs} ms`}
          subvalue="neural inference"
          icon={<Cpu size={18} />}
          trend="Optimal"
          trendPositive={true}
          statusColor="#10b981"
        />
      </div>

      {/* Middle Row: Active Calls Table (Left) & Real-Time Risk Line Chart (Right) */}
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(460px, 1fr))',
          gap: '16px'
        }}
      >
        {/* Active Calls Table */}
        <div
          className="glass-panel"
          style={{
            padding: '20px',
            display: 'flex',
            flexDirection: 'column',
            gap: '14px'
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
            <div>
              <h3 style={{ fontSize: '15px', fontWeight: 800, color: 'var(--text-main)' }}>
                Active VoIP / WebRTC Sessions
              </h3>
              <span style={{ fontSize: '12px', color: 'var(--text-dim)' }}>
                Live RTP audio packet inspection & biometric scoring
              </span>
            </div>
            <span
              style={{
                fontSize: '11px',
                fontWeight: 700,
                color: 'var(--accent-cyan)',
                display: 'flex',
                alignItems: 'center',
                gap: '5px'
              }}
            >
              <Radio size={12} className="animate-pulse" />
              {activeCalls.length} CHANNELS LIVE
            </span>
          </div>

          <ActiveCallTable
            calls={activeCalls}
            selectedCallId={currentCallId}
            onSelectCall={selectCall}
            onInvestigateCall={openInvestigation}
          />
          {activeCallsStatus === 'error' && activeCalls.length === 0 && (
            <div style={{ fontSize: '12px', color: '#f87171', marginTop: '10px', display: 'flex', alignItems: 'center', gap: '8px' }}>
              <span>{callsError || 'Call data unavailable.'}</span>
              <button
                onClick={() => void refreshActiveCalls()}
                style={{
                  background: 'transparent',
                  border: '1px solid var(--border-subtle)',
                  borderRadius: '6px',
                  padding: '4px 10px',
                  color: 'var(--text-main)',
                  fontSize: '11px',
                  fontWeight: 700,
                  cursor: 'pointer'
                }}
              >
                Retry
              </button>
            </div>
          )}
        </div>

        {/* Real-Time Risk Line Chart */}
        <div
          className="glass-panel"
          style={{
            padding: '20px',
            display: 'flex',
            flexDirection: 'column',
            gap: '14px'
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
            <div>
              <h3 style={{ fontSize: '15px', fontWeight: 800, color: 'var(--text-main)' }}>
                Real-Time Risk Telemetry{primaryCall ? ` — Call #${primaryCall.id} (${primaryCall.caller.name})` : ' — No active call'}
              </h3>
              <span style={{ fontSize: '12px', color: 'var(--text-dim)' }}>
                Neural vocoder artifacts vs biological acoustic threshold
              </span>
            </div>
            <div style={{ textAlign: 'right' }}>
              <span
                className="font-mono"
                style={{
                  fontSize: '14px',
                  fontWeight: 800,
                  color: primaryCall?.currentRiskLevel === 'HIGH' ? '#ef4444' : '#38bdf8'
                }}
              >
                {primaryCall ? `${primaryCall.currentRisk} / 100` : '— / 100'}
              </span>
            </div>
          </div>

          <RiskChart data={primaryCall ? primaryCall.riskHistory : []} height={180} />
        </div>
      </div>

      {/* Bottom Row: Live Detection Event Feed */}
      <div
        className="glass-panel"
        style={{
          padding: '20px',
          display: 'flex',
          flexDirection: 'column',
          gap: '14px'
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <div>
            <h3 style={{ fontSize: '15px', fontWeight: 800, color: 'var(--text-main)' }}>
              Live AI Detection Event Feed
            </h3>
            <span style={{ fontSize: '12px', color: 'var(--text-dim)' }}>
              Real-time chronological events from the audio neural classifier
            </span>
          </div>
          <span className="font-mono" style={{ fontSize: '11px', color: 'var(--text-muted)' }}>
            Auto-streaming enabled
          </span>
        </div>

        <EventFeed events={detectionEventsLog} maxItems={8} />
      </div>
    </div>
  );
};
