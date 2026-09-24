/**
 * Backend 1 — browser microphone capture (Milestone 2).
 *
 * Pipeline:
 *   navigator.mediaDevices.getUserMedia (mic)
 *     -> AudioContext at the device sample rate (e.g. 48000 Hz)
 *     -> AudioWorklet (downmix to mono, forward Float32 frames)
 *     -> main thread: REAL resampling to 16 kHz (linear interpolation)
 *     -> Float32 -> Int16 LE PCM
 *     -> fixed 250 ms frames (4000 samples = 8000 bytes) via onChunk
 *
 * Output contract (matches Backend 1 milestone-1 audio contract):
 *   sample rate 16000 Hz, 1 channel, signed 16-bit PCM, little-endian,
 *   delivered as raw ArrayBuffer (never base64, never JSON, never REST).
 *
 * This module is dependency-free (no imports from app code) and never
 * touches the risk WebSocket (src/services/websocket.ts) or CallContext.
 * Pure helpers (resampleFloat32 / floatTo16BitPCM) are exported so the
 * 16 kHz math can be unit-tested outside a browser.
 *
 * Two entry points share one conversion graph:
 *   start()            — owns a getUserMedia microphone stream.
 *   startFromStream()  — borrows an existing MediaStream (e.g. a WebRTC
 *                        remote peer stream). Borrowed tracks are NEVER
 *                        stopped here; their owner (RTCPeerConnection)
 *                        manages their lifetime.
 */

export const TARGET_SAMPLE_RATE = 16000;
export const TARGET_CHANNELS = 1;
/** Samples per emitted frame: 4000 @ 16 kHz = 250 ms = 8000 bytes. */
export const FRAME_SAMPLES = 4000;

export type AudioChunkCallback = (chunk: ArrayBuffer) => void;

export interface AudioCaptureDiagnostics {
  running: boolean;
  /** Device/context rate BEFORE conversion (e.g. 48000). 0 until started. */
  inputSampleRate: number;
  outputSampleRate: number;
  channels: number;
  framesEmitted: number;
  bytesEmitted: number;
}

/**
 * Linear-interpolation resampler for mono Float32 audio.
 * Never labels input as output: output length is derived from the rate
 * ratio, so 48000 Hz in -> ~16000 Hz worth of samples out.
 */
export function resampleFloat32(
  input: Float32Array,
  fromRate: number,
  toRate: number,
): Float32Array {
  if (fromRate === toRate) {
    return input.slice();
  }
  if (input.length === 0 || fromRate <= 0 || toRate <= 0) {
    return new Float32Array(0);
  }
  const ratio = fromRate / toRate;
  const outLen = Math.floor(input.length / ratio);
  const out = new Float32Array(outLen);
  for (let i = 0; i < outLen; i++) {
    const x = i * ratio;
    const j = Math.floor(x);
    const frac = x - j;
    const a = input[j];
    const b = j + 1 < input.length ? input[j + 1] : a;
    out[i] = a + (b - a) * frac;
  }
  return out;
}

/** Clamp Float32 [-1, 1] -> signed Int16 little-endian bytes. */
export function floatTo16BitPCM(samples: Float32Array): ArrayBuffer {
  const buffer = new ArrayBuffer(samples.length * 2);
  const view = new DataView(buffer);
  for (let i = 0; i < samples.length; i++) {
    const clamped = Math.max(-1, Math.min(1, samples[i]));
    view.setInt16(i * 2, Math.round(clamped * 32767), true);
  }
  return buffer;
}

/**
 * Inline AudioWorklet processor source. Kept as a string so no extra
 * worklet file is needed; loaded via Blob URL in start().
 * Averages all input channels to mono and posts Float32 frames.
 */
const CAPTURE_WORKLET_CODE = `
class VoiceGuardCapture extends AudioWorkletProcessor {
  process(inputs) {
    const input = inputs && inputs[0];
    if (input && input.length > 0) {
      const frames = input[0].length;
      const mono = new Float32Array(frames);
      for (let i = 0; i < frames; i++) {
        let sum = 0;
        for (let ch = 0; ch < input.length; ch++) {
          sum += input[ch][i];
        }
        mono[i] = sum / input.length;
      }
      this.port.postMessage(mono);
    }
    return true;
  }
}
registerProcessor('voiceguard-capture', VoiceGuardCapture);
`;

export class AudioCaptureService {
  private stream: MediaStream | null = null;
  /** False when the stream is borrowed (remote peer): never stop its tracks. */
  private ownsStream = true;
  private ctx: AudioContext | null = null;
  private source: MediaStreamAudioSourceNode | null = null;
  private node: AudioWorkletNode | null = null;
  private workletUrl: string | null = null;
  private onChunk: AudioChunkCallback | null = null;

