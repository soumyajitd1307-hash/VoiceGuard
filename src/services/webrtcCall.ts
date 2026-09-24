/**
 * Two-person browser call manager (WebRTC, no fakes).
 *
 * Owns exactly one RTCPeerConnection for one call room:
 *   getUserMedia (mic) -> addTrack -> SDP offer/answer + ICE via
 *   webrtcSignaling -> remote MediaStream via ontrack.
 *
 * "Connected" here always mirrors RTCPeerConnection.connectionState —
 * nothing is ever marked connected from React state alone.
 *
 * Glare-free negotiation rule: of any pair, the lexicographically
 * smaller participant_id creates the offer; the other side waits.
 * Both sides compute the same comparison, so exactly one offer exists.
 *
 * The remote stream is exposed via getRemoteStream() so VoiceGuard's
 * audio-processing pipeline can consume it later (out of scope here).
 */

import { webrtcSignaling } from './webrtcSignaling';

export type PeerCallState =
  | 'idle'
  | 'joining'
  | 'waiting-for-peer'
  | 'connecting'
  | 'connected'
  | 'disconnected'
  | 'failed'
  | 'closed'
  | 'error';

export interface PeerCallEvents {
  onState?: (state: PeerCallState, detail?: string) => void;
  onPeerJoined?: (displayName: string) => void;
  onPeerLeft?: () => void;
  onRemoteStream?: (stream: MediaStream | null) => void;
}

/** Development STUN only. No TURN — symmetric-NAT pairs will not connect. */
const ICE_SERVERS: RTCIceServer[] = [
  { urls: 'stun:stun.l.google.com:19302' },
];

function newParticipantId(): string {
  if (typeof crypto !== 'undefined' && 'randomUUID' in crypto) {
    return crypto.randomUUID();
  }
  return `p-${Date.now().toString(36)}-${Math.floor(Math.random() * 1e9).toString(36)}`;
}

class WebRTCCallManager {
  private pc: RTCPeerConnection | null = null;
  private localStream: MediaStream | null = null;
  private remoteStream: MediaStream | null = null;
  private pendingIce: RTCIceCandidateInit[] = [];
  /**
   * Outbound ICE gathered before the peer id is known. Without buffering,
   * early candidates are silently dropped and the call may never connect.
   * Bounded in practice (a handful per gathering cycle) and cleared on
   * teardown/leave alongside everything else.
   */
  private pendingIceSend: RTCIceCandidateInit[] = [];
  private events: PeerCallEvents = {};
  private callId = '';
  private participantId = '';
  private displayName = '';
  private peerId: string | null = null;
  private started = false;

  public getCallId(): string {
    return this.callId;
  }

  public getParticipantId(): string {
    return this.participantId;
  }

  /** Remote participant id once known (signaling), else null. */
  public getPeerId(): string | null {
    return this.peerId;
  }

  /** Remote peer audio for later pipeline use. Null until ontrack fires. */
  public getRemoteStream(): MediaStream | null {
    return this.remoteStream;
  }

  public getLocalStream(): MediaStream | null {
    return this.localStream;
  }

  public isActive(): boolean {
    return this.started;
  }

  private emit(state: PeerCallState, detail?: string): void {
    if (import.meta.env.DEV) {
      // eslint-disable-next-line no-console
      console.info(`[webrtcCall] state=${state}${detail ? ` (${detail})` : ''}`);
    }
    this.events.onState?.(state, detail);
  }

