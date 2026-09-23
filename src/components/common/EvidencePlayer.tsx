import React, { useState, useEffect } from 'react';
import { Play, Pause, RotateCcw, Volume2, ShieldAlert, Cpu } from 'lucide-react';
import { Evidence } from '../../types';
import { audioSynthesizer } from '../../utils/audioSynth';
import { getRiskTheme } from '../../utils/risk';

interface EvidencePlayerProps {
  evidence: Evidence;
  autoPlay?: boolean;
}

export const EvidencePlayer: React.FC<EvidencePlayerProps> = ({ evidence }) => {
  const [isPlaying, setIsPlaying] = useState(false);
  const [playbackProgress, setPlaybackProgress] = useState(0); // 0 to 100%

  const isHighRisk = evidence.overallRisk >= 70;
  const theme = getRiskTheme(evidence.overallRisk);

  useEffect(() => {
    let animFrame: number;
    let startTime: number;
    const durationMs = (evidence.durationSeconds || 4.5) * 1000;

    if (isPlaying) {
      startTime = performance.now();
      const step = (now: number) => {
        const elapsed = now - startTime;
        const prog = Math.min(100, (elapsed / durationMs) * 100);
        setPlaybackProgress(prog);

        if (prog < 100) {
          animFrame = requestAnimationFrame(step);
        } else {
          setIsPlaying(false);
          setPlaybackProgress(0);
        }
      };
      animFrame = requestAnimationFrame(step);
    }

    return () => {
      if (animFrame) cancelAnimationFrame(animFrame);
    };
  }, [isPlaying, evidence.durationSeconds]);

  const handleTogglePlay = () => {
    if (isPlaying) {
      audioSynthesizer.stop();
      setIsPlaying(false);
      setPlaybackProgress(0);
    } else {
      setIsPlaying(true);
      setPlaybackProgress(0);
      audioSynthesizer.playEvidenceSample(
        isHighRisk,
        evidence.durationSeconds || 4.5,
        () => {
          setIsPlaying(false);
          setPlaybackProgress(0);
        }
      );
    }
  };

  const handleReplay = () => {
    audioSynthesizer.stop();
    setIsPlaying(false);
    setPlaybackProgress(0);
    setTimeout(() => {
      handleTogglePlay();
    }, 50);
  };

  return (
    <div
      style={{
        background: 'var(--bg-secondary)',
        border: `1px solid ${isHighRisk ? 'rgba(239, 68, 68, 0.4)' : 'var(--border-subtle)'}`,
        borderRadius: '12px',
        padding: '16px',
        display: 'flex',
        flexDirection: 'column',
        gap: '14px'
      }}
    >
      {/* Evidence Header */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <Volume2 size={16} color={theme.primary} />
          <span style={{ fontSize: '13px', fontWeight: 700, color: 'var(--text-main)' }}>
            Acoustic Evidence Segment ({evidence.formattedTime})
          </span>
          <span
            style={{
              fontSize: '10px',
              padding: '2px 6px',
              borderRadius: '4px',
              background: 'rgba(255, 255, 255, 0.1)',
              color: 'var(--text-muted)'
            }}
          >
            {evidence.durationSeconds}s Clip
          </span>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
          <Cpu size={14} color="var(--accent-cyan)" />
          <span style={{ fontSize: '11px', color: 'var(--accent-cyan)', fontWeight: 600 }}>
            {evidence.detectionType}
          </span>
        </div>
      </div>

      {/* Waveform Visualizer & Playhead */}
      <div
        style={{
          position: 'relative',
          height: '64px',
          background: 'rgba(0, 0, 0, 0.4)',
          borderRadius: '8px',
          padding: '0 12px',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          overflow: 'hidden'
        }}
      >
        {/* Playhead line */}
        <div
          style={{
            position: 'absolute',
            top: 0,
            bottom: 0,
            left: `${playbackProgress}%`,
            width: '2px',
            backgroundColor: theme.primary,
            boxShadow: `0 0 8px ${theme.primary}`,
            zIndex: 10,
            transition: 'left 0.05s linear'
          }}
        />

        {/* Audio Bars */}
        {(evidence.waveform || []).map((amp, idx) => {
          const barHeight = Math.max(6, Math.min(54, amp * 52));
          const isPassed = (idx / evidence.waveform.length) * 100 <= playbackProgress;

          return (
            <div
              key={idx}
              style={{
                width: '4px',
                height: `${barHeight}px`,
                borderRadius: '2px',
                backgroundColor: isPassed
                  ? theme.primary
                  : isHighRisk && amp > 0.7
                  ? 'rgba(239, 68, 68, 0.6)'
                  : 'rgba(255, 255, 255, 0.25)',
                transition: 'background-color 0.1s ease',
                boxShadow: isPassed ? `0 0 6px ${theme.primary}` : 'none'
              }}
            />
          );
        })}
      </div>

      {/* Playback Controls & Timestamps */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
          <button
            onClick={handleTogglePlay}
            style={{
              width: '36px',
              height: '36px',
              borderRadius: '50%',
              background: theme.primary,
              border: 'none',
              color: '#ffffff',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              cursor: 'pointer',
              boxShadow: `0 0 10px ${theme.primary}`
            }}
            title={isPlaying ? 'Pause evidence' : 'Play audio evidence sample'}
          >
            {isPlaying ? <Pause size={16} /> : <Play size={16} style={{ marginLeft: '2px' }} />}
          </button>

          <button
            onClick={handleReplay}
            style={{
              background: 'rgba(255, 255, 255, 0.08)',
              border: '1px solid var(--border-subtle)',
              borderRadius: '50%',
              width: '32px',
              height: '32px',
              color: 'var(--text-muted)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              cursor: 'pointer'
            }}
            title="Replay from start"
          >
            <RotateCcw size={14} />
          </button>

          <span className="font-mono" style={{ fontSize: '12px', color: 'var(--text-muted)' }}>
            {isPlaying ? `Playing (${Math.round((playbackProgress / 100) * evidence.durationSeconds)}s)` : 'Audio Evidence Sample'}
          </span>
        </div>

        {/* Anomaly Badges */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <span
            style={{
              fontSize: '11px',
              padding: '3px 8px',
              borderRadius: '4px',
              background: theme.bgLight,
              color: theme.text,
              fontWeight: 700
            }}
          >
            Risk: {evidence.overallRisk}/100
          </span>
        </div>
      </div>

      {/* Metrics Breakdown Grid */}
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(3, 1fr)',
          gap: '8px',
          padding: '10px',
          background: 'rgba(0, 0, 0, 0.25)',
          borderRadius: '8px'
        }}
      >
        <div>
          <span style={{ fontSize: '10px', color: 'var(--text-dim)', textTransform: 'uppercase' }}>Synthetic Prob</span>
          <div className="font-mono" style={{ fontSize: '13px', fontWeight: 700, color: theme.text }}>
            {evidence.syntheticProbability}%
          </div>
        </div>
        <div>
          <span style={{ fontSize: '10px', color: 'var(--text-dim)', textTransform: 'uppercase' }}>Speaker Consistency</span>
          <div className="font-mono" style={{ fontSize: '13px', fontWeight: 700, color: 'var(--text-main)' }}>
            {evidence.speakerConsistency}%
          </div>
        </div>
        <div>
          <span style={{ fontSize: '10px', color: 'var(--text-dim)', textTransform: 'uppercase' }}>Context Risk</span>
          <div className="font-mono" style={{ fontSize: '13px', fontWeight: 700, color: '#f87171' }}>
            {evidence.contextRisk}%
          </div>
        </div>
      </div>

      {/* Forensic Findings */}
      {evidence.anomalyNotes && evidence.anomalyNotes.length > 0 && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
          <span style={{ fontSize: '11px', fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase' }}>
            Acoustic Artifact Findings:
          </span>
          {evidence.anomalyNotes.map((note, i) => (
            <div
              key={i}
              style={{
                fontSize: '11px',
                color: 'var(--text-muted)',
                display: 'flex',
                alignItems: 'baseline',
                gap: '6px'
              }}
            >
              <span style={{ color: theme.primary }}>•</span>
              {note}
            </div>
          ))}
        </div>
      )}
    </div>
  );
};
