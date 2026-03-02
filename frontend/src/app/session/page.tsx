"use client";

import { useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  Send,
  Upload,
  Clock,
  BookOpen,
  CheckCircle2,
  AlertCircle,
  ChevronDown,
  ChevronUp,
  Loader2,
  Sparkles,
} from "lucide-react";
import {
  Card,
  Badge,
  SectionHeader,
  ErrorBanner,
  CardSkeleton,
} from "@/components/ui";
import { cn, pct, formatDate, confidenceBadge } from "@/lib/utils";
import { postEvent, type NextBestAction, type LearnerEventType } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import { v4 as uuid } from "uuid";

// Human-friendly event type labels
const EVENT_LABELS: Record<string, string> = {
  quiz_result: "I took a quiz",
  time_on_task: "I studied for a while",
  self_report: "How I'm feeling",
  content_interaction: "I read / watched something",
  motivation_signal: "My motivation level",
  sentiment_signal: "My mood about studying",
  custom: "Something else",
};

interface SessionEntry {
  id: string;
  timestamp: string;
  concept: string;
  eventType: LearnerEventType;
  score?: number;
  timeSpent?: number;
  notes?: string;
  result: NextBestAction | null;
  error: string | null;
  loading: boolean;
}

export default function SessionPage() {
  const { user } = useAuth();

  const [concept, setConcept] = useState("");
  const [eventType, setEventType] = useState<LearnerEventType>("quiz_result");
  const [score, setScore] = useState("");
  const [timeSpent, setTimeSpent] = useState("");
  const [notes, setNotes] = useState("");
  const [entries, setEntries] = useState<SessionEntry[]>([]);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setSubmitting(true);

    const entryId = uuid();
    const entry: SessionEntry = {
      id: entryId,
      timestamp: new Date().toISOString(),
      concept: concept || "general",
      eventType,
      score: score ? parseFloat(score) : undefined,
      timeSpent: timeSpent ? parseInt(timeSpent) : undefined,
      notes: notes || undefined,
      result: null,
      error: null,
      loading: true,
    };

    setEntries((prev) => [entry, ...prev]);

    const res = await postEvent({
      event_id: entryId,
      event_type: eventType,
      concept_id: concept || undefined,
      data: {
        ...(score ? { score: parseFloat(score) } : {}),
        ...(timeSpent ? { time_spent_minutes: parseInt(timeSpent) } : {}),
        ...(notes ? { notes } : {}),
      },
    });

    setEntries((prev) =>
      prev.map((e) =>
        e.id === entryId
          ? { ...e, result: res.data, error: res.error, loading: false }
          : e
      )
    );

    setSubmitting(false);
    setConcept("");
    setScore("");
    setTimeSpent("");
    setNotes("");
  };

  return (
    <div className="space-y-6 max-w-5xl mx-auto">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Study Session</h1>
        <p className="text-sm text-[var(--muted-foreground)] mt-1">
          Tell us what you studied and get personalized feedback from your AI team
        </p>
      </div>

      {error && <ErrorBanner message={error} />}

      <div className="grid grid-cols-1 lg:grid-cols-5 gap-6">
        {/* Input Form */}
        <div className="lg:col-span-2 space-y-4">
          <SectionHeader title="Log study activity" subtitle="What did you work on?" />
          <Card>
            <form onSubmit={handleSubmit} className="space-y-4">
              {/* What did you do? */}
              <div>
                <label className="block text-xs font-medium text-[var(--muted-foreground)] mb-1">
                  What did you do?
                </label>
                <select
                  value={eventType}
                  onChange={(e) => setEventType(e.target.value as LearnerEventType)}
                  className="w-full bg-[var(--muted)] border border-[var(--border)] rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-[var(--ring)]"
                >
                  {Object.entries(EVENT_LABELS).map(([value, label]) => (
                    <option key={value} value={value}>{label}</option>
                  ))}
                </select>
              </div>

              {/* Topic */}
              <div>
                <label className="block text-xs font-medium text-[var(--muted-foreground)] mb-1">
                  Topic (optional)
                </label>
                <input
                  type="text"
                  value={concept}
                  onChange={(e) => setConcept(e.target.value)}
                  placeholder="e.g., Quadratic Equations"
                  className="w-full bg-[var(--muted)] border border-[var(--border)] rounded-lg px-3 py-2 text-sm placeholder:text-[var(--muted-foreground)]/50 focus:outline-none focus:ring-2 focus:ring-[var(--ring)]"
                />
              </div>

              {/* Score */}
              <div>
                <label className="block text-xs font-medium text-[var(--muted-foreground)] mb-1">
                  Score (0–100%, optional)
                </label>
                <input
                  type="number"
                  min="0"
                  max="1"
                  step="0.01"
                  value={score}
                  onChange={(e) => setScore(e.target.value)}
                  placeholder="0.75"
                  className="w-full bg-[var(--muted)] border border-[var(--border)] rounded-lg px-3 py-2 text-sm placeholder:text-[var(--muted-foreground)]/50 focus:outline-none focus:ring-2 focus:ring-[var(--ring)]"
                />
              </div>

              {/* Time Spent */}
              <div>
                <label className="block text-xs font-medium text-[var(--muted-foreground)] mb-1">
                  How long did you study? (minutes)
                </label>
                <input
                  type="number"
                  min="0"
                  value={timeSpent}
                  onChange={(e) => setTimeSpent(e.target.value)}
                  placeholder="25"
                  className="w-full bg-[var(--muted)] border border-[var(--border)] rounded-lg px-3 py-2 text-sm placeholder:text-[var(--muted-foreground)]/50 focus:outline-none focus:ring-2 focus:ring-[var(--ring)]"
                />
              </div>

              {/* Notes */}
              <div>
                <label className="block text-xs font-medium text-[var(--muted-foreground)] mb-1">
                  Notes (optional)
                </label>
                <textarea
                  value={notes}
                  onChange={(e) => setNotes(e.target.value)}
                  rows={2}
                  placeholder="e.g., Struggled with factoring..."
                  className="w-full bg-[var(--muted)] border border-[var(--border)] rounded-lg px-3 py-2 text-sm placeholder:text-[var(--muted-foreground)]/50 focus:outline-none focus:ring-2 focus:ring-[var(--ring)] resize-none"
                />
              </div>

              <button
                type="submit"
                disabled={submitting}
                className="w-full flex items-center justify-center gap-2 px-4 py-2.5 rounded-xl bg-[var(--primary)] text-[var(--primary-foreground)] text-sm font-medium hover:opacity-90 transition-opacity disabled:opacity-50"
              >
                {submitting ? (
                  <Loader2 className="w-4 h-4 animate-spin" />
                ) : (
                  <Send className="w-4 h-4" />
                )}
                Get AI Feedback
              </button>
            </form>
          </Card>

          {/* Upload hint */}
          <Card className="border-dashed">
            <div className="text-center py-4 space-y-2">
              <Upload className="w-6 h-6 mx-auto text-[var(--muted-foreground)]" />
              <p className="text-sm font-medium">Have a file to upload?</p>
              <p className="text-xs text-[var(--muted-foreground)]">
                Head to <a href="/my-data" className="text-[var(--primary)] hover:underline">Add Study Data</a> to upload assignments, notes, or screenshots.
              </p>
            </div>
          </Card>
        </div>

        {/* Results Timeline */}
        <div className="lg:col-span-3 space-y-4">
          <SectionHeader
            title="AI Feedback"
            subtitle="What your AI team recommends after each entry"
          />

          {entries.length === 0 && (
            <Card className="text-center py-16">
              <Sparkles className="w-10 h-10 mx-auto text-[var(--muted-foreground)] mb-4 opacity-50" />
              <p className="text-sm font-medium mb-1">No activity logged yet</p>
              <p className="text-xs text-[var(--muted-foreground)] max-w-sm mx-auto">
                Use the form to tell us what you studied. Your AI team will analyze it and give you personalized recommendations.
              </p>
            </Card>
          )}

          <div className="space-y-3">
            <AnimatePresence>
              {entries.map((entry) => (
                <SessionEntryCard key={entry.id} entry={entry} />
              ))}
            </AnimatePresence>
          </div>
        </div>
      </div>
    </div>
  );
}

