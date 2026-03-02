"use client";

import { useEffect, useState, useCallback } from "react";
import { motion, AnimatePresence } from "framer-motion";
import Link from "next/link";
import {
  Compass,
  Zap,
  Clock,
  Target,
  TrendingUp,
  ChevronDown,
  ChevronUp,
  Sparkles,
  AlertTriangle,
  BookOpen,
  Upload,
  Brain,
  ShieldCheck,
  BarChart3,
  Eye,
  MessageSquare,
  Timer,
  Flame,
  Repeat,
  Users,
} from "lucide-react";
import {
  Card,
  Badge,
  StatCard,
  SectionHeader,
  CardSkeleton,
  ErrorBanner,
  SampleDataBanner,
} from "@/components/ui";
import { cn, pct, formatDate, confidenceBadge } from "@/lib/utils";
import {
  getMyState,
  postEvent,
  type LearnerState,
  type NextBestAction,
} from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import { SAMPLE_AGENT_ACTIVITY, SAMPLE_CONCEPTS } from "@/lib/sample-data";
import { v4 as uuid } from "uuid";

// Map technical agent names to friendly descriptions
const AGENT_FRIENDLY: Record<string, { label: string; description: string; icon: React.ReactNode; color: string }> = {
  Diagnoser: { label: "Gap Finder", description: "Identifies what you need to work on", icon: <Target className="w-5 h-5" />, color: "text-rose-400" },
  Planner: { label: "Study Planner", description: "Builds your personalized study plan", icon: <BarChart3 className="w-5 h-5" />, color: "text-indigo-400" },
  Motivation: { label: "Motivation Coach", description: "Tracks your energy and engagement", icon: <Flame className="w-5 h-5" />, color: "text-amber-400" },
  "Drift Detector": { label: "Focus Monitor", description: "Notices when your learning drifts", icon: <Eye className="w-5 h-5" />, color: "text-sky-400" },
  "Decay Monitor": { label: "Memory Guard", description: "Flags topics you might forget", icon: <Brain className="w-5 h-5" />, color: "text-purple-400" },
  "RAG Agent": { label: "Research Helper", description: "Finds relevant study materials", icon: <BookOpen className="w-5 h-5" />, color: "text-teal-400" },
  "Debate Advocates": { label: "Strategy Team", description: "Proposes different study approaches", icon: <Users className="w-5 h-5" />, color: "text-orange-400" },
  "Debate Arbitrator": { label: "Decision Maker", description: "Picks the best strategy for you", icon: <ShieldCheck className="w-5 h-5" />, color: "text-emerald-400" },
  Evaluator: { label: "Progress Analyst", description: "Measures how well you're doing", icon: <BarChart3 className="w-5 h-5" />, color: "text-cyan-400" },
  Reflection: { label: "Learning Mirror", description: "Helps you reflect on progress", icon: <MessageSquare className="w-5 h-5" />, color: "text-pink-400" },
  "Time Optimizer": { label: "Schedule Optimizer", description: "Makes the most of your study time", icon: <Timer className="w-5 h-5" />, color: "text-lime-400" },
  "Generative Replay": { label: "Practice Generator", description: "Creates review exercises", icon: <Repeat className="w-5 h-5" />, color: "text-violet-400" },
  "Skill State": { label: "Knowledge Tracker", description: "Tracks what you know", icon: <Target className="w-5 h-5" />, color: "text-blue-400" },
  Behavior: { label: "Habit Analyst", description: "Understands your study patterns", icon: <TrendingUp className="w-5 h-5" />, color: "text-fuchsia-400" },
};

function getAgentFriendly(name: string) {
  return AGENT_FRIENDLY[name] || {
    label: name,
    description: "Part of your AI team",
    icon: <Sparkles className="w-5 h-5" />,
    color: "text-[var(--primary)]",
  };
}

