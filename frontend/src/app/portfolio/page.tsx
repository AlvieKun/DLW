"use client";

import { useState, useEffect, useCallback } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  Search,
  FolderOpen,
  FileText,
  Calendar,
  Tag,
  ChevronDown,
  ChevronUp,
  Database,
  BookOpen,
} from "lucide-react";
import Link from "next/link";
import {
  Card,
  Badge,
  SectionHeader,
  ErrorBanner,
  SampleDataBanner,
  CardSkeleton,
  Tabs,
} from "@/components/ui";
import { cn, formatDate } from "@/lib/utils";
import { getMyPortfolio, type PortfolioEntry } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";

const LOCAL_KEY = "ln_portfolio_local";

interface LocalEntry {
  id: string;
  timestamp: string;
  concept: string;
  type: string;
  content: string;
}

function loadLocalEntries(): LocalEntry[] {
  if (typeof window === "undefined") return [];
  try {
    return JSON.parse(localStorage.getItem(LOCAL_KEY) || "[]");
  } catch {
    return [];
  }
}

function saveLocalEntries(entries: LocalEntry[]) {
  localStorage.setItem(LOCAL_KEY, JSON.stringify(entries));
}

// Human-friendly type labels
const TYPE_LABELS: Record<string, string> = {
  reflection: "Reflection",
  justification: "Justification",
  auditor_prompt: "Review Prompt",
  note: "Note",
  entry: "Entry",
};

export default function PortfolioPage() {
  const { user } = useAuth();

  const [backendEntries, setBackendEntries] = useState<PortfolioEntry[]>([]);
  const [localEntries, setLocalEntries] = useState<LocalEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [searchTerm, setSearchTerm] = useState("");
  const [activeTab, setActiveTab] = useState("All");
  const [showAddForm, setShowAddForm] = useState(false);

  const [newConcept, setNewConcept] = useState("");
  const [newType, setNewType] = useState("reflection");
  const [newContent, setNewContent] = useState("");

  useEffect(() => {
    setLocalEntries(loadLocalEntries());
  }, []);

  const fetchPortfolio = useCallback(async () => {
    setLoading(true);
    setError(null);
    const res = await getMyPortfolio();
    if (res.error) {
      setError(res.error);
    } else if (res.data) {
      setBackendEntries(res.data.entries);
    }
    setLoading(false);
  }, []);

  useEffect(() => {
    fetchPortfolio();
  }, [fetchPortfolio]);

  const handleAddLocal = (e: React.FormEvent) => {
    e.preventDefault();
    const entry: LocalEntry = {
      id: crypto.randomUUID(),
      timestamp: new Date().toISOString(),
      concept: newConcept || "general",
      type: newType,
      content: newContent,
    };
    const updated = [entry, ...localEntries];
    setLocalEntries(updated);
    saveLocalEntries(updated);
    setNewConcept("");
    setNewContent("");
    setShowAddForm(false);
  };

  const allBackend = backendEntries.map((e, i) => ({
    id: `b-${i}`,
    timestamp: (e.timestamp as string) || "",
    concept: (e.concept_id as string) || (e.concept as string) || "—",
    type: (e.entry_type as string) || (e.type as string) || "entry",
    content: (e.summary as string) || (e.content as string) || JSON.stringify(e),
    source: "backend" as const,
  }));

  const allLocal = localEntries.map((e) => ({
    ...e,
    source: "local" as const,
  }));

  let combined = [...allBackend, ...allLocal];

  if (activeTab === "From AI") combined = combined.filter((e) => e.source === "backend");
  if (activeTab === "My Notes") combined = combined.filter((e) => e.source === "local");

  if (searchTerm) {
    const q = searchTerm.toLowerCase();
    combined = combined.filter(
      (e) =>
        e.concept.toLowerCase().includes(q) ||
        e.content.toLowerCase().includes(q) ||
        e.type.toLowerCase().includes(q)
    );
  }

  return (
    <div className="space-y-6 max-w-5xl mx-auto">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">
            Learning Journal
          </h1>
          <p className="text-sm text-[var(--muted-foreground)] mt-1">
            Your reflections, AI-generated insights, and study notes
          </p>
        </div>
        <button
          onClick={() => setShowAddForm(!showAddForm)}
          className="px-4 py-2 rounded-xl bg-[var(--primary)] text-[var(--primary-foreground)] text-sm font-medium hover:opacity-90 transition-opacity"
        >
          + Add Entry
        </button>
      </div>

      {error && <ErrorBanner message={error} onRetry={fetchPortfolio} />}

      {/* Add form */}
      <AnimatePresence>
        {showAddForm && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            className="overflow-hidden"
          >
            <Card>
              <SectionHeader
                title="New journal entry"
                subtitle="Write a reflection or note"
              />
              <form onSubmit={handleAddLocal} className="space-y-3">
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                  <div>
                    <label className="block text-xs font-medium text-[var(--muted-foreground)] mb-1">
                      Topic
                    </label>
                    <input
                      type="text"
                      value={newConcept}
                      onChange={(e) => setNewConcept(e.target.value)}
                      placeholder="e.g., Quadratic Equations"
                      className="w-full bg-[var(--muted)] border border-[var(--border)] rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-[var(--ring)]"
                    />
                  </div>
                  <div>
                    <label className="block text-xs font-medium text-[var(--muted-foreground)] mb-1">
                      Type
                    </label>
                    <select
                      value={newType}
                      onChange={(e) => setNewType(e.target.value)}
                      className="w-full bg-[var(--muted)] border border-[var(--border)] rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-[var(--ring)]"
                    >
                      <option value="reflection">Reflection</option>
                      <option value="justification">Justification</option>
                      <option value="note">Note</option>
                    </select>
                  </div>
                </div>
                <div>
                  <label className="block text-xs font-medium text-[var(--muted-foreground)] mb-1">
                    What&apos;s on your mind?
                  </label>
                  <textarea
                    value={newContent}
                    onChange={(e) => setNewContent(e.target.value)}
                    rows={3}
                    required
                    placeholder="Write your thoughts, what you learned, or what confused you..."
                    className="w-full bg-[var(--muted)] border border-[var(--border)] rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-[var(--ring)] resize-none"
                  />
                </div>
                <button
                  type="submit"
                  className="px-4 py-2 rounded-xl bg-[var(--primary)] text-[var(--primary-foreground)] text-sm font-medium hover:opacity-90"
                >
                  Save Entry
                </button>
              </form>
            </Card>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Search + tabs */}
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3">
        <div className="relative w-full sm:w-72">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-[var(--muted-foreground)]" />
          <input
            type="text"
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
            placeholder="Search topics, notes..."
            className="w-full bg-[var(--muted)] border border-[var(--border)] rounded-lg pl-9 pr-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-[var(--ring)]"
          />
        </div>
        <Tabs
          tabs={["All", "From AI", "My Notes"]}
          active={activeTab}
          onChange={setActiveTab}
        />
      </div>

      {/* Entries */}
      {loading ? (
        <div className="space-y-3">
          {[1, 2, 3].map((i) => (
            <CardSkeleton key={i} />
          ))}
        </div>
      ) : combined.length === 0 ? (
        <Card className="text-center py-16">
          <FolderOpen className="w-10 h-10 mx-auto text-[var(--muted-foreground)] mb-4 opacity-50" />
          <p className="text-sm font-medium mb-1">Your journal is empty</p>
          <p className="text-xs text-[var(--muted-foreground)] max-w-sm mx-auto">
            Add your own reflections above, or log study activity to generate AI insights automatically.
          </p>
          <Link
            href="/session"
            className="inline-flex items-center gap-2 mt-4 px-4 py-2 rounded-xl bg-[var(--primary)] text-[var(--primary-foreground)] text-sm font-medium hover:opacity-90 transition-opacity"
          >
            <BookOpen className="w-4 h-4" />
            Log study activity
          </Link>
        </Card>
      ) : (
        <div className="space-y-3">
          <AnimatePresence>
            {combined.map((entry) => (
              <PortfolioEntryCard key={entry.id} entry={entry} />
            ))}
          </AnimatePresence>
        </div>
      )}
    </div>
  );
}