  /** Raw device-rate mono samples awaiting resampling. */
  private pending: number[] = [];
  /** Fractional input position already consumed (resampler continuity). */
  private consumedPos = 0;
  private inputRate = 0;

  /**
   * Startup generation: bumped by stop() and by each start() entry, so an
   * in-flight start() can detect it was cancelled (external end/unmount or
   * a superseding start) and release partial resources instead of
   * committing an orphaned microphone.
   */
  private generation = 0;

  private framesEmitted = 0;
  private bytesEmitted = 0;

  public isRunning(): boolean {
    return this.ctx !== null;
  }

  public getDiagnostics(): AudioCaptureDiagnostics {
    return {
      running: this.isRunning(),
      inputSampleRate: this.inputRate,
      outputSampleRate: TARGET_SAMPLE_RATE,
      channels: TARGET_CHANNELS,
      framesEmitted: this.framesEmitted,
      bytesEmitted: this.bytesEmitted,
    };
  }

  public async start(onChunk: AudioChunkCallback): Promise<void> {
    if (this.isRunning()) {
      throw new Error('audioCapture: already running — call stop() first');
    }
    if (
      typeof navigator === 'undefined' ||
      !navigator.mediaDevices?.getUserMedia
    ) {
      throw new Error('audioCapture: microphone API unavailable in this browser');
    }
    const AudioCtor =
      window.AudioContext ??
      (window as unknown as { webkitAudioContext?: typeof AudioContext })
        .webkitAudioContext;
    if (!AudioCtor) {
      throw new Error('audioCapture: Web Audio API unavailable in this browser');
    }

    let stream: MediaStream;
    // Capture the generation: any stop() (or superseding start()) from here
    // on invalidates this attempt — checked after every await below.
    this.generation += 1;
    const myGeneration = this.generation;
    try {
      stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          channelCount: 1,
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        },
      });
    } catch (err) {
      const name = err instanceof DOMException ? err.name : 'UnknownError';
      throw new Error(
        `audioCapture: microphone permission/capture failed (${name}). ` +
          'Grant mic access and retry.',
      );
    }
    if (myGeneration !== this.generation) {
      // Stopped (or superseded) while awaiting the microphone: release the
      // track and abort before committing any state.
      stream.getTracks().forEach((t) => t.stop());
      throw new Error('audioCapture: start cancelled (stop requested during startup)');
    }

    await this.attachStream(stream, onChunk, true, myGeneration, 'microphone');
  }

  /**
   * Capture an existing MediaStream (e.g. a WebRTC remote peer stream)
   * through the SAME mono -> 16 kHz -> Int16LE -> 250 ms framing graph.
   * The stream is borrowed: stop() releases the AudioContext/nodes but
   * never stops the stream's tracks (owned by the RTCPeerConnection).
   */
  public async startFromStream(
    stream: MediaStream,
    onChunk: AudioChunkCallback,
  ): Promise<void> {
    if (this.isRunning()) {
      throw new Error('audioCapture: already running — call stop() first');
    }
    if (!stream || stream.getAudioTracks().length === 0) {
      throw new Error('audioCapture: source stream has no audio tracks');
    }
    this.generation += 1;
    const myGeneration = this.generation;
    await this.attachStream(stream, onChunk, false, myGeneration, 'remote-peer');
  }

  private async attachStream(
    stream: MediaStream,
    onChunk: AudioChunkCallback,
    ownsStream: boolean,
    myGeneration: number,
    sourceLabel: string,
  ): Promise<void> {
    const AudioCtor =
      window.AudioContext ??
      (window as unknown as { webkitAudioContext?: typeof AudioContext })
        .webkitAudioContext;
    if (!AudioCtor) {
      throw new Error('audioCapture: Web Audio API unavailable in this browser');
    }
    const releaseSource = () => {
      if (ownsStream) {
        try {
          stream.getTracks().forEach((t) => t.stop());
        } catch {
          // ignore teardown errors
        }
      }
    };

    const ctx = new AudioCtor({ latencyHint: 'interactive' });
    try {
      // Must resume explicitly: browsers create it suspended until a gesture.
      await ctx.resume();
      if (myGeneration !== this.generation) {
        releaseSource();
        await ctx.close().catch(() => undefined);
        throw new Error('audioCapture: start cancelled (stop requested during startup)');
      }
      if (!ctx.audioWorklet) {
        throw new Error('audioCapture: AudioWorklet unavailable in this browser');
      }
      const blob = new Blob([CAPTURE_WORKLET_CODE], {
        type: 'application/javascript',
      });
      const url = URL.createObjectURL(blob);
      await ctx.audioWorklet.addModule(url);
      if (myGeneration !== this.generation) {
        releaseSource();
        URL.revokeObjectURL(url);
        await ctx.close().catch(() => undefined);
        throw new Error('audioCapture: start cancelled (stop requested during startup)');
      }

      const source = ctx.createMediaStreamSource(stream);
      const node = new AudioWorkletNode(ctx, 'voiceguard-capture');
      node.port.onmessage = (event: MessageEvent) => {
        this.handleWorkletFrame(event.data as Float32Array);
      };
      source.connect(node);

      // Commit state only after every step succeeded.
      this.stream = stream;
      this.ownsStream = ownsStream;
      this.ctx = ctx;
      this.source = source;
      this.node = node;
      this.workletUrl = url;
      this.onChunk = onChunk;
      this.inputRate = ctx.sampleRate;
      this.pending = [];
      this.consumedPos = 0;

      if (import.meta.env.DEV) {
        // eslint-disable-next-line no-console
        console.info(
          `[audioCapture] started (${sourceLabel}): device ${ctx.sampleRate} Hz -> ` +
            `${TARGET_SAMPLE_RATE} Hz mono Int16LE, frame ${FRAME_SAMPLES} samples`,
        );
      }
    } catch (err) {
      releaseSource();
      await ctx.close().catch(() => undefined);
      throw err instanceof Error
        ? err
        : new Error('audioCapture: failed to start audio graph');
    }
  }

  private handleWorkletFrame(frame: Float32Array): void {
    if (!this.onChunk || !this.ctx) return;
    for (let i = 0; i < frame.length; i++) {
      this.pending.push(frame[i]);
    }
    this.drainFrames();
  }

  /**
   * Resample accumulated device-rate samples and emit fixed FRAME_SAMPLES
   * frames. Fractional position is carried across calls so chunk N+1
   * continues exactly where chunk N ended (no drift, no gaps).
   */
  private drainFrames(): void {
    if (!this.onChunk) return;
    const ratio = this.inputRate / TARGET_SAMPLE_RATE;
    const need = (FRAME_SAMPLES - 1) * ratio + 1; // input span per frame
    let pos = this.consumedPos;

    while (this.pending.length - pos >= need) {
      const out = new Float32Array(FRAME_SAMPLES);
      for (let i = 0; i < FRAME_SAMPLES; i++) {
        const x = pos + i * ratio;
        const j = Math.floor(x);
        const frac = x - j;
        const a = this.pending[j];
        // Guard the boundary sample exactly like resampleFloat32: without
        // this, j+1 can read past the buffer and inject NaN (which would
        // encode as a silent sample and be sent to B1 as if real audio).
        const b = j + 1 < this.pending.length ? this.pending[j + 1] : a;
        out[i] = a + (b - a) * frac;
      }
      const pcm = floatTo16BitPCM(out);
      this.framesEmitted += 1;
      this.bytesEmitted += pcm.byteLength;
      this.onChunk(pcm);
      pos += FRAME_SAMPLES * ratio;
    }

    // Compact: drop fully consumed integer samples, keep fractional offset.
    const drop = Math.floor(pos);
    if (drop > 0) {
      this.pending.splice(0, drop);
      pos -= drop;
    }
    this.consumedPos = pos;
  }

  public stop(): void {
    // Idempotent: safe to call when already stopped or mid-stream.
    // Bumping the generation first invalidates any in-flight start(), which
    // releases its partial resources and aborts instead of committing state.
    this.generation += 1;
    try {
      this.node?.port.close();
      this.node?.disconnect();
    } catch {
      // ignore teardown errors
    }
    try {
      this.source?.disconnect();
    } catch {
      // ignore teardown errors
    }
    if (this.ctx) {
      const ctx = this.ctx;
      this.ctx = null;
      ctx.close().catch(() => undefined);
    }
    if (this.stream) {
      // Borrowed (remote-peer) tracks belong to the RTCPeerConnection and
      // must keep flowing to the call even after forwarding stops.
      if (this.ownsStream) {
        this.stream.getTracks().forEach((t) => t.stop());
      }
      this.stream = null;
    }
    if (this.workletUrl) {
      URL.revokeObjectURL(this.workletUrl);
      this.workletUrl = null;
    }
    this.source = null;
    this.node = null;
    this.onChunk = null;
    this.pending = [];
    this.consumedPos = 0;
    this.inputRate = 0;
    // Reset per-session diagnostics so a later session never inherits
    // earlier counts (frames/bytes are meaningful only per capture run).
    this.framesEmitted = 0;
    this.bytesEmitted = 0;
  }
}

export const audioCapture = new AudioCaptureService();
