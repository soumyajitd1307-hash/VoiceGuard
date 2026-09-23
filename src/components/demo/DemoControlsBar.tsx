import React, { useState, useEffect } from 'react';
import {
  Play,
  Pause,
  RotateCcw,
  Zap,
  Smartphone,
  Layout,
  Columns,
  Radio,
  ToggleLeft,
  ToggleRight,
  ShieldAlert,
  Volume2
} from 'lucide-react';
import { useCallContext } from '../../context/CallContext';
import { demoSimulator, DemoStep } from '../../services/demoSimulator';

export type PresentationMode = 'dual' | 'mobile' | 'dashboard';

interface DemoControlsBarProps {
  presentationMode: PresentationMode;
  onSetPresentationMode: (mode: PresentationMode) => void;
}

export const DemoControlsBar: React.FC<DemoControlsBarProps> = ({
  presentationMode,
  onSetPresentationMode
}) => {
  const {
    isDemoMode,
    toggleDemoMode,
    triggerHighRiskDemo,
    resetDemoCall,
    startCall,
    selectedCall,
    activeCalls
  } = useCallContext();

  const [simStep, setSimStep] = useState<DemoStep | null>(null);
  const [isSimulating, setIsSimulating] = useState<boolean>(false);

  useEffect(() => {
    const unsub = demoSimulator.subscribe((step, isRunning) => {
      setSimStep(step);
      setIsSimulating(isRunning);
    });
    return unsub;
  }, []);

  const currentSec = simStep?.second ?? 0;
  const currentRisk = simStep?.risk ?? (selectedCall?.currentRisk || 18);

  return (
    <div
      style={{
        background: '#090d16',
        borderBottom: '1px solid var(--border-medium)',
        padding: '8px 16px',
        display: 'flex',
        flexWrap: 'wrap',
        alignItems: 'center',
        justifyContent: 'space-between',
        gap: '12px',
        zIndex: 100
      }}
    >
      {/* Left: View Mode Switcher */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
        <span style={{ fontSize: '11px', fontWeight: 800, textTransform: 'uppercase', color: 'var(--text-dim)', letterSpacing: '0.06em' }}>
          Presentation View:
        </span>

        <div style={{ display: 'flex', background: 'var(--bg-secondary)', padding: '3px', borderRadius: '8px', border: '1px solid var(--border-subtle)' }}>
          <button
            onClick={() => onSetPresentationMode('dual')}
            style={{
              background: presentationMode === 'dual' ? 'var(--accent-blue)' : 'transparent',
              color: presentationMode === 'dual' ? '#fff' : 'var(--text-muted)',
              border: 'none',
              borderRadius: '6px',
              padding: '5px 10px',
              fontSize: '11px',
              fontWeight: 700,
              cursor: 'pointer',
              display: 'flex',
              alignItems: 'center',
              gap: '6px'
            }}
            title="Side-by-side view showing both Mobile App and SOC Dashboard"
          >
            <Columns size={13} />
            Dual Live Demo (Shared Call #1042)
          </button>

          <button
            onClick={() => onSetPresentationMode('mobile')}
            style={{
              background: presentationMode === 'mobile' ? 'var(--accent-blue)' : 'transparent',
              color: presentationMode === 'mobile' ? '#fff' : 'var(--text-muted)',
              border: 'none',
              borderRadius: '6px',
              padding: '5px 10px',
              fontSize: '11px',
              fontWeight: 700,
              cursor: 'pointer',
              display: 'flex',
              alignItems: 'center',
              gap: '6px'
            }}
          >
            <Smartphone size={13} />
            Mobile App
          </button>

          <button
            onClick={() => onSetPresentationMode('dashboard')}
            style={{
              background: presentationMode === 'dashboard' ? 'var(--accent-blue)' : 'transparent',
              color: presentationMode === 'dashboard' ? '#fff' : 'var(--text-muted)',
              border: 'none',
              borderRadius: '6px',
              padding: '5px 10px',
              fontSize: '11px',
              fontWeight: 700,
              cursor: 'pointer',
              display: 'flex',
              alignItems: 'center',
              gap: '6px'
            }}
          >
            <Layout size={13} />
            SOC Dashboard
          </button>
        </div>
      </div>

      {/* Center: Hackathon Step Progression Bar (0s -> 5s -> 10s -> 14s -> 18s) */}
      {isDemoMode && (
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <span style={{ fontSize: '11px', color: 'var(--text-dim)', fontWeight: 700 }}>
            HACKATHON TIMELINE:
          </span>

          <div style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
            {[
              { sec: 0, label: '0s (18)', title: 'LOW RISK (Baseline)' },
              { sec: 5, label: '5s (27)', title: 'MONITORING ACTIVE' },
              { sec: 10, label: '10s (43)', title: 'MEDIUM (Acoustic Drift)' },
              { sec: 14, label: '14s (61)', title: 'SUSPICIOUS (Comb Filter)' },
              { sec: 18, label: '18s (84)', title: 'HIGH RISK (Synthetic Detected!)' }
            ].map(stage => {
              const isActive = Math.abs(currentSec - stage.sec) <= 2;
              const isPast = currentSec >= stage.sec;
              const isAlert = stage.sec === 18;

              return (
                <button
                  key={stage.sec}
                  onClick={() => demoSimulator.jumpToSecond(stage.sec)}
                  style={{
                    padding: '3px 8px',
                    borderRadius: '6px',
                    background: isActive
                      ? isAlert ? '#ef4444' : 'var(--accent-blue)'
                      : isPast ? 'rgba(56, 189, 248, 0.15)' : 'rgba(255, 255, 255, 0.05)',
                    border: `1px solid ${isActive ? '#fff' : isAlert && isPast ? 'rgba(239, 68, 68, 0.5)' : 'var(--border-subtle)'}`,
                    color: isActive ? '#fff' : isAlert && isPast ? '#f87171' : isPast ? '#93c5fd' : 'var(--text-dim)',
                    fontSize: '11px',
                    fontFamily: 'var(--font-mono)',
                    fontWeight: 700,
                    cursor: 'pointer'
                  }}
                  title={stage.title}
                >
                  {stage.label}
                </button>
              );
            })}
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: '4px', marginLeft: '6px' }}>
            <button
              onClick={() => {
                if (isSimulating) {
                  demoSimulator.pause();
                } else {
                  demoSimulator.resume();
                }
              }}
              style={{
                background: 'rgba(255, 255, 255, 0.08)',
                border: '1px solid var(--border-subtle)',
                borderRadius: '6px',
                padding: '4px 8px',
                color: '#fff',
                fontSize: '11px',
                cursor: 'pointer',
                display: 'flex',
                alignItems: 'center',
                gap: '4px'
              }}
              title={isSimulating ? 'Pause simulation' : 'Play / Resume simulation'}
            >
              {isSimulating ? <Pause size={12} /> : <Play size={12} />}
            </button>

            <button
              onClick={resetDemoCall}
              style={{
                background: 'rgba(255, 255, 255, 0.08)',
                border: '1px solid var(--border-subtle)',
                borderRadius: '6px',
                padding: '4px 8px',
                color: '#fff',
                fontSize: '11px',
                cursor: 'pointer',
                display: 'flex',
                alignItems: 'center',
                gap: '4px'
              }}
              title="Reset simulation back to 00:00"
            >
              <RotateCcw size={12} />
            </button>
          </div>
        </div>
      )}

      {/* Right: Demo Mode Toggle & Status Indicator */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
        <button
          onClick={toggleDemoMode}
          style={{
            background: isDemoMode ? 'rgba(56, 189, 248, 0.12)' : 'rgba(255, 255, 255, 0.05)',
            border: `1px solid ${isDemoMode ? 'rgba(56, 189, 248, 0.4)' : 'var(--border-subtle)'}`,
            borderRadius: '6px',
            padding: '4px 10px',
            color: isDemoMode ? 'var(--accent-blue)' : 'var(--text-muted)',
            fontSize: '11px',
            fontWeight: 700,
            cursor: 'pointer',
            display: 'flex',
            alignItems: 'center',
            gap: '6px'
          }}
          title="Toggle between Simulated Hackathon Demo Mode and Live WebSocket mode"
        >
          {isDemoMode ? <ToggleRight size={16} /> : <ToggleLeft size={16} />}
          <span>Demo Mode: {isDemoMode ? 'ACTIVE (Simulated)' : 'OFF (Live WS)'}</span>
        </button>
      </div>
    </div>
  );
};
