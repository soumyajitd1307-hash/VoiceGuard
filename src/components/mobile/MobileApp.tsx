import React, { useState, useEffect, useRef } from 'react';
import { Wifi, BatteryMedium, Signal, Shield, Home, Clock, Phone } from 'lucide-react';
import { useCallContext } from '../../context/CallContext';
import { audioCapture } from '../../services/audioCapture';
import { audioStream } from '../../services/audioStream';
import { Call, Evidence } from '../../types';
import { SplashScreen } from './SplashScreen';
import { HomeScreen } from './HomeScreen';
import { ActiveCallScreen, LiveAudioState } from './ActiveCallScreen';
import { PeerCallScreen } from './PeerCallScreen';
import { CallEndScreen } from './CallEndScreen';
import { CallHistoryScreen } from './CallHistoryScreen';
import { CallDetailsScreen } from './CallDetailsScreen';
import { EvidenceScreen } from './EvidenceScreen';

export type MobileScreen =
  | 'splash'
  | 'home'
  | 'active_call'
  | 'peer_call'
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
  // Backend 1 live-audio failure surfaced inline (no fake "mic active" state).
  const [audioError, setAudioError] = useState<string | null>(null);
  const [isStartingCall, setIsStartingCall] = useState<boolean>(false);
  // Real audio transport state for the Active Call indicator. Updated only
  // from actual audioCapture/audioStream lifecycle events — never simulated.
  const [liveAudioState, setLiveAudioState] = useState<LiveAudioState>('disconnected');
  // The actual mobile session: targeted by End and retained through the
  // call-end screen, so a mid-call dashboard selection or a currentCallId
  // rebinding can never substitute a different (e.g. mock #1042) call.
  const [sessionCallId, setSessionCallId] = useState<string | null>(null);
  const [endedCall, setEndedCall] = useState<Call | null>(null);

  // Default to active call if one exists and user clicked start
  const activeCall = selectedCall || activeCalls[0];

  // Auto transition to active call if an active call exists and screen is home
  useEffect(() => {
    if (activeCall && activeCall.status === 'ACTIVE' && currentScreen === 'splash') {
      setCurrentScreen('home');
    }
  }, [activeCall, currentScreen]);

  // Never leak mic/Backend 1 socket if the mobile UI unmounts mid-call
  // (e.g. presentation-mode switch). Both calls are idempotent.
  useEffect(() => {
    return () => {
      audioCapture.stop();
      audioStream.disconnect();
    };
  }, []);

  // If the session was torn down externally (e.g. the SOC dashboard ended
  // this call via CallContext.endCall), re-check the REAL service state on
  // the next context update so the indicator never claims "active" without
  // a running capture + open socket.
  useEffect(() => {
    if (
      liveAudioState === 'active' &&
      !(audioCapture.isRunning() && audioStream.isConnected())
    ) {
      setLiveAudioState('disconnected');
    }
  }, [liveAudioState, activeCalls]);

  // Synchronous guard: a ref (not state) so two same-tick invocations cannot
  // both slip through before React commits isStartingCall.
  const startingRef = useRef(false);

  const handleStartCall = async () => {
    if (startingRef.current || isStartingCall) return;
    startingRef.current = true;
    setAudioError(null);
    setIsStartingCall(true);
    setLiveAudioState('connecting');

    // The call record is created first so the Backend 1 audio session uses
    // the ACTUAL generated call ID — never a hardcoded or fallback ID.
    // No caller name is passed: without a contacts backend there is no
    // verified caller, so the session starts as 'Unknown caller'.
    const callId = startCall();
    setSessionCallId(callId);
    setEndedCall(null);

    try {
      await audioStream.connect(callId);
      await audioCapture.start((chunk) => {
        audioStream.sendAudio(chunk);
        // Real mid-call transport check, driven by actual PCM frames
        // (one per 250 ms). If the Backend 1 socket dropped, surface it
        // immediately — no timers, no simulated status.
        if (!audioStream.isConnected()) {
          setLiveAudioState('disconnected');
        }
      });
      // Capture running AND socket open: only now is the mic genuinely active.
      setLiveAudioState('active');
      // Navigate only after the live-audio path is genuinely up.
      setCurrentScreen('active_call');
    } catch (err) {
      // No orphaned mic/WebSocket, no fake success: roll back the partial
      // session AND the call record, stay on home, show the real error.
      audioCapture.stop();
      audioStream.disconnect();
      endCall(callId);
      setLiveAudioState('disconnected');
      const message =
        err instanceof Error ? err.message : 'Live audio unavailable. Is Backend 1 running on :8001?';
      // eslint-disable-next-line no-console
      console.error(`[MobileApp] live audio failed for call ${callId}:`, message);
      setAudioError(message);
      setSessionCallId(null);
    } finally {
      startingRef.current = false;
      setIsStartingCall(false);
    }
  };

  const handleEndCall = () => {
    // End the ACTUAL mobile session, not whatever happens to be selected.
    const targetId = sessionCallId ?? activeCall?.id;
    if (!targetId) {
      // Nothing live to end (e.g. already terminated elsewhere).
      setCurrentScreen('home');
      return;
    }
    const targetCall =
      activeCalls.find((c) => c.id === targetId) ?? activeCall ?? null;
    // Order: capture first, then socket, then existing call teardown.
    audioCapture.stop();
    audioStream.disconnect();
    endCall(targetId);
    setEndedCall(targetCall);
    setSessionCallId(null);
    setLiveAudioState('disconnected');
    setCurrentScreen(targetCall ? 'call_end' : 'home');
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

  // Shared home element: used as the honest fallback whenever a screen
  // requires a call/evidence object that does not exist (empty live state).
  const homeScreenElement = (
    <HomeScreen
      onStartCall={handleStartCall}
      startDisabled={isStartingCall}
      onJoinPeerCall={() => setCurrentScreen('peer_call')}
      onOpenCallHistory={() => setCurrentScreen('history')}
      onOpenCallDetails={handleOpenDetails}
      recentCalls={[...activeCalls, ...callHistory]}
    />
  );

  // Resolved snapshots for screens that require a call object. Each may be
  // undefined in the empty live state — branches below fall back to home.
  const activeCallForScreen = activeCall || activeCalls[0];
  const endedCallForScreen = endedCall || activeCall || activeCalls[0];
  const inspectedCallForScreen = inspectedCall || activeCall || activeCalls[0];
  const evidenceForScreen =
    inspectedEvidence || activeCall?.evidence || activeCalls[0]?.evidence;

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
          {audioError && currentScreen === 'home' && (
            <div
              style={{
                margin: '10px 16px 0',
                background: 'rgba(239, 68, 68, 0.12)',
                border: '1px solid rgba(239, 68, 68, 0.4)',
                borderRadius: '12px',
                padding: '10px 12px',
                display: 'flex',
                flexDirection: 'column',
                gap: '6px'
              }}
            >
              <span style={{ fontSize: '11px', fontWeight: 800, color: '#f87171', textTransform: 'uppercase', letterSpacing: '0.06em' }}>
                Live audio unavailable — call not started
              </span>
              <span className="font-mono" style={{ fontSize: '11px', color: 'var(--text-muted)', wordBreak: 'break-word' }}>
                {audioError}
              </span>
              <div style={{ display: 'flex', gap: '8px' }}>
                <button
                  onClick={() => void handleStartCall()}
                  disabled={isStartingCall}
                  style={{
                    background: 'rgba(255, 255, 255, 0.08)',
                    border: '1px solid var(--border-medium)',
                    borderRadius: '8px',
                    padding: '6px 12px',
                    color: '#fff',
                    fontSize: '11px',
                    fontWeight: 700,
                    cursor: isStartingCall ? 'wait' : 'pointer',
                    opacity: isStartingCall ? 0.6 : 1
                  }}
                >
                  {isStartingCall ? 'Starting…' : 'Retry'}
                </button>
                <button
                  onClick={() => setAudioError(null)}
                  style={{
                    background: 'transparent',
                    border: 'none',
                    color: 'var(--text-dim)',
                    fontSize: '11px',
                    fontWeight: 700,
                    cursor: 'pointer',
                    padding: '6px 8px'
                  }}
                >
                  Dismiss
                </button>
              </div>
            </div>
          )}

          {currentScreen === 'splash' && (
            <SplashScreen onContinue={() => setCurrentScreen('home')} />
          )}

          {currentScreen === 'home' && homeScreenElement}

          {currentScreen === 'peer_call' && (
            <PeerCallScreen onLeave={() => setCurrentScreen('home')} />
          )}

          {currentScreen === 'active_call' &&
            (activeCallForScreen ? (
              <ActiveCallScreen
                call={activeCallForScreen}
                onEndCall={handleEndCall}
                audioState={liveAudioState}
                onOpenEvidence={() => {
                  if (activeCall?.evidence) {
                    handleOpenEvidence(activeCall.evidence);
                  }
                }}
              />
            ) : (
              homeScreenElement
            ))}

          {currentScreen === 'call_end' &&
            (endedCallForScreen ? (
              <CallEndScreen
                call={endedCallForScreen}
                onGoHome={() => setCurrentScreen('home')}
                onViewReport={() => {
                  const target = endedCall || activeCall || activeCalls[0];
                  if (target) {
                    handleOpenDetails(target);
                  } else {
                    setCurrentScreen('home');
                  }
                }}
                onPlayEvidence={() => {
                  const ended = endedCall || activeCall;
                  if (ended?.evidence) {
                    handleOpenEvidence(ended.evidence);
                  }
                }}
              />
            ) : (
              homeScreenElement
            ))}

          {currentScreen === 'history' && (
            <CallHistoryScreen
              calls={[...activeCalls, ...callHistory]}
              onBack={() => setCurrentScreen('home')}
              onSelectCall={handleOpenDetails}
            />
          )}

          {currentScreen === 'call_details' &&
            (inspectedCallForScreen ? (
              <CallDetailsScreen
                call={inspectedCallForScreen}
                onBack={() => setCurrentScreen('home')}
                onOpenEvidence={handleOpenEvidence}
              />
            ) : (
              homeScreenElement
            ))}

          {currentScreen === 'evidence' &&
            (evidenceForScreen ? (
              <EvidenceScreen
                evidence={evidenceForScreen}
                onBack={() => setCurrentScreen('active_call')}
              />
            ) : (
              homeScreenElement
            ))}
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
                  void handleStartCall();
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