// Session Entry Card
function SessionEntryCard({ entry }: { entry: SessionEntry }) {
  const [expanded, setExpanded] = useState(false);

  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -12 }}
    >
      <Card
        className={cn(
          "cursor-pointer hover:border-[var(--primary)]/30 transition-colors",
          entry.error && "border-red-500/30"
        )}
        onClick={() => setExpanded(!expanded)}
      >
        {/* Header */}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3 min-w-0">
            {entry.loading ? (
              <Loader2 className="w-4 h-4 animate-spin text-[var(--primary)]" />
            ) : entry.error ? (
              <AlertCircle className="w-4 h-4 text-red-400" />
            ) : (
              <CheckCircle2 className="w-4 h-4 text-emerald-400" />
            )}
            <div className="min-w-0">
              <span className="text-sm font-medium truncate block">
                {entry.concept}
              </span>
              <span className="text-[10px] text-[var(--muted-foreground)]">
                {EVENT_LABELS[entry.eventType] || entry.eventType} · {formatDate(entry.timestamp)}
              </span>
            </div>
          </div>
          <div className="flex items-center gap-2">
            {entry.score !== undefined && (
              <Badge variant={entry.score >= 0.7 ? "success" : entry.score >= 0.4 ? "warning" : "danger"}>
                {pct(entry.score)}
              </Badge>
            )}
            {entry.timeSpent !== undefined && (
              <div className="flex items-center gap-1 text-[10px] text-[var(--muted-foreground)]">
                <Clock className="w-3 h-3" />
                {entry.timeSpent}m
              </div>
            )}
            {expanded ? (
              <ChevronUp className="w-4 h-4 text-[var(--muted-foreground)]" />
            ) : (
              <ChevronDown className="w-4 h-4 text-[var(--muted-foreground)]" />
            )}
          </div>
        </div>

        {/* Expanded content */}
        <AnimatePresence>
          {expanded && (
            <motion.div
              initial={{ height: 0, opacity: 0 }}
              animate={{ height: "auto", opacity: 1 }}
              exit={{ height: 0, opacity: 0 }}
              className="overflow-hidden"
            >
              <div className="pt-3 mt-3 border-t border-[var(--border)] space-y-3">
                {entry.loading && <CardSkeleton />}

                {entry.error && (
                  <div className="text-xs text-red-400 bg-red-500/10 rounded-lg p-3">
                    {entry.error}
                  </div>
                )}

                {entry.result && (
                  <div className="space-y-3">
                    {/* Recommendation */}
                    <div>
                      <p className="text-[10px] font-medium text-[var(--muted-foreground)] mb-1 uppercase tracking-wider">
                        What to do next
                      </p>
                      <p className="text-sm font-medium">
                        {entry.result.recommended_action}
                      </p>
                    </div>

                    {/* Why */}
                    <div className="bg-[var(--muted)] rounded-xl p-3">
                      <p className="text-[10px] font-medium text-[var(--muted-foreground)] mb-1 uppercase tracking-wider">
                        Why this recommendation
                      </p>
                      <p className="text-xs text-[var(--muted-foreground)] leading-relaxed">
                        {entry.result.rationale}
                      </p>
                    </div>

                    {/* Metrics */}
                    <div className="flex flex-wrap gap-3">
                      <Badge className={confidenceBadge(entry.result.confidence)}>
                        {pct(entry.result.confidence)} confident
                      </Badge>
                      <Badge variant="info">
                        +{pct(entry.result.expected_learning_gain)} expected gain
                      </Badge>
                      {Object.entries(entry.result.risk_assessment).map(
                        ([k, v]) => (
                          <Badge
                            key={k}
                            variant={v >= 0.5 ? "danger" : v >= 0.3 ? "warning" : "success"}
                          >
                            {k}: {pct(v)}
                          </Badge>
                        )
                      )}
                    </div>

                    {/* Citations */}
                    {entry.result.citations.length > 0 && (
                      <div>
                        <p className="text-[10px] font-medium text-[var(--muted-foreground)] mb-1 uppercase tracking-wider">
                          Supporting evidence
                        </p>
                        <div className="flex flex-wrap gap-1">
                          {entry.result.citations.map((c, i) => (
                            <Badge key={i} variant="muted">
                              {c}
                            </Badge>
                          ))}
                        </div>
                      </div>
                    )}

                    {/* Debug trace - hidden behind details */}
                    {Object.keys(entry.result.debug_trace).length > 0 && (
                      <details className="group">
                        <summary className="text-[10px] font-medium text-[var(--muted-foreground)] cursor-pointer hover:text-[var(--foreground)] uppercase tracking-wider">
                          Technical details ▸
                        </summary>
                        <pre className="mt-2 text-[10px] bg-[var(--muted)] rounded-lg p-3 overflow-x-auto text-[var(--muted-foreground)]">
                          {JSON.stringify(entry.result.debug_trace, null, 2)}
                        </pre>
                      </details>
                    )}
                  </div>
                )}

                {entry.notes && (
                  <div className="text-xs text-[var(--muted-foreground)] italic">
                    Your note: {entry.notes}
                  </div>
                )}
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </Card>
    </motion.div>
  );
}
