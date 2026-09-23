# VoiceGuard — AI Real-Time Voice Integrity & Deepfake Detection

<p align="center">
  <img src="public/vite.svg" width="80" alt="VoiceGuard Logo"/>
</p>

<p align="center">
  <strong>AI-powered real-time voice integrity monitoring system for controlled WebRTC/VoIP calls</strong>
</p>

<p align="center">
  <img alt="React" src="https://img.shields.io/badge/React-19-61DAFB?style=for-the-badge&logo=react"/>
  <img alt="TypeScript" src="https://img.shields.io/badge/TypeScript-6.0-3178C6?style=for-the-badge&logo=typescript"/>
  <img alt="Vite" src="https://img.shields.io/badge/Vite-8.3-646CFF?style=for-the-badge&logo=vite"/>
  <img alt="License" src="https://img.shields.io/badge/License-MIT-green?style=for-the-badge"/>
</p>

---

## 🛡️ Overview

VoiceGuard is a hackathon project that demonstrates **real-time AI-powered voice integrity monitoring** for WebRTC/VoIP calls. It detects synthetic voices (deepfakes, neural vocoders) in live call streams and alerts security teams through a dual-interface dashboard.

### ✨ Key Features

- **Real-Time Neural Voice Analysis**: Continuous analysis of WebRTC audio streams for synthetic/deepfake speech patterns
- **Dual Live Demo Mode**: Synchronized Mobile App + SOC Dashboard view with shared Call ID
- **Risk State Engine**: 0–39 LOW → 40–69 MEDIUM → 70–100 HIGH with smooth UI transitions
- **Live Risk Chart**: Continuously updating SVG line chart showing risk vs. time
- **Audio Evidence Player**: Web Audio API synthesizer with vocoder artifact simulation
- **WebSocket Architecture**: Clean service layer with auto-reconnect and demo simulator fallback
- **Investigation Modal**: Full forensic analysis with detection timeline and containment actions

---

## 📱 Application Architecture

```
VoiceGuard Frontend
├── Part 1: Mobile Application (Android-style)
│   ├── Splash Screen
│   ├── Home Screen (Security status + "Start Secure Call" CTA)
│   ├── Active Call Screen (Live Voice Integrity Gauge 0–100)
│   ├── Call End Screen (Final risk + evidence)
│   ├── Call History (Search + LOW/MEDIUM/HIGH filters)
│   ├── Call Details (Risk-over-time graph + detection timeline)
│   └── Evidence Screen (Audio player + acoustic forensics)
│
├── Part 2: Web SOC Dashboard
│   ├── Overview (Stats + Active Calls Table + Risk Chart + Alert)
│   ├── Active Calls (Live monitoring grid)
│   ├── Live Monitoring (Real-time spectrogram + vocoder metrics)
│   ├── Detection Events (Audit trail with filters)
│   ├── Evidence Vault (Cryptographic evidence player)
│   ├── Call History (Archived sessions)
│   └── System Status (Node topology + AI model health)
│
├── Shared Services
│   ├── WebSocket Service (with reconnection + demo broadcast)
│   ├── Demo Simulator (0s→18s progression)
│   ├── API Service Layer (REST with mock fallback)
│   └── React CallContext (global state)
│
└── Hackathon Demo Controller
    ├── Dual / Mobile / SOC view switcher
    ├── Playback: Play / Pause / Reset / Jump to step
    └── Fast-forward: "Simulate High Risk (18s)"
```

---

## 🚀 Getting Started

### Prerequisites
- Node.js 18+
- npm 9+

### Installation

```bash
git clone https://github.com/soumyajitd1307-hash/VoiceGuard.git
cd VoiceGuard
npm install
```

### Environment Setup

```bash
cp .env.example .env
# Edit .env to configure your backend WebSocket and API URLs
```

### Run in Development Mode (with Demo Simulation)

```bash
npm run dev
```

Open http://localhost:5173

### Build for Production

```bash
npm run build
```

---

## 🎯 Hackathon Demo Flow

The app opens in **Dual Live Demo** view with Demo Mode **ON** by default.

1. ✅ Open app → See Mobile phone (left) + SOC Dashboard (right)
2. ✅ Mobile: Click **"Start Secure Call"** (Rahul #1042)
3. ✅ Risk starts at **18/100 LOW** (normal voice profile established)
4. ✅ Timeline auto-progresses: 5s → 10s → 14s → **18s HIGH RISK**
5. ✅ At 18s: RED alert banner appears: **"POSSIBLE SYNTHETIC VOICE DETECTED"**
6. ✅ Mobile transitions: **"POSSIBLE SYNTHETIC VOICE / 84/100 / HIGH RISK"**
7. ✅ Click **INVESTIGATE** → forensic modal with risk graph + timeline + audio evidence
8. ✅ Click **Play** on Evidence Player → hear synthesized deepfake audio simulation
9. ✅ Use top timeline buttons to jump between stages

### Fast Controls

| Button | Action |
|--------|--------|
| `18s (84)` | Jump to HIGH RISK state immediately |
| `Simulate High Risk (18s)` | Same shortcut in top bar |
| `▶ Play` | Start auto-progression from current second |
| `⏸ Pause` | Freeze simulation |
| `↺ Reset` | Restart from 0s LOW risk |

---

## 🔌 Backend Integration

To connect to a real backend:

1. Set environment variables in `.env`:
   ```
   VITE_WS_URL=ws://your-backend:8000/ws/calls
   VITE_API_BASE_URL=http://your-backend:8000/api/v1
   VITE_ENABLE_DEMO_MODE=false
   ```

2. Toggle **Demo Mode OFF** in the app header.

3. Backend should emit WebSocket messages in this format:
   ```json
   {
     "type": "risk_update",
     "callId": "1042",
     "timestamp": 18,
     "risk": 84,
     "syntheticProbability": 91,
     "speakerConsistency": 64,
     "contextRisk": 90,
     "confidence": "HIGH"
   }
   ```

The UI updates in real-time with no code changes required.

---

## 📊 Risk Classification

| Score Range | Level | Color | Action |
|-------------|-------|-------|--------|
| 0–39 | LOW | 🟢 Emerald | Monitor |
| 40–69 | MEDIUM | 🟡 Amber | Alert |
| 70–100 | HIGH | 🔴 Red | Immediate Action |

---

## 🛠️ Technology Stack

- **Framework**: React 19 + TypeScript 6
- **Build Tool**: Vite 8
- **Icons**: Lucide React
- **Audio**: Web Audio API (built-in)
- **Charts**: Custom SVG (no dependencies)
- **Fonts**: Plus Jakarta Sans + JetBrains Mono (Google Fonts)
- **Styling**: Vanilla CSS with CSS Custom Properties

---

## 👥 Team

Built for hackathon presentation by the VoiceGuard team.

---

## 📄 License

MIT