export default function HomePage() {
  const { user } = useAuth();
  const firstName = user?.display_name?.split(" ")[0] || "there";

  const [state, setState] = useState<LearnerState | null>(null);
  const [nba, setNba] = useState<NextBestAction | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [useSample, setUseSample] = useState(false);

  const fetchData = useCallback(async () => {
    setLoading(true);
    setError(null);
    setUseSample(false);

    const stateRes = await getMyState();
    if (stateRes.error) {
      setError(stateRes.error);
      setUseSample(true);
      setLoading(false);
      return;
    }
    if (stateRes.data?.found && stateRes.data.state) {
      setState(stateRes.data.state);
    } else {
      setUseSample(true);
    }
    setLoading(false);
  }, []);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  const handleGetGuidance = async () => {
    setLoading(true);
    const res = await postEvent({
      event_id: uuid(),
      event_type: "self_report",
      data: { message: "Check-in from home" },
    });
    if (res.data) {
      setNba(res.data);
    } else if (res.error) {
      setError(res.error);
    }
    setLoading(false);
  };

  const concepts = state ? Object.values(state.concepts) : [];
  const avgMastery = concepts.length
    ? concepts.reduce((s, c) => s + c.bkt.p_know, 0) / concepts.length
    : 0;
  const sessionCount = state?.session_count ?? 0;
  const lastActive = state?.last_active ?? null;
  const motivation = state?.motivation;

  return (
    <div className="space-y-8 max-w-7xl mx-auto">
      {/* GPS Hero */}
      <div className="rounded-2xl border border-[var(--border)] bg-gradient-to-br from-indigo-500/10 via-[var(--card)] to-purple-500/10 p-6 sm:p-8">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-6">
          <div className="space-y-2">
            <div className="flex items-center gap-2 text-[var(--primary)]">
              <Compass className="w-5 h-5" />
              <span className="text-xs font-semibold uppercase tracking-widest">Your Learning GPS</span>
            </div>
            <h1 className="text-2xl sm:text-3xl font-bold tracking-tight">
              Welcome back, {firstName}
            </h1>
            <p className="text-sm text-[var(--muted-foreground)] max-w-lg">
              Your AI team of {Object.keys(AGENT_FRIENDLY).length} specialized agents is ready to guide your next study session.
            </p>
          </div>
          <div className="flex flex-col sm:flex-row gap-3 shrink-0">
            <button
              onClick={handleGetGuidance}
              disabled={loading}
              className="flex items-center justify-center gap-2 px-6 py-3 rounded-xl bg-[var(--primary)] text-[var(--primary-foreground)] text-sm font-semibold hover:opacity-90 transition-opacity disabled:opacity-50 shadow-lg shadow-[var(--primary)]/20"
            >
              <Zap className="w-4 h-4" />
              Get Today&apos;s Guidance
            </button>
            <div className="flex gap-3">
              <Link
                href="/session"
                className="flex items-center justify-center gap-2 px-4 py-3 rounded-xl border border-[var(--border)] bg-[var(--card)] text-sm font-medium hover:bg-[var(--muted)] transition-colors"
              >
                <BookOpen className="w-4 h-4" />
                Log Activity
              </Link>
              <Link
                href="/my-data"
                className="flex items-center justify-center gap-2 px-4 py-3 rounded-xl border border-[var(--border)] bg-[var(--card)] text-sm font-medium hover:bg-[var(--muted)] transition-colors"
              >
                <Upload className="w-4 h-4" />
                Upload Work
              </Link>
            </div>
          </div>
        </div>
      </div>

      {error && <ErrorBanner message={error} onRetry={fetchData} />}
      {useSample && !loading && <SampleDataBanner />}

      {/* Stats Row */}
      {loading ? (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
          {[1, 2, 3, 4].map((i) => <CardSkeleton key={i} />)}
        </div>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
          <StatCard
            label="Overall Progress"
            value={useSample ? "54%" : pct(avgMastery)}
            sublabel={useSample ? "Across 5 topics" : `Across ${concepts.length} topics`}
            icon={<Target className="w-5 h-5" />}
            trend="up"
          />
          <StatCard
            label="Study Sessions"
            value={useSample ? 12 : sessionCount}
            sublabel="Completed so far"
            icon={<BookOpen className="w-5 h-5" />}
          />
          <StatCard
            label="Last Active"
            value={useSample ? "2h ago" : (lastActive ? formatDate(lastActive) : "—")}
            icon={<Clock className="w-5 h-5" />}
          />
          <StatCard
            label="Motivation"
            value={useSample ? "Medium" : (motivation?.level ?? "—")}
            sublabel={
              useSample
                ? "Trending up"
                : motivation
                  ? `Trend: ${motivation.trend > 0 ? "+" : ""}${motivation.trend.toFixed(2)}`
                  : undefined
            }
            icon={<TrendingUp className="w-5 h-5" />}
            trend={
              useSample
                ? "up"
                : motivation
                  ? motivation.trend > 0 ? "up" : motivation.trend < 0 ? "down" : "neutral"
                  : undefined
            }
          />
        </div>
      )}

      {/* Today's Guidance + AI Team Activity */}
      <div className="grid grid-cols-1 lg:grid-cols-5 gap-6">
        <div className="lg:col-span-2 space-y-4">
          <SectionHeader title="Today's Guidance" subtitle="Your AI-powered next step" />
          <GuidanceCard nba={nba} loading={loading} useSample={useSample} />
        </div>
        <div className="lg:col-span-3 space-y-4">
          <SectionHeader title="How your AI team helped" subtitle="Behind the scenes" />
          <AgentInsights nba={nba} useSample={useSample} />
        </div>
      </div>

      {/* Your AI Team */}
      <div>
        <SectionHeader
          title="Your AI Team"
          subtitle={`${Object.keys(AGENT_FRIENDLY).length} specialized agents working for you`}
        />
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
          {Object.entries(AGENT_FRIENDLY).slice(0, 8).map(([key, agent]) => (
            <Card key={key} className="flex items-start gap-3 !p-4">
              <div className={cn("shrink-0 mt-0.5", agent.color)}>
                {agent.icon}
              </div>
              <div className="min-w-0">
                <p className="text-sm font-medium">{agent.label}</p>
                <p className="text-xs text-[var(--muted-foreground)] mt-0.5 leading-relaxed">{agent.description}</p>
              </div>
            </Card>
          ))}
        </div>
      </div>

      {/* Your Strengths & Gaps */}
      <div>
        <SectionHeader title="Your strengths & gaps" subtitle="How well you know each topic" />
        <ConceptGrid concepts={concepts} useSample={useSample} />
      </div>
    </div>
  );
}

