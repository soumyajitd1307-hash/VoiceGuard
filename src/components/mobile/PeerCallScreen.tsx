import React, { useState, useEffect, useRef } from 'react';
import { PhoneOff, Mic, User, Hash, Signal } from 'lucide-react';
import { webrtcCall, PeerCallState } from '../../services/webrtcCall';
import { AudioCaptureService } from '../../services/audioCapture';
import { AudioStreamService } from '../../services/audioStream';
import { wsService } from '../../services/websocket';
import { useCallContext } from '../../context/CallContext';
import { createCall, terminateCall, terminateCallBeacon } from '../../services/backend4calls';

/**
 * Two-person browser call screen (WebRTC, no fakes).
 *
 * Backend 4 owns call identity (Prompt 4):
 *   Create mode: POST /api/v1/calls -> B4 call_id -> WebRTC room ->
 *                B1 audio session. ONE id end to end, never generated here.
 *   Join mode:   join the B4-created call id shared by the other person.
 * Displayed connection state always mirrors the real
 * RTCPeerConnection.connectionState via webrtcCall events — the UI
 * never marks a call "connected" from React state alone.
 */
interface PeerCallScreenProps {
  onLeave: () => void;
}

const STATE_META: Record<PeerCallState, { label: string; color: string }> = {
  idle: { label: 'Idle', color: 'var(--text-dim)' },
  joining: { label: 'Joining…', color: '#fbbf24' },
  'waiting-for-peer': { label: 'Waiting for peer…', color: '#fbbf24' },
  connecting: { label: 'Connecting…', color: '#38bdf8' },
  connected: { label: 'Connected', color: '#34d399' },
  disconnected: { label: 'Disconnected', color: '#f87171' },
  failed: { label: 'Failed', color: '#f87171' },
  closed: { label: 'Ended', color: 'var(--text-dim)' },
  error: { label: 'Error', color: '#f87171' },
};

