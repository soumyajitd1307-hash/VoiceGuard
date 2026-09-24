import React, { useState } from 'react';
import {
  LayoutDashboard,
  PhoneCall,
  Activity,
  AlertTriangle,
  Disc,
  Clock,
  Server,
  Shield,
  Radio,
  Search,
  Zap,
  HelpCircle
} from 'lucide-react';
import { useCallContext } from '../../context/CallContext';
import { WebSocketStatus } from '../common/WebSocketStatus';
import { OverviewView } from './OverviewView';
import { ActiveCallsView } from './ActiveCallsView';
import { LiveMonitoringView } from './LiveMonitoringView';
import { DetectionEventsView } from './DetectionEventsView';
import { EvidenceView } from './EvidenceView';
import { CallHistoryView } from './CallHistoryView';
import { SystemStatusView } from './SystemStatusView';
import { InvestigationModal } from './InvestigationModal';

export type DashboardTab = 
  | 'overview'
  | 'active_calls'
  | 'live_monitoring'
  | 'detection_events'
  | 'evidence'
  | 'call_history'
  | 'system_status';

export const DashboardLayout: React.FC = () => {
  const [activeTab, setActiveTab] = useState<DashboardTab>('overview');
  const {
    activeCalls,
    wsStatus,
    wsMessage,
    isDemoMode,
    investigationCall,
    closeInvestigation,
    endCall,
    triggerHighRiskDemo,
    connectWebSocket
  } = useCallContext();

  const navItems = [
    { id: 'overview' as const, label: 'Overview', icon: <LayoutDashboard size={17} /> },
    { id: 'active_calls' as const, label: 'Active Calls', icon: <PhoneCall size={17} />, count: activeCalls.length },
    { id: 'live_monitoring' as const, label: 'Live Monitoring', icon: <Activity size={17} /> },
    { id: 'detection_events' as const, label: 'Detection Events', icon: <AlertTriangle size={17} /> },
    { id: 'evidence' as const, label: 'Evidence', icon: <Disc size={17} /> },
    { id: 'call_history' as const, label: 'Call History', icon: <Clock size={17} /> },
    { id: 'system_status' as const, label: 'System Status', icon: <Server size={17} /> }
  ];

  return (
    <div style={{ display: 'flex', minHeight: '100%', width: '100%', background: 'var(--bg-primary)' }}>
      {/* Sidebar Navigation */}
      <aside
        style={{
          width: '240px',
          minWidth: '240px',
          background: 'var(--bg-secondary)',
          borderRight: '1px solid var(--border-subtle)',
          display: 'flex',
          flexDirection: 'column',
          justifyContent: 'space-between',
          padding: '20px 14px'
        }}
      >
        <div style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
          {/* Logo Branding */}
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px', padding: '0 6px' }}>
            <div
              style={{
                width: '34px',
                height: '34px',
                borderRadius: '8px',
                background: 'linear-gradient(135deg, #0284c7, #0369a1)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                color: '#fff',
                boxShadow: '0 0 14px rgba(2, 132, 199, 0.4)'
              }}
            >
              <Shield size={20} />
            </div>
            <div>
              <div style={{ fontSize: '16px', fontWeight: 800, color: '#ffffff', letterSpacing: '-0.02em' }}>
                Voice<span style={{ color: 'var(--accent-blue)' }}>Guard</span>
              </div>
              <div style={{ fontSize: '10px', color: 'var(--accent-cyan)', fontWeight: 700, letterSpacing: '0.08em', textTransform: 'uppercase' }}>
                SOC Command Center
              </div>
            </div>
          </div>

          {/* Navigation Items */}
          <nav style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
            {navItems.map(item => {
              const active = activeTab === item.id;
              return (
                <button
                  key={item.id}
                  onClick={() => setActiveTab(item.id)}
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                    padding: '10px 12px',
                    borderRadius: '8px',
                    background: active ? 'rgba(56, 189, 248, 0.12)' : 'transparent',
                    border: active ? '1px solid rgba(56, 189, 248, 0.25)' : '1px solid transparent',
                    color: active ? '#ffffff' : 'var(--text-muted)',
                    fontWeight: active ? 700 : 500,
                    fontSize: '13px',
                    cursor: 'pointer',
                    transition: 'all 0.15s ease'
                  }}
                >
                  <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                    <span style={{ color: active ? 'var(--accent-blue)' : 'var(--text-dim)' }}>
                      {item.icon}
                    </span>
                    <span>{item.label}</span>
                  </div>

                  {item.count !== undefined && (
                    <span
                      style={{
                        fontSize: '11px',
                        padding: '1px 6px',
                        borderRadius: '10px',
                        background: active ? 'var(--accent-blue)' : 'rgba(255, 255, 255, 0.08)',
                        color: active ? '#fff' : 'var(--text-muted)',
                        fontWeight: 700
                      }}
                    >
                      {item.count}
                    </span>
                  )}
                </button>
              );
            })}
          </nav>
        </div>

        {/* Sidebar Footer */}
        <div style={{ borderTop: '1px solid var(--border-subtle)', paddingTop: '16px', display: 'flex', flexDirection: 'column', gap: '10px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '11px', color: 'var(--text-dim)' }}>
            <Radio size={12} color="#10b981" />
            <span>AI Neural Core: v3.4</span>
          </div>
          <div style={{ fontSize: '11px', color: 'var(--text-dim)' }}>
            RFC 3550 WebRTC RTP Secure Node
          </div>
        </div>
      </aside>

      {/* Main Content Area */}
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minWidth: 0 }}>
        {/* Top Header Bar */}
        <header
          style={{
            height: '64px',
            borderBottom: '1px solid var(--border-subtle)',
            background: 'var(--bg-secondary)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            padding: '0 24px',
            gap: '16px'
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: '14px' }}>
            <h1 style={{ fontSize: '17px', fontWeight: 800, color: 'var(--text-main)', textTransform: 'capitalize' }}>
              {activeTab.replace('_', ' ')}
            </h1>
            <WebSocketStatus
              status={wsStatus}
              message={wsMessage}
              isDemoMode={isDemoMode}
              onReconnect={connectWebSocket}
            />
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
            {/* Demo-only trigger: hidden in live mode so simulated risk can
                never be injected into a real call session. */}
            {isDemoMode && (
              <button
                onClick={triggerHighRiskDemo}
              style={{
                background: 'rgba(239, 68, 68, 0.15)',
                border: '1px solid rgba(239, 68, 68, 0.4)',
                borderRadius: '8px',
                color: '#f87171',
                padding: '6px 12px',
                fontSize: '11px',
                fontWeight: 700,
                cursor: 'pointer',
                display: 'flex',
                alignItems: 'center',
                gap: '6px'
              }}
              title="Fast-forward simulation to 18s (triggers High-Risk alert)"
            >
              <Zap size={13} />
              Simulate High Risk (18s)
              </button>
            )}
          </div>
        </header>

        {/* Dynamic Tab Body */}
        <main style={{ flex: 1, padding: '24px', overflowY: 'auto' }}>
          {activeTab === 'overview' && <OverviewView />}
          {activeTab === 'active_calls' && <ActiveCallsView />}
          {activeTab === 'live_monitoring' && <LiveMonitoringView />}
          {activeTab === 'detection_events' && <DetectionEventsView />}
          {activeTab === 'evidence' && <EvidenceView />}
          {activeTab === 'call_history' && <CallHistoryView />}
          {activeTab === 'system_status' && <SystemStatusView />}
        </main>
      </div>

      {/* Forensic Investigation Modal */}
      <InvestigationModal
        call={investigationCall}
        onClose={closeInvestigation}
        onTerminate={endCall}
      />
    </div>
  );
};