// Entry Card
function PortfolioEntryCard({
  entry,
}: {
  entry: {
    id: string;
    timestamp: string;
    concept: string;
    type: string;
    content: string;
    source: "backend" | "local";
  };
}) {
  const [expanded, setExpanded] = useState(false);

  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0 }}
    >
      <Card
        className="cursor-pointer hover:border-[var(--primary)]/30 transition-colors"
        onClick={() => setExpanded(!expanded)}
      >
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3 min-w-0">
            <FileText className="w-4 h-4 text-[var(--muted-foreground)] shrink-0" />
            <div className="min-w-0">
              <div className="flex items-center gap-2">
                <span className="text-sm font-medium truncate">
                  {entry.concept}
                </span>
                <Badge
                  variant={entry.source === "backend" ? "info" : "muted"}
                >
                  {entry.source === "backend" ? "AI-generated" : "Your note"}
                </Badge>
              </div>
              <div className="flex items-center gap-3 text-[10px] text-[var(--muted-foreground)] mt-0.5">
                <span className="flex items-center gap-1">
                  <Tag className="w-3 h-3" />
                  {TYPE_LABELS[entry.type] || entry.type}
                </span>
                {entry.timestamp && (
                  <span className="flex items-center gap-1">
                    <Calendar className="w-3 h-3" />
                    {formatDate(entry.timestamp)}
                  </span>
                )}
              </div>
            </div>
          </div>
          {expanded ? (
            <ChevronUp className="w-4 h-4 text-[var(--muted-foreground)]" />
          ) : (
            <ChevronDown className="w-4 h-4 text-[var(--muted-foreground)]" />
          )}
        </div>

        <AnimatePresence>
          {expanded && (
            <motion.div
              initial={{ height: 0, opacity: 0 }}
              animate={{ height: "auto", opacity: 1 }}
              exit={{ height: 0, opacity: 0 }}
              className="overflow-hidden"
            >
              <div className="pt-3 mt-3 border-t border-[var(--border)]">
                <p className="text-xs text-[var(--muted-foreground)] leading-relaxed whitespace-pre-wrap">
                  {entry.content}
                </p>
                {entry.source === "local" && (
                  <div className="flex items-center gap-1 mt-2 text-[10px] text-[var(--muted-foreground)]">
                    <Database className="w-3 h-3" />
                    Saved locally in your browser
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
