"use client";

import { useState, useEffect, useCallback } from "react";
import { motion } from "framer-motion";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from "recharts";
import {
  Calendar,
  TrendingUp,
  AlertTriangle,
  Brain,
  Flame,
  Info,
  Target,
  BookOpen,
} from "lucide-react";
import Link from "next/link";
import {
  Card,
  Badge,
  SectionHeader,
  Tabs,
  ErrorBanner,
  SampleDataBanner,
  CardSkeleton,
} from "@/components/ui";
import { cn, pct } from "@/lib/utils";
import { getMyState, type LearnerState } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import { SAMPLE_PLAN_ITEMS, SAMPLE_FORECAST_DATA } from "@/lib/sample-data";

const PHASES = ["Now", "Next", "Later"] as const;
const PHASE_LABELS = {
  Now: "Focus on now",
  Next: "Coming up",
  Later: "Maintain",
} as const;

export default function PlanPage() {
  const { user } = useAuth();

  const [state, setState] = useState<LearnerState | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [useSample, setUseSample] = useState(false);
  const [viewTab, setViewTab] = useState("Kanban");
  const [simTab, setSimTab] = useState("Score");

  const fetchData = useCallback(async () => {
    setLoading(true);
    setError(null);
    const res = await getMyState();
    if (res.error) {
      setError(res.error);
      setUseSample(true);
    } else if (res.data?.found && res.data.state) {
      setState(res.data.state);
      setUseSample(false);
    } else {
      setUseSample(true);
    }
    setLoading(false);
  }, []);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  const planItems = useSample ? SAMPLE_PLAN_ITEMS : buildPlanFromState(state);

  return (
    <div className="space-y-6 max-w-7xl mx-auto">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Your Plan</h1>
        <p className="text-sm text-[var(--muted-foreground)] mt-1">
          A personalized study plan built by your AI team, with what-if scenarios
        </p>
      </div>

      {error && <ErrorBanner message={error} onRetry={fetchData} />}
      {useSample && !loading && <SampleDataBanner />}

      {/* Study Plan */}
      <div>
        <SectionHeader
          title="What to study"
          subtitle="Prioritized by your AI team: now, next, and later"
          action={
            <Tabs
              tabs={["Kanban", "Timeline"]}
              active={viewTab}
              onChange={setViewTab}
            />
          }
        />

        {loading ? (
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            {[1, 2, 3].map((i) => <CardSkeleton key={i} />)}
          </div>
        ) : planItems.length === 0 ? (
          <Card className="text-center py-12">
            <Target className="w-10 h-10 mx-auto text-[var(--muted-foreground)] mb-4 opacity-50" />
            <p className="text-sm font-medium mb-1">No study plan yet</p>
            <p className="text-xs text-[var(--muted-foreground)] max-w-sm mx-auto">
              Log some study activity and your AI team will build a personalized plan for you.
            </p>
            <Link
              href="/session"
              className="inline-flex items-center gap-2 mt-4 px-4 py-2 rounded-xl bg-[var(--primary)] text-[var(--primary-foreground)] text-sm font-medium hover:opacity-90 transition-opacity"
            >
              <BookOpen className="w-4 h-4" />
              Log study activity
            </Link>
          </Card>
        ) : viewTab === "Kanban" ? (
          <KanbanView items={planItems} />
        ) : (
          <TimelineView items={planItems} />
        )}
      </div>

      {/* What-If Scenarios */}
      <div>
        <SectionHeader
          title="What-if scenarios"
          subtitle="See how different study strategies could play out"
          action={
            <Tabs
              tabs={["Score", "Burnout", "Retention"]}
              active={simTab}
              onChange={setSimTab}
            />
          }
        />
        <SimulationPanel tab={simTab} useSample={useSample} state={state} />
      </div>

      {/* Risk overview */}
      <div>
        <SectionHeader title="Things to watch" subtitle="Current risk factors your AI team is monitoring" />
        <RiskCards state={state} useSample={useSample} />
      </div>
    </div>
  );
}