// Guidance Card
function GuidanceCard({
  nba,
  loading,
  useSample,
}: {
  nba: NextBestAction | null;
  loading: boolean;
  useSample: boolean;
}) {
  if (loading) return <CardSkeleton />;

  if (!nba && !useSample) {
    return (
      <Card className="text-center py-10">
        <Compass className="w-10 h-10 mx-auto text-[var(--primary)] mb-3 opacity-60" />
        <p className="text-sm font-medium mb-1">Ready when you are</p>
        <p className="text-xs text-[var(--muted-foreground)] max-w-xs mx-auto">
          Click &ldquo;Get Today&apos;s Guidance&rdquo; above and your AI team will analyze your progress and suggest what to study next.
        </p>
      </Card>
    );
  }

  const action = nba?.recommended_action ?? "Review Quadratic Equations using spaced practice";
  const rationale =
    nba?.rationale ??
    "This topic is at risk of being forgotten. Spaced practice now will help you remember it long-term.";
  const confidence = nba?.confidence ?? 0.75;
  const gain = nba?.expected_learning_gain ?? 0.18;
  const risks = nba?.risk_assessment ?? { burnout: 0.15, drift: 0.08, forgetting: 0.55 };

  const riskLabels: Record<string, string> = {
    burnout: "Burnout Risk",
    drift: "Focus Risk",
    forgetting: "Forgetting Risk",
  };

  return (
    <Card gradient className="space-y-4">
      <div className="flex items-start justify-between">
        <Badge variant={confidence >= 0.7 ? "success" : "warning"}>
          {pct(confidence)} confident
        </Badge>
        {!nba && <Badge variant="muted">Sample</Badge>}
      </div>
      <p className="text-base font-semibold leading-snug">{action}</p>
      <p className="text-xs text-[var(--muted-foreground)] leading-relaxed">
        {rationale}
      </p>
      <div className="flex flex-wrap gap-3 pt-1">
        <MiniStat label="Expected Gain" value={pct(gain)} variant="success" />
        {Object.entries(risks).map(([k, v]) => (
          <MiniStat
            key={k}
            label={riskLabels[k] || k}
            value={pct(v)}
            variant={v >= 0.5 ? "danger" : v >= 0.3 ? "warning" : "success"}
          />
        ))}
      </div>
    </Card>
  );
}

