// Sample learner IDs used when backend has no data (for layout previews).
// These are clearly labeled as "Sample UI Data" in the UI.

export const SAMPLE_LEARNER_ID = "student-1";

export const SAMPLE_CONCEPTS = [
  { concept_id: "algebra-basics", display_name: "Algebra Basics", mastery: 0.82, forgetting: 0.12 },
  { concept_id: "quadratic-equations", display_name: "Quadratic Equations", mastery: 0.45, forgetting: 0.35 },
  { concept_id: "linear-functions", display_name: "Linear Functions", mastery: 0.91, forgetting: 0.05 },
  { concept_id: "trigonometry-intro", display_name: "Trigonometry Intro", mastery: 0.28, forgetting: 0.55 },
  { concept_id: "calculus-limits", display_name: "Calculus: Limits", mastery: 0.15, forgetting: 0.7 },
];

export const SAMPLE_AGENT_ACTIVITY = [
  { agent: "Diagnoser", status: "ran", summary: "Identified weak concepts: quadratic-equations, trigonometry-intro", confidence: 0.78 },
  { agent: "Planner", status: "ran", summary: "Generated 3-step study plan focused on pre-requisites", confidence: 0.72 },
  { agent: "Motivation", status: "ran", summary: "Motivation level: MEDIUM, trend: improving (+0.1)", confidence: 0.65 },
  { agent: "Drift Detector", status: "ran", summary: "No significant drift detected", confidence: 0.85 },
  { agent: "Decay Monitor", status: "ran", summary: "Forgetting risk high for trigonometry-intro", confidence: 0.80 },
  { agent: "RAG Agent", status: "stub", summary: "RAG retrieval not configured — demo mode", confidence: 0.0 },
  { agent: "Debate Advocates", status: "ran", summary: "2 strategies proposed: spaced practice vs intensive review", confidence: 0.70 },
  { agent: "Debate Arbitrator", status: "ran", summary: "Selected: spaced practice (higher retention forecast)", confidence: 0.75 },
];

export const SAMPLE_PLAN_ITEMS = [
  { phase: "now", concept: "Quadratic Equations", action: "Review factoring techniques", priority: "high" },
  { phase: "now", concept: "Trigonometry Intro", action: "Watch unit circle video + 5 practice problems", priority: "high" },
  { phase: "next", concept: "Algebra Basics", action: "Spaced review — 10 mixed problems", priority: "medium" },
  { phase: "next", concept: "Calculus: Limits", action: "Read chapter 2.1 + conceptual quiz", priority: "medium" },
  { phase: "later", concept: "Linear Functions", action: "Maintain mastery — weekly review quiz", priority: "low" },
];

export const SAMPLE_FORECAST_DATA = [
  { day: "Day 1", planA: 42, planB: 42, rest: 42 },
  { day: "Day 3", planA: 48, planB: 46, rest: 40 },
  { day: "Day 7", planA: 58, planB: 52, rest: 36 },
  { day: "Day 14", planA: 70, planB: 62, rest: 30 },
  { day: "Day 21", planA: 78, planB: 68, rest: 25 },
  { day: "Day 30", planA: 85, planB: 74, rest: 22 },
];