// Kanban
function KanbanView({ items }: { items: typeof SAMPLE_PLAN_ITEMS }) {
  return (
    <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
      {PHASES.map((phase) => {
        const phaseItems = items.filter(
          (i) => i.phase.toLowerCase() === phase.toLowerCase()
        );
        const colors = {
          Now: "border-red-500/40",
          Next: "border-amber-500/40",
          Later: "border-emerald-500/40",
        };
        return (
          <div key={phase} className="space-y-3">
            <div className="flex items-center gap-2">
              <div
                className={cn(
                  "w-3 h-3 rounded-full",
                  phase === "Now"
                    ? "bg-red-500"
                    : phase === "Next"
                      ? "bg-amber-500"
                      : "bg-emerald-500"
                )}
              />
              <h3 className="text-sm font-semibold">{PHASE_LABELS[phase]}</h3>
              <Badge variant="muted">{phaseItems.length}</Badge>
            </div>
            {phaseItems.map((item, i) => (
              <motion.div
                key={i}
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: i * 0.05 }}
              >
                <Card className={cn("border-l-2", colors[phase])}>
                  <p className="text-sm font-medium">{item.concept}</p>
                  <p className="text-xs text-[var(--muted-foreground)] mt-1 leading-relaxed">
                    {item.action}
                  </p>
                  <Badge
                    variant={
                      item.priority === "high"
                        ? "danger"
                        : item.priority === "medium"
                          ? "warning"
                          : "muted"
                    }
                    className="mt-2"
                  >
                    {item.priority === "high" ? "Urgent" : item.priority === "medium" ? "Important" : "Maintain"}
                  </Badge>
                </Card>
              </motion.div>
            ))}
            {phaseItems.length === 0 && (
              <Card className="text-center py-6 opacity-50">
                <p className="text-xs text-[var(--muted-foreground)]">Nothing here yet</p>
              </Card>
            )}
          </div>
        );
      })}
    </div>
  );
}

// Timeline
function TimelineView({ items }: { items: typeof SAMPLE_PLAN_ITEMS }) {
  return (
    <div className="relative pl-8 space-y-4">
      <div className="absolute left-3 top-0 bottom-0 w-px bg-[var(--border)]" />
      {items.map((item, i) => (
        <motion.div
          key={i}
          initial={{ opacity: 0, x: -12 }}
          animate={{ opacity: 1, x: 0 }}
          transition={{ delay: i * 0.06 }}
          className="relative"
        >
          <div
            className={cn(
              "absolute left-[-22px] top-2 w-3 h-3 rounded-full border-2 border-[var(--card)]",
              item.phase === "now"
                ? "bg-red-500"
                : item.phase === "next"
                  ? "bg-amber-500"
                  : "bg-emerald-500"
            )}
          />
          <Card>
            <div className="flex items-center gap-2 mb-1">
              <Badge
                variant={
                  item.phase === "now"
                    ? "danger"
                    : item.phase === "next"
                      ? "warning"
                      : "success"
                }
              >
                {item.phase === "now" ? "Focus now" : item.phase === "next" ? "Coming up" : "Maintain"}
              </Badge>
              <span className="text-sm font-medium">{item.concept}</span>
            </div>
            <p className="text-xs text-[var(--muted-foreground)] leading-relaxed">
              {item.action}
            </p>
          </Card>
        </motion.div>
      ))}
    </div>
  );
}

// Simulation Panel
function SimulationPanel({
  tab,
  useSample,
  state,
}: {
  tab: string;
  useSample: boolean;
  state: LearnerState | null;
}) {
  const data = SAMPLE_FORECAST_DATA;

  const chartData =
    tab === "Score"
      ? data
      : tab === "Burnout"
        ? data.map((d) => ({
            ...d,
            planA: Math.max(0, 100 - d.planA),
            planB: Math.max(0, 100 - d.planB + 10),
            rest: 10,
          }))
        : data.map((d) => ({
            ...d,
            planA: Math.min(100, d.planA + 5),
            planB: Math.min(100, d.planB),
            rest: Math.max(0, d.rest - 5),
          }));

  const label =
    tab === "Score"
      ? "Expected Score (%)"
      : tab === "Burnout"
        ? "Burnout Risk (%)"
        : "Retention (%)";

  return (
    <Card>
      {!useSample && !state ? (
        <div className="text-center py-10">
          <Info className="w-8 h-8 mx-auto text-[var(--muted-foreground)] mb-3" />
          <p className="text-sm text-[var(--muted-foreground)]">
            Log some study activity first to unlock simulations
          </p>
        </div>
      ) : (
        <>
          <div className="flex items-center gap-2 mb-4">
            <h3 className="text-sm font-medium">{label}</h3>
            {useSample && <Badge variant="muted">Sample Data</Badge>}
          </div>
          <div className="h-64">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={chartData}>
                <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
                <XAxis
                  dataKey="day"
                  tick={{ fontSize: 11, fill: "var(--muted-foreground)" }}
                />
                <YAxis
                  tick={{ fontSize: 11, fill: "var(--muted-foreground)" }}
                  domain={[0, 100]}
                />
                <Tooltip
                  contentStyle={{
                    backgroundColor: "var(--card)",
                    border: "1px solid var(--border)",
                    borderRadius: "0.75rem",
                    fontSize: 12,
                  }}
                />
                <Legend wrapperStyle={{ fontSize: 11 }} />
                <Line
                  type="monotone"
                  dataKey="planA"
                  name="Spaced Practice"
                  stroke="#818cf8"
                  strokeWidth={2}
                  dot={false}
                />
                <Line
                  type="monotone"
                  dataKey="planB"
                  name="Intensive Review"
                  stroke="#f59e0b"
                  strokeWidth={2}
                  dot={false}
                />
                <Line
                  type="monotone"
                  dataKey="rest"
                  name="No Study (Rest)"
                  stroke="#ef4444"
                  strokeWidth={2}
                  strokeDasharray="5 5"
                  dot={false}
                />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </>
      )}
    </Card>
  );
}

