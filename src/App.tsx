import React, { useState } from 'react';
import { CallProvider } from './context/CallContext';
import { MobileApp } from './components/mobile/MobileApp';
import { DashboardLayout } from './components/dashboard/DashboardLayout';
import { DemoControlsBar, PresentationMode } from './components/demo/DemoControlsBar';
import './index.css';

export function VoiceGuardApp() {
  const [presentationMode, setPresentationMode] = useState<PresentationMode>('dual');

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100vh', width: '100vw', overflow: 'hidden', background: 'var(--bg-primary)' }}>
      {/* Top Demo & View Switcher Bar */}
      <DemoControlsBar
        presentationMode={presentationMode}
        onSetPresentationMode={setPresentationMode}
      />

      {/* Main View Area based on Mode */}
      <div style={{ flex: 1, display: 'flex', overflow: 'hidden', position: 'relative' }}>
        {/* DUAL MODE: Side-by-side presentation (Mobile + Web SOC Dashboard) */}
        {presentationMode === 'dual' && (
          <div style={{ display: 'flex', width: '100%', height: '100%', overflow: 'hidden' }}>
            {/* Left Column: Mobile App */}
            <div
              style={{
                width: '440px',
                minWidth: '400px',
                background: '#05070d',
                borderRight: '1px solid var(--border-medium)',
                display: 'flex',
                flexDirection: 'column',
                alignItems: 'center',
                justifyContent: 'center',
                padding: '16px',
                overflowY: 'auto'
              }}
            >
              <div style={{ marginBottom: '10px', textAlign: 'center' }}>
                <span
                  style={{
                    fontSize: '11px',
                    fontWeight: 800,
                    letterSpacing: '0.08em',
                    textTransform: 'uppercase',
                    color: 'var(--accent-blue)',
                    background: 'rgba(56, 189, 248, 0.1)',
                    padding: '3px 10px',
                    borderRadius: '12px',
                    border: '1px solid rgba(56, 189, 248, 0.25)'
                  }}
                >
                  📱 Mobile Client View (Caller/Receiver)
                </span>
              </div>
              <MobileApp embeddedInShell={true} />
            </div>

            {/* Right Column: SOC Security Dashboard */}
            <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden', minWidth: 0 }}>
              <DashboardLayout />
            </div>
          </div>
        )}

        {/* MOBILE ONLY MODE */}
        {presentationMode === 'mobile' && (
          <div
            style={{
              width: '100%',
              height: '100%',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              background: '#05070d',
              padding: '24px',
              overflowY: 'auto'
            }}
          >
            <MobileApp embeddedInShell={true} />
          </div>
        )}

        {/* SOC DASHBOARD ONLY MODE */}
        {presentationMode === 'dashboard' && (
          <div style={{ width: '100%', height: '100%', display: 'flex', overflow: 'hidden' }}>
            <DashboardLayout />
          </div>
        )}
      </div>
    </div>
  );
}

export default function App() {
  return (
    <CallProvider>
      <VoiceGuardApp />
    </CallProvider>
  );
}
