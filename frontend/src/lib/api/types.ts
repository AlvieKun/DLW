// ─── Backend API Types (derived from OpenAPI / Pydantic models) ───

export type LearnerEventType =
  | "quiz_result"
  | "time_on_task"
  | "sentiment_signal"
  | "motivation_signal"
  | "inactivity_gap"
  | "content_interaction"
  | "self_report"
  | "teacher_annotation"
  | "custom";

export interface EventRequest {
  event_id: string;
  learner_id?: string;  // auto-filled from auth on backend
  event_type: LearnerEventType;
  concept_id?: string | null;
  data?: Record<string, unknown>;
}

export interface ExplainabilityFactor {
  agent_id: string;
  agent_name: string;
  signal: string;
  evidence: string;
  confidence?: number | null;
}

export interface DecisionTrace {
  ran_agents: string[];
  skipped_agents: string[];
  debate_outcome?: Record<string, unknown> | null;
  maker_checker?: Record<string, unknown> | null;
}

export interface Explainability {
  top_factors: ExplainabilityFactor[];
  decision_trace: DecisionTrace;
}

export interface ExpectedImpact {
  mastery_gain_estimate?: number | null;
  confidence_gain_estimate?: number | null;
  risk_reduction: Record<string, number>;
  time_horizon_days?: number | null;
  assumptions: string[];
}

export interface NextBestAction {
  action_id: string;
  learner_id: string;
  recommended_action: string;
  rationale: string;
  confidence: number;
  expected_learning_gain: number;
  risk_assessment: Record<string, number>;
  citations: string[];
  debug_trace: Record<string, unknown>;
  explainability: Explainability;
  expected_impact: ExpectedImpact;
  timestamp: string;
}

export interface HealthResponse {
  status: string;
  version: string;
  environment: string;
}

export interface BKTParams {
  p_know: number;
  p_init: number;
  p_transit: number;
  p_slip: number;
  p_guess: number;
}

export type MotivationLevel = "HIGH" | "MEDIUM" | "LOW" | "CRITICAL";

export interface MotivationState {
  level: MotivationLevel;
  score: number;
  trend: number;
  confidence: number;
  last_updated: string;
}

export interface ConceptState {
  concept_id: string;
  display_name: string;
  bkt: BKTParams;
  last_practiced: string | null;
  practice_count: number;
  forgetting_score: number;
  spacing_history: number[];
  difficulty: number;
}

export interface DriftSignal {
  drift_type: string;
  severity: number;
  detected_at: string;
  details: Record<string, unknown>;
}

export interface BehavioralAnomaly {
  anomaly_type: string;
  severity: number;
  detected_at: string;
  evidence: Record<string, unknown>;
  resolved: boolean;
}

export interface TimeBudget {
  total_hours_per_week: number;
  hours_remaining_this_week: number;
  preferred_session_minutes: number;
  deadline: string | null;
  priority_concept_ids: string[];
}

export interface LearnerState {
  schema_version: string;
  learner_id: string;
  updated_at: string;
  concepts: Record<string, ConceptState>;
  motivation: MotivationState;
  active_drift_signals: DriftSignal[];
  behavioral_anomalies: BehavioralAnomaly[];
  time_budget: TimeBudget;
  session_count: number;
  last_active: string | null;
  total_practice_time_hours: number;
  global_confidence: number;
  metadata: Record<string, unknown>;
}

export interface LearnerStateResponse {
  learner_id: string;
  found: boolean;
  state: LearnerState | null;
}

export interface PortfolioEntry {
  [key: string]: unknown;
}

export interface PortfolioResponse {
  learner_id: string;
  count: number;
  entries: PortfolioEntry[];
}

export interface CalibrationResponse {
  agents: Record<string, unknown>;
}

export interface LearnersListResponse {
  learner_ids: string[];
  count: number;
}

// ─── Auth Types ───

export interface AuthUser {
  id: string;
  email: string;
  display_name: string;
  onboarded: boolean;
  created_at: string;
}

export interface RegisterRequest {
  email: string;
  password: string;
  display_name: string;
}

export interface LoginRequest {
  email: string;
  password: string;
}

export interface UserProfile {
  user_id: string;
  onboarded: boolean;
  learning_goals: Record<string, unknown> | null;
  subjects: Array<Record<string, unknown>> | null;
  weekly_schedule: Record<string, unknown> | null;
  preferences: Record<string, unknown> | null;
  baseline_assessment: Record<string, unknown> | null;
}

export interface ProfileUpdate {
  learning_goals?: Record<string, unknown>;
  subjects?: Array<Record<string, unknown>>;
  weekly_schedule?: Record<string, unknown>;
  preferences?: Record<string, unknown>;
  baseline_assessment?: Record<string, unknown>;
}

export interface UserEvent {
  id: string;
  user_id: string;
  concept: string;
  score: number | null;
  time_spent_minutes: number | null;
  event_type: string;
  notes: string;
  source: string;
  timestamp: string;
  created_at: string;
}

export interface UserUpload {
  id: string;
  user_id: string;
  file_name: string;
  file_type: string;
  file_size: number;
  storage_path: string;
  created_at: string;
}

export interface AgentStatus {
  agent_id: string;
  agent_name: string;
  friendly_name: string;
  description: string;
  module: string;
  class_name: string;
  status: "implemented" | "partial" | "stub" | "error" | "unknown";
  evidence: string;
  file_path: string;
  method_count: number;
  line_count: number;
  checked_at: string;
}

export interface AgentSystemSummary {
  total: number;
  implemented: number;
  partial: number;
  stub: number;
  health_level: string;
  health_pct: number;
  label: string;
  description: string;
  engine_type: string;
  engine_note: string;
}

export interface AgentStatusResponse {
  agents: AgentStatus[];
  total_agents: number;
  implemented_agents: number;
  summary: AgentSystemSummary;
}

// ─── Weekly Summary Types ───

export interface WeeklySummary {
  id?: string;
  user_id?: string;
  week_start?: string;
  week_end?: string;
  summary_text: string;
  highlights: string[];
  focus_items: string[];
  burnout_flag: boolean;
  evidence_bullets: string[];
  model_used?: string;
  status: "generated" | "unavailable" | "error";
  disclaimer?: string;
  message?: string;
  created_at?: string;
}
