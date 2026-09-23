/**
 * Audio Synthesizer & Web Audio Engine for VoiceGuard
 * Generates realistic audio simulation with vocoder/cloned artifacts for evidence playback
 * and provides live audio frequency data for visualizers.
 */

class AudioSynthesizer {
  private ctx: AudioContext | null = null;
  private isPlaying = false;
  private activeNodes: (AudioNode | number)[] = [];
  private onEndedCallback: (() => void) | null = null;

  private getContext(): AudioContext {
    if (!this.ctx) {
      const AudioCtx = window.AudioContext || (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext;
      this.ctx = new AudioCtx();
    }
    if (this.ctx.state === 'suspended') {
      this.ctx.resume();
    }
    return this.ctx;
  }

  /**
   * Plays a simulated voice evidence sample with deepfake neural vocoder artifacts
   * @param isSynthetic whether to add glitchy vocoder overtone harmonics
   * @param duration seconds to play (default 4s)
   */
  public playEvidenceSample(isSynthetic: boolean = true, duration: number = 4.5, onEnded?: () => void): void {
    this.stop();
    const ctx = this.getContext();
    this.isPlaying = true;
    this.onEndedCallback = onEnded || null;

    const masterGain = ctx.createGain();
    masterGain.gain.setValueAtTime(0.3, ctx.currentTime);
    masterGain.connect(ctx.destination);

    // Fundamental human speech frequency (~130Hz - 220Hz male/female range)
    const baseFreqs = [140, 165, 185, 210, 175, 150];
    const stepDuration = duration / baseFreqs.length;

    // Carrier Oscillator (fundamental formant)
    const osc1 = ctx.createOscillator();
    osc1.type = isSynthetic ? 'sawtooth' : 'triangle';

    // Modulator Oscillator (synthesizer/neural vocoder metallic artifact)
    const osc2 = ctx.createOscillator();
    osc2.type = 'sine';
    osc2.frequency.setValueAtTime(isSynthetic ? 840 : 280, ctx.currentTime);

    // Filter to shape into vocal tract formants (Bandpass)
    const filter = ctx.createBiquadFilter();
    filter.type = 'bandpass';
    filter.frequency.setValueAtTime(800, ctx.currentTime);
    filter.Q.setValueAtTime(isSynthetic ? 4.5 : 1.5, ctx.currentTime);

    // Formant pitch envelope
    baseFreqs.forEach((freq, idx) => {
      const time = ctx.currentTime + idx * stepDuration;
      // If synthetic, add micro-pitch wobbles and rigid quantizations
      const pitchTarget = isSynthetic ? Math.round(freq / 10) * 10 : freq;
      osc1.frequency.setValueAtTime(pitchTarget, time);
      filter.frequency.setValueAtTime(freq * 3, time);
    });

    // Neural vocoder metallic distortion if synthetic
    if (isSynthetic) {
      const glitchGain = ctx.createGain();
      glitchGain.gain.setValueAtTime(0.18, ctx.currentTime);
      osc2.connect(filter);
      filter.connect(masterGain);
    }

    osc1.connect(filter);
    filter.connect(masterGain);

    // Envelope
    masterGain.gain.setValueAtTime(0.001, ctx.currentTime);
    masterGain.gain.linearRampToValueAtTime(0.28, ctx.currentTime + 0.1);
    masterGain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + duration);

    osc1.start(ctx.currentTime);
    osc2.start(ctx.currentTime);

    osc1.stop(ctx.currentTime + duration);
    osc2.stop(ctx.currentTime + duration);

    const timer = window.setTimeout(() => {
      this.isPlaying = false;
      if (this.onEndedCallback) {
        this.onEndedCallback();
      }
    }, duration * 1000);

    this.activeNodes = [osc1, osc2, masterGain, timer];
  }

  public stop(): void {
    this.isPlaying = false;
    this.activeNodes.forEach(node => {
      if (typeof node === 'number') {
        clearTimeout(node);
      } else {
        try {
          (node as AudioScheduledSourceNode).stop?.();
          node.disconnect();
        } catch {
          // ignore if already disconnected
        }
      }
    });
    this.activeNodes = [];
    if (this.onEndedCallback) {
      this.onEndedCallback();
      this.onEndedCallback = null;
    }
  }

  public getIsPlaying(): boolean {
    return this.isPlaying;
  }
}

export const audioSynthesizer = new AudioSynthesizer();