export const PeerCallScreen: React.FC<PeerCallScreenProps> = ({ onLeave }) => {
  const { registerBackendCall, endCall } = useCallContext();
  const [mode, setMode] = useState<'create' | 'join'>('create');
  const [joinCallId, setJoinCallId] = useState('');
  const [displayName, setDisplayName] = useState('');
  // Authoritative B4 call id: created via POST /calls (create mode) or
  // typed from the other person's share (join mode). Never generated here.
  const [b4CallId, setB4CallId] = useState<string | null>(null);
  const b4CallIdRef = useRef<string | null>(null);
  const [phase, setPhase] = useState<'form' | 'in-call'>('form');
  const [pcState, setPcState] = useState<PeerCallState>('idle');
  const [peerName, setPeerName] = useState<string | null>(null);
  const [remoteStream, setRemoteStream] = useState<MediaStream | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [joining, setJoining] = useState(false);
  // Remote-analysis pipeline state (display only; updated ~every 10 s).
  const [fwdStatus, setFwdStatus] = useState<string | null>(null);
  const remoteAudioRef = useRef<HTMLAudioElement | null>(null);

  // Dedicated remote pipeline instances (separate from the local-mic
  // audioCapture/audioStream singletons): capture borrows the peer's
  // MediaStream, socket targets the REAL call room id. Refs (not state)
  // so event callbacks always see the live handles.
  const remoteCaptureRef = useRef<AudioCaptureService | null>(null);
  const remoteSocketRef = useRef<AudioStreamService | null>(null);
  const forwardingRef = useRef(false);
  // Mirrors for use inside async/event callbacks (avoid stale closures).
  const pcStateRef = useRef<PeerCallState>('idle');
  const remoteStreamRef = useRef<MediaStream | null>(null);

  const stopRemoteForwarding = (reason: string) => {
    if (
      !forwardingRef.current &&
      !remoteCaptureRef.current &&
      !remoteSocketRef.current
    ) {
      return;
    }
    forwardingRef.current = false;
    const capture = remoteCaptureRef.current;
    remoteCaptureRef.current = null;
    const socket = remoteSocketRef.current;
    remoteSocketRef.current = null;
    try {
      capture?.stop();
    } catch {
      // ignore teardown errors
    }
    if (socket) {
      const s = socket.getStats();
      if (import.meta.env.DEV) {
        // eslint-disable-next-line no-console
        console.info(
          `[peerCall] remote pipeline stopped (${reason}): ` +
            `frames=${s.framesSent} bytes=${s.bytesSent} ` +
            `acked=${s.ackCount} dropped=${s.droppedFrames}`,
        );
      }
      try {
        socket.disconnect();
      } catch {
        // ignore teardown errors
      }
    }
    setFwdStatus(null);
  };

  const startRemoteForwarding = async (
    stream: MediaStream,
    callId: string,
  ): Promise<void> => {
    const socket = new AudioStreamService();
    await socket.connect(callId); // throws: caller surfaces, nothing captured
    const capture = new AudioCaptureService();
    let frames = 0;
    try {
      await capture.startFromStream(stream, (chunk) => {
        socket.sendAudio(chunk);
        frames += 1;
        if (!import.meta.env.DEV) return;
        if (frames === 1) {
          // eslint-disable-next-line no-console
          console.info(`[peerCall] first remote frame: ${chunk.byteLength} bytes`);
        }
        if (frames % 40 === 0) {
          const s = socket.getStats();
          // eslint-disable-next-line no-console
          console.info(
            `[peerCall] remote fwd: frames=${s.framesSent} ` +
              `bytes=${s.bytesSent} acked=${s.ackCount} dropped=${s.droppedFrames}`,
          );
          setFwdStatus(
            `Forwarding remote audio → B1 · ${s.framesSent} frames · ` +
              `${s.bytesSent} B · ${s.ackCount} acks`,
          );
        }
      });
    } catch (err) {
      try {
        socket.disconnect();
      } catch {
        // ignore teardown errors
      }
      throw err;
    }
    remoteSocketRef.current = socket;
    remoteCaptureRef.current = capture;
    forwardingRef.current = true;
    const d = capture.getDiagnostics();
    if (import.meta.env.DEV) {
      // eslint-disable-next-line no-console
      console.info(
        `[peerCall] remote pipeline started: session=${callId} ` +
          `input ${d.inputSampleRate} Hz -> ${d.outputSampleRate} Hz mono Int16LE`,
      );
      // Development consistency check: ONE identity across B4, WebRTC, B1.
      // eslint-disable-next-line no-console
      console.info(
        `[peerCall] id check: b4=${b4CallIdRef.current} ` +
          `webrtc=${webrtcCall.getCallId()} ` +
          `b1=${socket.getStats().sessionId}`,
      );
    }
    setFwdStatus('Forwarding remote audio → B1 · starting…');
  };

  /**
   * Starts forwarding only when ALL hold: no pipeline yet, a real remote
   * stream exists, the peer connection is actually connected, and the
   * real call id is known. Never fabricates frames.
   */
  const maybeStartRemoteForwarding = (): void => {
    if (forwardingRef.current) return;
    const stream = remoteStreamRef.current;
    if (!stream) return;
    if (pcStateRef.current !== 'connected') return;
    const callId = webrtcCall.getCallId();
    if (!callId) return;
    void startRemoteForwarding(stream, callId).catch((err: unknown) => {
      stopRemoteForwarding('start failed');
      setError(
        err instanceof Error
          ? `Remote analysis unavailable: ${err.message}`
          : 'Remote analysis unavailable.',
      );
    });
  };

  // Never leak mic/peer connection if this screen unmounts mid-call.
  // Best-effort B4 termination (keepalive: also covers browser refresh).
  // Never creates anything: unmount only tears down.
  useEffect(() => {
    return () => {
      stopRemoteForwarding('unmount');
      const id = b4CallIdRef.current;
      b4CallIdRef.current = null;
      if (id) {
        terminateCallBeacon(id);
        // Drop the record; also closes a bound risk socket, if any.
        endCall(id);
      }
      if (webrtcCall.isActive()) {
        webrtcCall.leave();
      }
    };
  }, []);

  // Attach the REAL remote MediaStream to the audio element when it arrives.
  useEffect(() => {
    const el = remoteAudioRef.current;
    if (el) {
      el.srcObject = remoteStream;
    }
  }, [remoteStream]);

  /**
   * Deterministic start order: B4 creates the authoritative call id
   * FIRST, then WebRTC + B1 audio reuse that exact id. If B4 creation
   * fails, nothing else starts and no fallback fake call is created.
   */
  const handleJoin = async () => {
    const name = displayName.trim();
    const typedId = joinCallId.trim();
    if (!name || joining) return;
    if (mode === 'join' && !typedId) return;
    setError(null);
    setJoining(true);
    setPcState('joining');
    let authoritativeId: string | null = null;
    let createdHere = false;
    try {
      if (mode === 'create') {
        // B4 mints the ONE call id; register its real record so live
        // RiskUpdates have a call to land on (no fabricated state).
        const record = await createCall(name);
        authoritativeId = record.id;
        createdHere = true;
        registerBackendCall(record);
        if (import.meta.env.DEV) {
          // eslint-disable-next-line no-console
          console.info(`[peerCall] B4 call created: id=${authoritativeId}`);
        }
      } else {
        // Joining a real B4 call by its shared id: register a minimal
        // record (id only) so its RiskUpdates land; values stay empty
        // until the backend speaks.
        authoritativeId = typedId;
        registerBackendCall({
          id: typedId,
          callerName: null,
          receiver: null,
          startTime: null,
          status: null,
          monitoringState: null,
        });
      }
      b4CallIdRef.current = authoritativeId;
      setB4CallId(authoritativeId);

      await webrtcCall.joinCall(authoritativeId, name, {
        onState: (state, detail) => {
          pcStateRef.current = state;
          setPcState(state);
          if (state === 'error' || state === 'failed') {
            setError(detail || 'Peer connection failed.');
          }
          if (state === 'connected') {
            // Both preconditions may now hold (stream may already exist).
            maybeStartRemoteForwarding();
          }
          if (state === 'failed' || state === 'closed') {
            stopRemoteForwarding(`pc ${state}`);
          }
        },
        onPeerJoined: (name) => setPeerName(name),
        onPeerLeft: () => {
          stopRemoteForwarding('peer left');
          setPeerName(null);
          remoteStreamRef.current = null;
          setRemoteStream(null);
        },
        onRemoteStream: (stream) => {
          remoteStreamRef.current = stream;
          setRemoteStream(stream);
          if (stream) {
            if (import.meta.env.DEV) {
              // eslint-disable-next-line no-console
              console.info(
                `[peerCall] remote stream received: ` +
                  `${stream.getAudioTracks().length} audio track(s)`,
              );
            }
            const [track] = stream.getAudioTracks();
            if (track) {
              track.onended = () => {
                stopRemoteForwarding('remote track ended');
                remoteStreamRef.current = null;
                setRemoteStream(null);
              };
            }
            // pc may already be connected (ontrack can precede the event).
            maybeStartRemoteForwarding();
          } else {
            stopRemoteForwarding('remote stream removed');
          }
        },
      });
      // WebRTC is up: open the B4 risk stream for THIS call id. A risk
      // socket failure never fails the call itself (status surfaces in UI).
      wsService.connect(authoritativeId);
      setPhase('in-call');
    } catch (err) {
      // WebRTC failed AFTER we created the B4 call: terminate it so no
      // zombie active call remains. Join-mode failures created nothing.
      if (createdHere && authoritativeId) {
        try {
          await terminateCall(authoritativeId);
        } catch {
          // best effort: the id is dropped either way
        }
        b4CallIdRef.current = null;
        setB4CallId(null);
      }
      setError(err instanceof Error ? err.message : 'Could not join the call.');
      setPcState('error');
    } finally {
      setJoining(false);
    }
  };

  const handleLeave = async () => {
    const id = b4CallIdRef.current;
    b4CallIdRef.current = null;
    stopRemoteForwarding('leave');
    webrtcCall.leave();
    if (id) {
      // Shared call ends for both peers; second terminate is idempotent.
      try {
        await terminateCall(id);
      } catch (err) {
        if (import.meta.env.DEV) {
          // eslint-disable-next-line no-console
          console.warn('[peerCall] B4 terminate failed (call may linger):', err);
        }
      }
      // Remove the record from live state (also closes its risk socket).
      endCall(id);
    }
    pcStateRef.current = 'closed';
    remoteStreamRef.current = null;
    setB4CallId(null);
    setPhase('form');
    setPcState('closed');
    setPeerName(null);
    setRemoteStream(null);
    onLeave();
  };

  const meta = STATE_META[pcState];

  return (
    <div
      style={{
        flex: 1,
        display: 'flex',
        flexDirection: 'column',
        padding: '20px 16px',
        overflowY: 'auto',
        gap: '16px',
      }}
    >
      <div style={{ textAlign: 'center', paddingTop: '8px' }}>
        <h2 style={{ fontSize: '18px', fontWeight: 800, color: 'var(--text-main)' }}>
          Person-to-Person Call
        </h2>
        <p style={{ fontSize: '12px', color: 'var(--text-muted)', marginTop: '4px' }}>
          Direct browser WebRTC audio — no backend media path
        </p>
      </div>

      {error && (
        <div
          style={{
            background: 'rgba(239, 68, 68, 0.12)',
            border: '1px solid rgba(239, 68, 68, 0.4)',
            borderRadius: '12px',
            padding: '10px 12px',
            fontSize: '11px',
            color: '#f87171',
            wordBreak: 'break-word',
          }}
        >
          {error}
        </div>
      )}

      {phase === 'form' ? (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
          {/* Create: Backend 4 mints the call id. Join: use the shared id. */}
          <div style={{ display: 'flex', background: 'var(--bg-secondary)', padding: '3px', borderRadius: '10px', border: '1px solid var(--border-subtle)' }}>
            {(['create', 'join'] as const).map((m) => (
              <button
                key={m}
                onClick={() => setMode(m)}
                style={{
                  flex: 1,
                  background: mode === m ? 'var(--accent-blue)' : 'transparent',
                  color: mode === m ? '#fff' : 'var(--text-muted)',
                  border: 'none',
                  borderRadius: '8px',
                  padding: '8px',
                  fontSize: '12px',
                  fontWeight: 800,
                  cursor: 'pointer',
                }}
              >
                {m === 'create' ? 'Create new call' : 'Join with ID'}
              </button>
            ))}
          </div>

          {mode === 'join' && (
            <label style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
              <span style={{ fontSize: '11px', fontWeight: 800, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.06em', display: 'flex', alignItems: 'center', gap: '6px' }}>
                <Hash size={12} /> Call ID (shared by the other person)
              </span>
              <input
                value={joinCallId}
                onChange={(e) => setJoinCallId(e.target.value)}
                placeholder="e.g. a91f3c2d4e07"
                autoComplete="off"
                style={{
                  background: 'var(--bg-card)',
                  border: '1px solid var(--border-subtle)',
                  borderRadius: '10px',
                  padding: '12px 14px',
                  color: '#fff',
                  fontSize: '14px',
                  outline: 'none',
                }}
              />
            </label>
          )}

          <label style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
            <span style={{ fontSize: '11px', fontWeight: 800, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.06em', display: 'flex', alignItems: 'center', gap: '6px' }}>
              <User size={12} /> Your display name
            </span>
            <input
              value={displayName}
              onChange={(e) => setDisplayName(e.target.value)}
              placeholder="e.g. Person A"
              autoComplete="off"
              style={{
                background: 'var(--bg-card)',
                border: '1px solid var(--border-subtle)',
                borderRadius: '10px',
                padding: '12px 14px',
                color: '#fff',
                fontSize: '14px',
                outline: 'none',
              }}
            />
          </label>

          <button
            onClick={() => void handleJoin()}
            disabled={joining || !displayName.trim() || (mode === 'join' && !joinCallId.trim())}
            style={{
              background: 'linear-gradient(135deg, #0284c7 0%, #0369a1 100%)',
              border: 'none',
              borderRadius: '14px',
              padding: '14px',
              color: '#fff',
              fontSize: '15px',
              fontWeight: 800,
              cursor: joining ? 'wait' : 'pointer',
              opacity: joining || !displayName.trim() || (mode === 'join' && !joinCallId.trim()) ? 0.6 : 1,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              gap: '8px',
            }}
          >
            <Mic size={16} />
            {joining ? 'Joining…' : mode === 'create' ? 'Create call & join with microphone' : 'Join call with microphone'}
          </button>
        </div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '14px' }}>
          <div
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: '8px',
              padding: '6px 14px',
              borderRadius: '20px',
              background: 'rgba(255, 255, 255, 0.06)',
              border: '1px solid var(--border-subtle)',
            }}
          >
            <span
              style={{
                width: '8px',
                height: '8px',
                borderRadius: '50%',
                backgroundColor: meta.color,
                boxShadow: `0 0 8px ${meta.color}`,
              }}
            />
            <span style={{ fontSize: '11px', fontWeight: 800, letterSpacing: '0.08em', textTransform: 'uppercase', color: meta.color }}>
              {meta.label}
            </span>
          </div>

          <div style={{ textAlign: 'center' }}>
            <div style={{ fontSize: '16px', fontWeight: 800, color: 'var(--text-main)' }}>
              {peerName ? `Talking with ${peerName}` : 'No peer yet'}
            </div>
            <div className="font-mono" style={{ fontSize: '11px', color: 'var(--text-dim)', marginTop: '4px' }}>
              Call ID: {b4CallId ?? '—'}
            </div>
            {pcState === 'waiting-for-peer' && (
              <div style={{ fontSize: '12px', color: 'var(--text-muted)', marginTop: '8px' }}>
                Share this Call ID with the other person so they can join.
              </div>
            )}
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '11px', color: 'var(--text-dim)' }}>
            <Signal size={12} />
            <span>
              {remoteStream ? 'Receiving remote audio' : 'No remote audio yet'}
            </span>
          </div>

          {/* Remote-analysis pipeline state (real forwarding status). */}
          <div className="font-mono" style={{ fontSize: '11px', color: fwdStatus ? '#34d399' : 'var(--text-dim)', textAlign: 'center' }}>
            {fwdStatus ?? 'Remote analysis: idle (no peer audio forwarded)'}
          </div>

          {/* Hidden element that actually plays the remote peer's MediaStream. */}
          <audio ref={remoteAudioRef} autoPlay playsInline style={{ display: 'none' }} />

          <button
            onClick={() => void handleLeave()}
            style={{
              width: '60px',
              height: '60px',
              borderRadius: '50%',
              background: '#dc2626',
              border: 'none',
              color: '#ffffff',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              cursor: 'pointer',
              boxShadow: '0 0 20px rgba(220, 38, 38, 0.6)',
              marginTop: '8px',
            }}
            title="Leave call"
          >
            <PhoneOff size={24} />
          </button>
        </div>
      )}
    </div>
  );
};