  public async joinCall(
    callId: string,
    displayName: string,
    events: PeerCallEvents,
  ): Promise<void> {
    if (this.started) {
      throw new Error('webrtcCall: already in a call — leave first');
    }
    if (!callId.trim() || !displayName.trim()) {
      throw new Error('webrtcCall: callId and displayName are required');
    }
    if (
      typeof navigator === 'undefined' ||
      !navigator.mediaDevices?.getUserMedia
    ) {
      throw new Error('webrtcCall: microphone API unavailable in this browser');
    }
    if (typeof RTCPeerConnection === 'undefined') {
      throw new Error('webrtcCall: WebRTC unavailable in this browser');
    }

    this.events = events;
    this.callId = callId.trim();
    this.displayName = displayName.trim();
    this.participantId = newParticipantId();
    this.emit('joining');

    let stream: MediaStream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        },
      });
    } catch (err) {
      const name = err instanceof DOMException ? err.name : 'UnknownError';
      throw new Error(
        `webrtcCall: microphone unavailable (${name}). Grant mic access and retry.`,
      );
    }

    const pc = new RTCPeerConnection({ iceServers: ICE_SERVERS });
    this.pc = pc;
    this.localStream = stream;
    stream.getAudioTracks().forEach((track) => pc.addTrack(track, stream));

    pc.onicecandidate = (event) => {
      if (!event.candidate) return;
      if (this.peerId) {
        webrtcSignaling.sendIce(this.peerId, event.candidate.toJSON());
      } else {
        // Peer unknown yet (roster/peer-joined still in flight): buffer
        // and flush once handleJoined/handlePeerJoined sets the id.
        this.pendingIceSend.push(event.candidate.toJSON());
      }
    };

    pc.ontrack = (event) => {
      const [incoming] = event.streams;
      if (incoming) {
        this.remoteStream = incoming;
        this.events.onRemoteStream?.(incoming);
      }
    };

    pc.onconnectionstatechange = () => {
      const s = pc.connectionState;
      if (s === 'connected') this.emit('connected');
      else if (s === 'connecting') this.emit('connecting');
      else if (s === 'disconnected') this.emit('disconnected');
      else if (s === 'failed') this.emit('failed', 'ICE/DTLS failure (NAT? no TURN)');
      else if (s === 'closed') this.emit('closed');
    };

    try {
      await webrtcSignaling.connect(
        this.callId,
        this.participantId,
        this.displayName,
        {
          onJoined: (peers) => void this.handleJoined(peers.map((p) => p.participant_id)),
          onPeerJoined: (peer) => void this.handlePeerJoined(peer.participant_id, peer.display_name),
          onPeerLeft: (id) => this.handlePeerLeft(id),
          onOffer: (from, sdp) => void this.handleOffer(from, sdp),
          onAnswer: (from, sdp) => void this.handleAnswer(from, sdp),
          onIce: (from, candidate) => void this.handleIce(candidate),
          onErrorMessage: (detail) => this.emit('error', detail),
          onClose: () => {
            if (this.started) this.emit('disconnected', 'signaling closed');
          },
        },
      );
    } catch (err) {
      this.teardown();
      throw err instanceof Error ? err : new Error('webrtcCall: signaling failed');
    }

    this.started = true;
    this.emit('waiting-for-peer');
  }

  /** Smaller id offers — deterministic, so two joiners never double-offer. */
  private amOfferer(remoteId: string): boolean {
    return this.participantId < remoteId;
  }

  private flushPendingIceSend(): void {
    if (!this.peerId || this.pendingIceSend.length === 0) return;
    const queued = this.pendingIceSend;
    this.pendingIceSend = [];
    for (const candidate of queued) {
      webrtcSignaling.sendIce(this.peerId, candidate);
    }
  }

  private async handleJoined(existingPeerIds: string[]): Promise<void> {
    for (const id of existingPeerIds) {
      this.peerId = this.peerId ?? id;
      this.flushPendingIceSend();
      if (this.amOfferer(id)) {
        await this.createAndSendOffer(id);
      }
    }
  }

  private async handlePeerJoined(id: string, displayName: string): Promise<void> {
    this.peerId = this.peerId ?? id;
    this.flushPendingIceSend();
    this.events.onPeerJoined?.(displayName || id);
    if (this.amOfferer(id)) {
      await this.createAndSendOffer(id);
    }
  }

  private handlePeerLeft(id: string): void {
    if (id !== this.peerId) return;
    this.peerId = null;
    this.remoteStream = null;
    this.events.onRemoteStream?.(null);
    this.events.onPeerLeft?.();
    this.emit('waiting-for-peer', 'peer left');
  }

  private async createAndSendOffer(to: string): Promise<void> {
    const pc = this.pc;
    if (!pc || pc.signalingState !== 'stable') return;
    try {
      const offer = await pc.createOffer();
      await pc.setLocalDescription(offer);
      if (pc.localDescription) {
        webrtcSignaling.sendOffer(to, pc.localDescription.toJSON());
      }
    } catch (err) {
      this.emit('error', err instanceof Error ? err.message : 'offer failed');
    }
  }

  private async handleOffer(from: string, sdp: RTCSessionDescriptionInit): Promise<void> {
    const pc = this.pc;
    if (!pc) return;
    this.peerId = this.peerId ?? from;
    if (pc.signalingState !== 'stable') return; // glare guard: offerer role is fixed
    try {
      await pc.setRemoteDescription(new RTCSessionDescription(sdp));
      await this.drainPendingIce();
      const answer = await pc.createAnswer();
      await pc.setLocalDescription(answer);
      if (pc.localDescription) {
        webrtcSignaling.sendAnswer(from, pc.localDescription.toJSON());
      }
    } catch (err) {
      this.emit('error', err instanceof Error ? err.message : 'answer failed');
    }
  }

  private async handleAnswer(from: string, sdp: RTCSessionDescriptionInit): Promise<void> {
    const pc = this.pc;
    if (!pc) return;
    if (pc.signalingState !== 'have-local-offer') return; // stray answer: ignore
    try {
      await pc.setRemoteDescription(new RTCSessionDescription(sdp));
      await this.drainPendingIce();
    } catch (err) {
      this.emit('error', err instanceof Error ? err.message : 'invalid answer');
    }
  }

  private async handleIce(candidate: RTCIceCandidateInit): Promise<void> {
    const pc = this.pc;
    if (!pc) return;
    if (!pc.remoteDescription) {
      this.pendingIce.push(candidate); // remote not set yet: queue
      return;
    }
    try {
      await pc.addIceCandidate(new RTCIceCandidate(candidate));
    } catch (err) {
      if (import.meta.env.DEV) {
        // eslint-disable-next-line no-console
        console.warn('[webrtcCall] addIceCandidate failed', err);
      }
    }
  }

  private async drainPendingIce(): Promise<void> {
    const pc = this.pc;
    if (!pc) return;
    const queued = this.pendingIce;
    this.pendingIce = [];
    for (const candidate of queued) {
      try {
        await pc.addIceCandidate(new RTCIceCandidate(candidate));
      } catch {
        // stale candidate: safe to drop
      }
    }
  }

  private teardown(): void {
    try {
      this.pc?.close();
    } catch {
      // ignore teardown errors
    }
    this.pc = null;
    if (this.localStream) {
      this.localStream.getTracks().forEach((t) => t.stop());
      this.localStream = null;
    }
    this.remoteStream = null;
    this.pendingIce = [];
    this.pendingIceSend = [];
    this.peerId = null;
    this.started = false;
  }

  /** Clean leave: notify peer, close RTCPeerConnection, stop mic, drop socket. */
  public leave(): void {
    // Idempotent: safe to call twice or without joining.
    try {
      webrtcSignaling.leave();
    } catch {
      // ignore teardown errors
    }
    webrtcSignaling.disconnect();
    this.teardown();
    this.callId = '';
    this.participantId = '';
    this.displayName = '';
    this.emit('closed');
    // Detach handlers AFTER emitting 'closed' so no late pc callback
    // (e.g. a trailing connectionstatechange) can reach unmounted UI
    // and resurrect state for a dead call.
    this.events = {};
  }
}

export const webrtcCall = new WebRTCCallManager();