function MiniStat({
  label,
  value,
  variant,
}: {
  label: string;
  value: string;
  variant: "success" | "warning" | "danger";
}) {
  const colors = {
    success: "text-emerald-400",
    warning: "text-amber-400",
    danger: "text-red-400",
  };
  return (
    <div className="text-center">
      <p className={cn("text-sm font-bold", colors[variant])}>{value}</p>
      <p className="text-[10px] text-[var(--muted-foreground)]">{label}</p>
    </div>
  );
}

// Agent Insights
function AgentInsights({
  nba,
  useSample,
}: {
  nba: NextBestAction | null;
  useSample: boolean;
}) {
  const [expanded, setExpanded] = useState<string | null>(null);

  const agents = nba?.debug_trace
    ? Object.entries(nba.debug_trace).map(([key, val]) => ({
        agent: key,
        status: "ran" as const,
        summary: typeof val === "string" ? val : JSON.stringify(val).slice(0, 120),
        confidence: nba.confidence,
      }))
    : useSample
      ? SAMPLE_AGENT_ACTIVITY
      : [];

  if (!agents.length) {
    return (
      <Card className="text-center py-10">
        <Sparkles className="w-8 h-8 mx-auto text-[var(--muted-foreground)] mb-3" />
        <p className="text-sm text-[var(--muted-foreground)]">
          Your AI team hasn&apos;t run yet. Get guidance to see what they find.
        </p>
      </Card>
    );
  }

  return (
    <div className="space-y-2">
      <AnimatePresence>
        {agents.map((a, i) => {
          const friendly = getAgentFriendly(a.agent);
          return (
            <motion.div
              key={a.agent}
              initial={{ opacity: 0, x: 12 }}
              animate={{ opacity: 1, x: 0 }}
              transition={{ delay: i * 0.05 }}
            >
              <Card
                className={cn(
                  "cursor-pointer hover:border-[var(--primary)]/30 transition-colors",
                  expanded === a.agent && "border-[var(--primary)]/40"
                )}
                onClick={() => setExpanded(expanded === a.agent ? null : a.agent)}
              >
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-3 min-w-0">
                    <div className={cn("shrink-0", friendly.color)}>
                      {friendly.icon}
                    </div>
                    <div className="min-w-0">
                      <span className="text-sm font-medium truncate block">
                        {friendly.label}
                      </span>
                      <span className="text-[10px] text-[var(--muted-foreground)]">
                        {friendly.description}
                      </span>
                    </div>
                    <Badge variant={a.status === "ran" ? "success" : "warning"}>
                      {a.status === "ran" ? "Active" : "Standby"}
                    </Badge>
                  </div>
                  {expanded === a.agent ? (
                    <ChevronUp className="w-4 h-4 text-[var(--muted-foreground)]" />
                  ) : (
                    <ChevronDown className="w-4 h-4 text-[var(--muted-foreground)]" />
                  )}
                </div>
                <AnimatePresence>
                  {expanded === a.agent && (
                    <motion.div
                      initial={{ height: 0, opacity: 0 }}
                      animate={{ height: "auto", opacity: 1 }}
                      exit={{ height: 0, opacity: 0 }}
                      className="overflow-hidden"
                    >
                      <div className="pt-3 mt-3 border-t border-[var(--border)] space-y-2">
                        <p className="text-xs text-[var(--muted-foreground)] leading-relaxed">
                          {a.summary}
                        </p>
                        <div className="flex items-center gap-2">
                          <span className="text-[10px] text-[var(--muted-foreground)]">
                            Confidence:
                          </span>
                          <Badge className={confidenceBadge(a.confidence)}>
                            {pct(a.confidence)}
                          </Badge>
                        </div>
                      </div>
                    </motion.div>
                  )}
                </AnimatePresence>
              </Card>
            </motion.div>
          );
        })}
      </AnimatePresence>
    </div>
  );
}

