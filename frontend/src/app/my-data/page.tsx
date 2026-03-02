"use client";

import { useState, useEffect, useCallback } from "react";
import {
  Upload,
  FileText,
  Trash2,
  Plus,
  Clock,
  BookOpen,
  BarChart3,
  Loader2,
  FileUp,
  X,
  CheckCircle2,
} from "lucide-react";
import { Card, Badge, SectionHeader, Tabs, ErrorBanner } from "@/components/ui";
import { cn, formatDate } from "@/lib/utils";
import * as api from "@/lib/api/client";
import type { UserEvent, UserUpload } from "@/lib/api/types";

export default function MyDataPage() {
  const [tab, setTab] = useState("activity");
  const [events, setEvents] = useState<UserEvent[]>([]);
  const [uploads, setUploads] = useState<UserUpload[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Event form
  const [showEventForm, setShowEventForm] = useState(false);
  const [eventConcept, setEventConcept] = useState("");
  const [eventScore, setEventScore] = useState("");
  const [eventTime, setEventTime] = useState("");
  const [eventType, setEventType] = useState("quiz_result");
  const [eventNotes, setEventNotes] = useState("");
  const [submittingEvent, setSubmittingEvent] = useState(false);

  // Upload
  const [dragging, setDragging] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [uploadSuccess, setUploadSuccess] = useState<string | null>(null);

  const loadData = useCallback(async () => {
    setLoading(true);
    setError(null);
    const [evtRes, uplRes] = await Promise.all([
      api.getUserEvents(200),
      api.getUserUploads(),
    ]);
    if (evtRes.data) setEvents(evtRes.data.events);
    if (uplRes.data) setUploads(uplRes.data.uploads);
    if (evtRes.error && uplRes.error) setError(evtRes.error);
    setLoading(false);
  }, []);

  useEffect(() => {
    loadData();
  }, [loadData]);

  async function handleAddEvent(e: React.FormEvent) {
    e.preventDefault();
    setSubmittingEvent(true);
    const { data, error: err } = await api.createUserEvent({
      concept: eventConcept,
      score: eventScore ? parseFloat(eventScore) : null,
      time_spent_minutes: eventTime ? parseFloat(eventTime) : null,
      event_type: eventType,
      notes: eventNotes,
      source: "manual",
    });
    setSubmittingEvent(false);
    if (data) {
      setEvents((prev) => [data, ...prev]);
      setShowEventForm(false);
      setEventConcept("");
      setEventScore("");
      setEventTime("");
      setEventNotes("");
    } else if (err) {
      setError(err);
    }
  }

  async function handleFileDrop(files: FileList | null) {
    if (!files?.length) return;
    setUploading(true);
    setUploadSuccess(null);
    setError(null);
    for (const file of Array.from(files)) {
      const { data, error: err } = await api.uploadFile(file);
      if (data) {
        setUploads((prev) => [data, ...prev]);
        setUploadSuccess(`Uploaded: ${file.name}`);
      } else if (err) {
        setError(err);
      }
    }
    setUploading(false);
    setTimeout(() => setUploadSuccess(null), 3000);
  }

  function formatFileSize(bytes: number) {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  }

  return (
    <div className="space-y-6">
      <SectionHeader
        title="Add Study Data"
        subtitle="Log what you've studied or upload files — your AI team uses this to help you"
      />

      {error && <ErrorBanner message={error} onRetry={loadData} />}

      <Tabs tabs={["activity", "files"]} active={tab} onChange={setTab} />

      {/* Activity Tab */}
      {tab === "activity" && (
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <p className="text-sm text-[var(--muted-foreground)]">
              {events.length} event{events.length !== 1 ? "s" : ""} logged
            </p>
            <button
              onClick={() => setShowEventForm(!showEventForm)}
              className="flex items-center gap-2 px-4 py-2 rounded-xl bg-[var(--primary)] text-[var(--primary-foreground)] text-sm font-medium hover:opacity-90 transition-colors"
            >
              {showEventForm ? <X className="w-4 h-4" /> : <Plus className="w-4 h-4" />}
              {showEventForm ? "Cancel" : "Log Activity"}
            </button>
          </div>

          {/* Event form */}
          {showEventForm && (
            <Card className="space-y-4">
              <form onSubmit={handleAddEvent} className="space-y-4">
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                  <div>
                    <label className="block text-sm font-medium mb-1.5">
                      Topic *
                    </label>
                    <input
                      type="text"
                      value={eventConcept}
                      onChange={(e) => setEventConcept(e.target.value)}
                      required
                      placeholder="e.g. Linear Algebra"
                      className="w-full px-3 py-2 rounded-lg border border-[var(--border)] bg-[var(--background)] text-sm focus:outline-none focus:ring-2 focus:ring-[var(--primary)]"
                    />
                  </div>
                  <div>
                    <label className="block text-sm font-medium mb-1.5">
                      What did you do?
                    </label>
                    <select
                      value={eventType}
                      onChange={(e) => setEventType(e.target.value)}
                      className="w-full px-3 py-2 rounded-lg border border-[var(--border)] bg-[var(--background)] text-sm focus:outline-none focus:ring-2 focus:ring-[var(--primary)]"
                    >
                      <option value="quiz_result">I took a quiz</option>
                      <option value="time_on_task">I studied for a while</option>
                      <option value="self_report">How I'm feeling</option>
                      <option value="content_interaction">I read / watched something</option>
                      <option value="custom">Something else</option>
                    </select>
                  </div>
                  <div>
                    <label className="block text-sm font-medium mb-1.5">
                      Score (0-1)
                    </label>
                    <input
                      type="number"
                      step="0.01"
                      min="0"
                      max="1"
                      value={eventScore}
                      onChange={(e) => setEventScore(e.target.value)}
                      placeholder="0.85"
                      className="w-full px-3 py-2 rounded-lg border border-[var(--border)] bg-[var(--background)] text-sm focus:outline-none focus:ring-2 focus:ring-[var(--primary)]"
                    />
                  </div>
                  <div>
                    <label className="block text-sm font-medium mb-1.5">
                      Time Spent (min)
                    </label>
                    <input
                      type="number"
                      step="1"
                      min="0"
                      value={eventTime}
                      onChange={(e) => setEventTime(e.target.value)}
                      placeholder="30"
                      className="w-full px-3 py-2 rounded-lg border border-[var(--border)] bg-[var(--background)] text-sm focus:outline-none focus:ring-2 focus:ring-[var(--primary)]"
                    />
                  </div>
                </div>
                <div>
                  <label className="block text-sm font-medium mb-1.5">
                    Notes
                  </label>
                  <textarea
                    value={eventNotes}
                    onChange={(e) => setEventNotes(e.target.value)}
                    placeholder="Any thoughts on how it went..."
                    rows={2}
                    className="w-full px-3 py-2 rounded-lg border border-[var(--border)] bg-[var(--background)] text-sm focus:outline-none focus:ring-2 focus:ring-[var(--primary)] resize-none"
                  />
                </div>
                <button
                  type="submit"
                  disabled={submittingEvent}
                  className="flex items-center gap-2 px-4 py-2 rounded-xl bg-[var(--primary)] text-[var(--primary-foreground)] text-sm font-medium hover:opacity-90 disabled:opacity-50 transition-colors"
                >
                  {submittingEvent && (
                    <Loader2 className="w-4 h-4 animate-spin" />
                  )}
                  Save
                </button>
              </form>
            </Card>
          )}

          {/* Events list */}
          {loading ? (
            <div className="flex items-center gap-2 justify-center py-12 text-[var(--muted-foreground)]">
              <Loader2 className="w-4 h-4 animate-spin" />
              Loading...
            </div>
          ) : events.length === 0 ? (
            <Card className="flex flex-col items-center py-12 text-center">
              <BookOpen className="w-10 h-10 text-[var(--muted-foreground)] mb-3" />
              <p className="font-medium">No activity logged yet</p>
              <p className="text-sm text-[var(--muted-foreground)] mt-1">
                Log what you studied so your AI team can give you better recommendations.
              </p>
            </Card>
          ) : (
            <div className="space-y-2">
              {events.map((evt) => (
                <Card key={evt.id} className="flex items-start gap-4 !p-4">
                  <div
                    className={cn(
                      "w-9 h-9 rounded-lg flex items-center justify-center shrink-0",
                      evt.event_type === "quiz_result"
                        ? "bg-indigo-500/15 text-indigo-400"
                        : evt.event_type === "time_on_task"
                        ? "bg-amber-500/15 text-amber-400"
                        : "bg-emerald-500/15 text-emerald-400"
                    )}
                  >
                    {evt.event_type === "quiz_result" ? (
                      <BarChart3 className="w-4 h-4" />
                    ) : evt.event_type === "time_on_task" ? (
                      <Clock className="w-4 h-4" />
                    ) : (
                      <BookOpen className="w-4 h-4" />
                    )}
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="font-medium text-sm">{evt.concept || "—"}</span>
                      <Badge variant="muted">{evt.event_type === "quiz_result" ? "Quiz" : evt.event_type === "time_on_task" ? "Study time" : evt.event_type === "self_report" ? "Check-in" : evt.event_type === "content_interaction" ? "Reading" : evt.event_type}</Badge>
                      {evt.score !== null && (
                        <Badge variant={evt.score >= 0.7 ? "success" : evt.score >= 0.4 ? "warning" : "danger"}>
                          {Math.round(evt.score * 100)}%
                        </Badge>
                      )}
                    </div>
                    {evt.notes && (
                      <p className="text-xs text-[var(--muted-foreground)] mt-1 truncate">
                        {evt.notes}
                      </p>
                    )}
                    <p className="text-[11px] text-[var(--muted-foreground)] mt-1">
                      {formatDate(evt.created_at)}
                      {evt.time_spent_minutes
                        ? ` · ${evt.time_spent_minutes} min`
                        : ""}
                    </p>
                  </div>
                </Card>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Files Tab */}
      {tab === "files" && (
        <div className="space-y-4">
          {/* Upload dropzone */}
          <Card
            className={cn(
              "relative border-2 border-dashed transition-colors cursor-pointer",
              dragging
                ? "border-[var(--primary)] bg-[var(--primary)]/5"
                : "border-[var(--border)] hover:border-[var(--muted-foreground)]"
            )}
            onDragOver={(e) => {
              e.preventDefault();
              setDragging(true);
            }}
            onDragLeave={() => setDragging(false)}
            onDrop={(e) => {
              e.preventDefault();
              setDragging(false);
              handleFileDrop(e.dataTransfer.files);
            }}
            onClick={() => {
              const input = document.createElement("input");
              input.type = "file";
              input.multiple = true;
              input.accept = ".csv,.json,.jsonl,.txt,.pdf";
              input.onchange = () => handleFileDrop(input.files);
              input.click();
            }}
          >
            <div className="flex flex-col items-center py-8 text-center">
              {uploading ? (
                <Loader2 className="w-8 h-8 text-[var(--primary)] animate-spin mb-3" />
              ) : (
                <FileUp className="w-8 h-8 text-[var(--muted-foreground)] mb-3" />
              )}
              <p className="font-medium text-sm">
                {uploading
                  ? "Uploading..."
                  : "Drop files here or click to browse"}
              </p>
              <p className="text-xs text-[var(--muted-foreground)] mt-1">
                CSV, JSON, JSONL, TXT, PDF — max 10 MB
              </p>
            </div>
          </Card>

          {uploadSuccess && (
            <div className="flex items-center gap-2 px-4 py-2 rounded-xl border border-emerald-500/30 bg-emerald-500/10 text-sm text-emerald-400">
              <CheckCircle2 className="w-4 h-4" />
              {uploadSuccess}
            </div>
          )}

          {/* Uploads list */}
          {loading ? (
            <div className="flex items-center gap-2 justify-center py-12 text-[var(--muted-foreground)]">
              <Loader2 className="w-4 h-4 animate-spin" />
              Loading...
            </div>
          ) : uploads.length === 0 ? (
            <Card className="flex flex-col items-center py-12 text-center">
              <Upload className="w-10 h-10 text-[var(--muted-foreground)] mb-3" />
              <p className="font-medium">No files uploaded yet</p>
              <p className="text-sm text-[var(--muted-foreground)] mt-1">
                Upload assignments, notes, or study materials to give your AI team more context.
              </p>
            </Card>
          ) : (
            <div className="space-y-2">
              {uploads.map((upl) => (
                <Card key={upl.id} className="flex items-center gap-4 !p-4">
                  <div className="w-9 h-9 rounded-lg bg-sky-500/15 text-sky-400 flex items-center justify-center shrink-0">
                    <FileText className="w-4 h-4" />
                  </div>
                  <div className="flex-1 min-w-0">
                    <p className="font-medium text-sm truncate">
                      {upl.file_name}
                    </p>
                    <p className="text-[11px] text-[var(--muted-foreground)]">
                      {formatFileSize(upl.file_size)} · {upl.file_type} ·{" "}
                      {formatDate(upl.created_at)}
                    </p>
                  </div>
                </Card>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