// Risk Cards
function RiskCards({
  state,
  useSample,
}: {
  state: LearnerState | null;
  useSample: boolean;
}) {
  const risks = useSample
    ? [
        { type: "Burnout Risk", value: 0.15, icon: <Flame className="w-5 h-5" /> },
        { type: "Focus Drift", value: 0.08, icon: <TrendingUp className="w-5 h-5" /> },
        { type: "Forgetting Risk", value: 0.55, icon: <Brain className="w-5 h-5" /> },
      ]
    : state
      ? [
          {
            type: "Focus Drift",
            value:
              state.active_drift_signals.length > 0
                ? Math.max(...state.active_drift_signals.map((d) => d.severity))
                : 0,
            icon: <TrendingUp className="w-5 h-5" />,
          },
          {
            type: "Unusual Patterns",
            value:
              state.behavioral_anomalies.filter((a) => !a.resolved).length > 0
                ? Math.max(
                    ...state.behavioral_anomalies
                      .filter((a) => !a.resolved)
                      .map((a) => a.severity)
                  )
                : 0,
            icon: <AlertTriangle className="w-5 h-5" />,
          },
          {
            type: "Time Remaining",
            value:
              state.time_budget.hours_remaining_this_week /
              state.time_budget.total_hours_per_week,
            icon: <Calendar className="w-5 h-5" />,
          },
        ]
      : [];

  if (!risks.length) {
    return (
      <Card className="text-center py-8">
        <AlertTriangle className="w-8 h-8 mx-auto text-[var(--muted-foreground)] mb-3 opacity-50" />
        <p className="text-sm text-[var(--muted-foreground)]">
          No risk data yet. Your AI team will monitor risks once you start studying.
        </p>
      </Card>
    );
  }

  return (
    <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
      {risks.map((r) => (
        <Card key={r.type} className="flex items-center gap-4">
          <div
            className={cn(
              "flex items-center justify-center w-10 h-10 rounded-xl shrink-0",
              r.value >= 0.5
                ? "bg-red-500/15 text-red-400"
                : r.value >= 0.25
                  ? "bg-amber-500/15 text-amber-400"
                  : "bg-emerald-500/15 text-emerald-400"
            )}
          >
            {r.icon}
          </div>
          <div>
            <p className="text-xs text-[var(--muted-foreground)]">{r.type}</p>
            <p className="text-lg font-bold">{pct(r.value)}</p>
          </div>
        </Card>
      ))}
    </div>
  );
}

// Helper: build plan from real state
function buildPlanFromState(state: LearnerState | null) {
  if (!state) return [];
  const concepts = Object.values(state.concepts);
  const items: typeof SAMPLE_PLAN_ITEMS = [];

  concepts
    .filter((c) => c.bkt.p_know < 0.4)
    .sort((a, b) => a.bkt.p_know - b.bkt.p_know)
    .forEach((c) =>
      items.push({
        phase: "now",
        concept: c.display_name || c.concept_id,
        action: `Focus practice — you're at ${pct(c.bkt.p_know)}`,
        priority: "high",
      })
    );

  concepts
    .filter((c) => c.bkt.p_know >= 0.4 && c.bkt.p_know < 0.75)
    .forEach((c) =>
      items.push({
        phase: "next",
        concept: c.display_name || c.concept_id,
        action: `Keep building — you're at ${pct(c.bkt.p_know)}`,
        priority: "medium",
      })
    );

  concepts
    .filter((c) => c.bkt.p_know >= 0.75)
    .forEach((c) =>
      items.push({
        phase: "later",
        concept: c.display_name || c.concept_id,
        action: `Great work! Quick review to stay sharp`,
        priority: "low",
      })
    );

  return items;
}