// Concept Grid
function ConceptGrid({
  concepts,
  useSample,
}: {
  concepts: { concept_id: string; display_name?: string; bkt?: { p_know: number }; forgetting_score?: number }[];
  useSample: boolean;
}) {
  const items = useSample
    ? SAMPLE_CONCEPTS.map((c) => ({
        id: c.concept_id,
        name: c.display_name,
        mastery: c.mastery,
        forgetting: c.forgetting,
      }))
    : concepts.map((c) => ({
        id: c.concept_id,
        name: c.display_name || c.concept_id,
        mastery: c.bkt?.p_know ?? 0,
        forgetting: c.forgetting_score ?? 0,
      }));

  if (!items.length) {
    return (
      <Card className="text-center py-12">
        <Target className="w-10 h-10 mx-auto text-[var(--muted-foreground)] mb-4 opacity-50" />
        <p className="text-sm font-medium mb-1">No topics tracked yet</p>
        <p className="text-xs text-[var(--muted-foreground)] max-w-sm mx-auto">
          Once you log some study activity, your AI team will track your progress on each topic here.
        </p>
        <Link
          href="/session"
          className="inline-flex items-center gap-2 mt-4 px-4 py-2 rounded-xl bg-[var(--primary)] text-[var(--primary-foreground)] text-sm font-medium hover:opacity-90 transition-opacity"
        >
          <BookOpen className="w-4 h-4" />
          Log your first activity
        </Link>
      </Card>
    );
  }

  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
      {items.map((c) => (
        <Card key={c.id} className="space-y-3">
          <div className="flex items-center justify-between">
            <span className="text-sm font-medium truncate">{c.name}</span>
            {c.forgetting >= 0.5 && (
              <Badge variant="warning" className="shrink-0 ml-2">
                <AlertTriangle className="w-3 h-3 mr-1" />
                Needs review
              </Badge>
            )}
          </div>
          <div>
            <div className="flex justify-between text-[10px] text-[var(--muted-foreground)] mb-1">
              <span>How well you know this</span>
              <span>{pct(c.mastery)}</span>
            </div>
            <div className="h-2 rounded-full bg-[var(--muted)] overflow-hidden">
              <motion.div
                initial={{ width: 0 }}
                animate={{ width: `${c.mastery * 100}%` }}
                transition={{ duration: 0.6, ease: "easeOut" }}
                className={cn(
                  "h-full rounded-full",
                  c.mastery >= 0.7
                    ? "bg-emerald-500"
                    : c.mastery >= 0.4
                      ? "bg-amber-500"
                      : "bg-red-500"
                )}
              />
            </div>
          </div>
          <div>
            <div className="flex justify-between text-[10px] text-[var(--muted-foreground)] mb-1">
              <span>Review urgency</span>
              <span>{pct(c.forgetting)}</span>
            </div>
            <div className="h-2 rounded-full bg-[var(--muted)] overflow-hidden">
              <motion.div
                initial={{ width: 0 }}
                animate={{ width: `${c.forgetting * 100}%` }}
                transition={{ duration: 0.6, ease: "easeOut" }}
                className={cn(
                  "h-full rounded-full",
                  c.forgetting >= 0.5
                    ? "bg-red-500"
                    : c.forgetting >= 0.25
                      ? "bg-amber-500"
                      : "bg-emerald-500"
                )}
              />
            </div>
          </div>
        </Card>
      ))}
    </div>
  );
}
