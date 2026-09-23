import React, { useState, useEffect } from 'react';
import { Wifi, BatteryMedium, Signal, Shield, Home, Clock, Phone } from 'lucide-react';
import { useCallContext } from '../../context/CallContext';
import { Call, Evidence } from '../../types';
import { SplashScreen } from './SplashScreen';
import { HomeScreen } from './HomeScreen';
import { ActiveCallScreen } from './ActiveCallScreen';
import { CallEndScreen } from './CallEndScreen';
import { CallHistoryScreen } from './CallHistoryScreen';
import { CallDetailsScreen } from './CallDetailsScreen';
import { EvidenceScreen } from './EvidenceScreen';

export type MobileScreen = 
  | 'splash'
  | 'home'
  | 'active_call'
  | 'call_end'
  | 'history'
  | 'call_details'
  | 'evidence';

interface MobileAppProps {
  embeddedInShell?: boolean;
}

export const MobileApp: React.FC<MobileAppProps> = ({ embeddedInShell = true }) => {
  const {
    activeCalls,
    selectedCall,
    callHistory,
    startCall,
    endCall
  } = useCallContext();

  const [currentScreen, setCurrentScreen] = useState<MobileScreen>('home');
  const [inspectedCall, setInspectedCall] = useState<Call | null>(null);
  const [inspectedEvidence, setInspectedEvidence] = useState<Evidence | null>(null);

  // Default to active call if one exists and user clicked start
  const activeCall = selectedCall || activeCalls[0];

  // Auto transition to active call if an active call exists and screen is home
  useEffect(() => {
    if (activeCall && activeCall.status === 'ACTIVE' && currentScreen === 'splash') {
      setCurrentScreen('home');
    }
  }, [activeCall, currentScreen]);

  const handleStartCall = () => {
    startCall('Rahul');
    setCurrentScreen('active_call');
  };

  const handleEndCall = () => {
    endCall(activeCall?.id);
    setCurrentScreen('call_end');
  };

  const handleOpenDetails = (call: Call) => {
    setInspectedCall(call);
    setCurrentScreen('call_details');
  };

  const handleOpenEvidence = (evidence: Evidence) => {
    setInspectedEvidence(evidence);
    setCurrentScreen('evidence');
  };

  const showBottomNav = currentScreen !== 'splash' && currentScreen !== 'active_call';

  return (
    <div className={embeddedInShell ? 'mobile-device-wrapper' : 'w-full h-full'}>
      <div className={embeddedInShell ? 'mobile-device-screen' : 'w-full h-full flex flex-col'}>
        {/* Dynamic Island / Notch */}
        {embeddedInShell && (
          <div className="mobile-notch">
            <div className="mobile-notch-camera" />
          </div>
        )}

        {/* Android Status Bar */}
        <div
          style={{
            height: '38px',
            padding: '8px 20px 0',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            fontSize: '12px',
            fontWeight: 700,
            color: '#cbd5e1',
            zIndex: 10
          }}
        >
          <span>09:41</span>
          <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
            <Signal size={13} />
            <Wifi size={13} />
            <span style={{ fontSize: '11px', fontWeight: 800 }}>5G</span>
            <BatteryMedium size={15} />
          </div>
        </div>

        {/* Screen Routing Content */}
        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
          {currentScreen === 'splash' && (
            <SplashScreen onContinue={() => setCurrentScreen('home')} />
          )}

          {currentScreen === 'home' && (
            <HomeScreen
              onStartCall={handleStartCall}
              onOpenCallHistory={() => setCurrentScreen('history')}
              onOpenCallDetails={handleOpenDetails}
              recentCalls={[...activeCalls, ...callHistory]}
            />
          )}

          {currentScreen === 'active_call' && (
            <ActiveCallScreen
              call={activeCall || activeCalls[0]}
              onEndCall={handleEndCall}
              onOpenEvidence={() => {
                if (activeCall?.evidence) {
                  handleOpenEvidence(activeCall.evidence);
                }
              }}
            />
          )}

          {currentScreen === 'call_end' && (
            <CallEndScreen
              call={activeCall || activeCalls[0]}
              onGoHome={() => setCurrentScreen('home')}
              onViewReport={() => handleOpenDetails(activeCall || activeCalls[0])}
              onPlayEvidence={() => {
                if (activeCall?.evidence) {
                  handleOpenEvidence(activeCall.evidence);
                }
              }}
            />
          )}

          {currentScreen === 'history' && (
            <CallHistoryScreen
              calls={[...activeCalls, ...callHistory]}
              onBack={() => setCurrentScreen('home')}
              onSelectCall={handleOpenDetails}
            />
          )}

          {currentScreen === 'call_details' && (
            <CallDetailsScreen
              call={inspectedCall || activeCall || activeCalls[0]}
              onBack={() => setCurrentScreen('home')}
              onOpenEvidence={handleOpenEvidence}
            />
          )}

          {currentScreen === 'evidence' && (
            <EvidenceScreen
              evidence={inspectedEvidence || activeCall?.evidence || activeCalls[0].evidence!}
              onBack={() => setCurrentScreen('active_call')}
            />
          )}
        </div>

        {/* Bottom Mobile Navigation Bar */}
        {showBottomNav && (
          <div
            style={{
              height: '56px',
              borderTop: '1px solid var(--border-subtle)',
              background: '#070a12',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-around',
              padding: '0 10px',
              zIndex: 10
            }}
          >
            <button
              onClick={() => setCurrentScreen('home')}
              style={{
                background: 'transparent',
                border: 'none',
                color: currentScreen === 'home' ? 'var(--accent-blue)' : 'var(--text-dim)',
                display: 'flex',
                flexDirection: 'column',
                alignItems: 'center',
                gap: '3px',
                cursor: 'pointer',
                fontSize: '10px',
                fontWeight: 700
              }}
            >
              <Home size={18} />
              Home
            </button>

            <button
              onClick={() => {
                if (activeCall && activeCall.status === 'ACTIVE') {
                  setCurrentScreen('active_call');
                } else {
                  handleStartCall();
                }
              }}
              style={{
                background: 'transparent',
                border: 'none',
                color: 'var(--text-dim)',
                display: 'flex',
                flexDirection: 'column',
                alignItems: 'center',
                gap: '3px',
                cursor: 'pointer',
                fontSize: '10px',
                fontWeight: 700
              }}
            >
              <Phone size={18} />
              Active Call
            </button>

            <button
              onClick={() => setCurrentScreen('history')}
              style={{
                background: 'transparent',
                border: 'none',
                color: currentScreen === 'history' ? 'var(--accent-blue)' : 'var(--text-dim)',
                display: 'flex',
                flexDirection: 'column',
                alignItems: 'center',
                gap: '3px',
                cursor: 'pointer',
                fontSize: '10px',
                fontWeight: 700
              }}
            >
              <Clock size={18} />
              History
            </button>

            <button
              onClick={() => setCurrentScreen('splash')}
              style={{
                background: 'transparent',
                border: 'none',
                color: 'var(--text-dim)',
                display: 'flex',
                flexDirection: 'column',
                alignItems: 'center',
                gap: '3px',
                cursor: 'pointer',
                fontSize: '10px',
                fontWeight: 700
              }}
            >
              <Shield size={18} />
              About
            </button>
          </div>
        )}

        {/* Android Gesture Bar */}
        {embeddedInShell && (
          <div
            style={{
              height: '14px',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              background: '#070a12'
            }}
          >
            <div
              style={{
                width: '110px',
                height: '4px',
                borderRadius: '2px',
                backgroundColor: 'rgba(255, 255, 255, 0.25)'
              }}
            />
          </div>
        )}
      </div>
    </div>
  );
};
