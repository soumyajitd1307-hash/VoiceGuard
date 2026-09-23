import React from 'react';
import { PhoneCall, ShieldAlert, Cpu, Activity, Radio, AlertTriangle } from 'lucide-react';
import { useCallContext } from '../../context/CallContext';
import { StatCard } from '../common/StatCard';
import { ActiveCallTable } from '../common/ActiveCallTable';
import { RiskChart } from '../common/RiskChart';
import { EventFeed } from '../common/EventFeed';
import { SecurityAlert } from '../common/SecurityAlert';

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
    detectionEventsLog
  } = useCallContext();

  const primaryCall = selectedCall || activeCalls[0];

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
                Real-Time Risk Telemetry — Call #{primaryCall ? primaryCall.id : '1042'} ({primaryCall ? primaryCall.caller.name : 'Rahul'})
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
                {primaryCall ? primaryCall.currentRisk : 18} / 100
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
