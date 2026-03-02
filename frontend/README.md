# Learning Navigator — Frontend

A consumer-grade web interface for the Learning Navigator AI platform. Built around the **"Learning GPS"** concept — your personal AI tutor powered by 14 specialized agents that analyze your progress and guide your study sessions.

## UX Philosophy

- **Personal, not technical** — No developer jargon. "Your strengths & gaps" instead of "Concept Mastery". "Get Today's Guidance" instead of "POST /api/v1/events".
- **You are the only learner** — No student selector dropdown, no exposed learner IDs. The app uses your authenticated account automatically.
- **Your AI team is visible** — 14 agents (Gap Finder, Study Planner, Motivation Coach, Memory Guard, etc.) are named, described, and shown working for you.
- **Guided empty states** — Every section has a helpful empty state with a clear CTA instead of a blank page.
- **Upload-friendly** — Prominent "Add Study Data" nav item and drag-drop file upload throughout.

## Stack

- **Next.js 15** (App Router) + **TypeScript**
- **Tailwind CSS 4** for styling
- **Framer Motion** for animations
- **Recharts** for charts
- **Lucide React** for icons

## Pages

| Route | Label | Purpose |
|---|---|---|
| `/` | **Home** | GPS hero card, "Get Today's Guidance" CTA, stats, AI team cards, strengths & gaps grid |
| `/session` | **Study Session** | Log what you studied, get AI feedback with recommendations, evidence, and confidence |
| `/plan` | **Your Plan** | Kanban/timeline study plan (Focus now / Coming up / Maintain), what-if scenarios |
| `/portfolio` | **Learning Journal** | AI-generated insights + your own reflections, searchable, filterable |
| `/my-data` | **Add Study Data** | Log activity or upload files (drag-drop), event history |
| `/settings` | **Settings** | Account info, learning profile, schedule, security |
| `/login` | Login | Email + password login |
| `/register` | Register | Create account |
| `/onboarding` | Onboarding | 4-step wizard: goals, subjects, schedule, confirmation |
| `/dev-tools` | Developer Tools | Backend health, endpoint ping, agent diagnostics (hidden behind footer link) |

## Your AI Team (14 agents)

| Friendly Name | Backend Agent | What it does |
|---|---|---|
| Gap Finder | Diagnoser | Identifies what you need to work on |
| Study Planner | Planner | Builds your personalized study plan |
| Motivation Coach | Motivation | Tracks your energy and engagement |
| Focus Monitor | Drift Detector | Notices when your learning drifts |
| Memory Guard | Decay Monitor | Flags topics you might forget |
| Research Helper | RAG Agent | Finds relevant study materials |
| Strategy Team | Debate Advocates | Proposes different study approaches |
| Decision Maker | Debate Arbitrator | Picks the best strategy for you |
| Progress Analyst | Evaluator | Measures how well you're doing |
| Learning Mirror | Reflection | Helps you reflect on progress |
| Schedule Optimizer | Time Optimizer | Makes the most of your study time |
| Practice Generator | Generative Replay | Creates review exercises |
| Knowledge Tracker | Skill State | Tracks what you know |
| Habit Analyst | Behavior | Understands your study patterns |

## Architecture

```
src/
├── app/              # Next.js App Router pages
│   ├── layout.tsx    # Root layout (auth gate + sidebar + top bar)
│   ├── page.tsx      # Home (Learning GPS)
│   ├── session/      # Study Session
│   ├── plan/         # Your Plan
│   ├── portfolio/    # Learning Journal
│   ├── my-data/      # Add Study Data
│   ├── settings/     # Settings
│   ├── login/        # Login
│   ├── register/     # Register
│   ├── onboarding/   # Onboarding wizard
│   └── dev-tools/    # Developer Tools
├── components/
│   ├── client-shell.tsx  # Auth gate (redirects to /login or /onboarding)
│   ├── sidebar.tsx       # Navigation (Home, Study Session, Your Plan, etc.)
│   ├── top-bar.tsx       # Top bar with dark mode + user menu
│   └── ui.tsx            # Shared UI (Card, Badge, StatCard, Tabs, etc.)
└── lib/
    ├── auth-context.tsx  # React auth provider (JWT cookies)
    ├── api/
    │   ├── client.ts     # Typed API client with proxy + error handling
    │   ├── types.ts      # TypeScript types matching Pydantic models
    │   └── index.ts      # Re-exports
    ├── utils.ts          # cn(), formatDate(), pct(), confidenceBadge()
    └── sample-data.ts    # Preview data (labeled clearly in UI)
```

## Auth Flow

1. User registers → JWT cookie set → redirected to onboarding
2. Onboarding wizard (4 steps) → profile saved → redirected to Home
3. All subsequent visits: cookie checked → auto-login or redirect to /login
4. Learner ID = authenticated user ID (no multi-user leakage)

## Quick Start

```bash
cd frontend
cp .env.example .env.local   # Edit if backend is not on :8000
npm install
npm run dev                   # http://localhost:3000
```

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `NEXT_PUBLIC_API_BASE_URL` | `http://127.0.0.1:8000` | Backend API base URL |

## Design Principles

- Dark mode default, light mode toggle in top bar
- Responsive: desktop sidebar, mobile hamburger menu
- Framer Motion animations on all interactive elements
- Graceful fallbacks: sample data shown (clearly labeled) when backend is offline
- Human-first copy: every label written for learners, not engineers
