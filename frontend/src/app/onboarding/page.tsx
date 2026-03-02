"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import {
  Brain,
  BookOpen,
  Target,
  Clock,
  ChevronRight,
  ChevronLeft,
  Loader2,
  Check,
  Sparkles,
} from "lucide-react";
import { useAuth } from "@/lib/auth-context";
import * as api from "@/lib/api/client";

const SUBJECTS = [
  { id: "math", label: "Mathematics", emoji: "📐" },
  { id: "science", label: "Science", emoji: "🔬" },
  { id: "cs", label: "Computer Science", emoji: "💻" },
  { id: "english", label: "English / Writing", emoji: "✍️" },
  { id: "history", label: "History", emoji: "📜" },
  { id: "languages", label: "Foreign Languages", emoji: "🌍" },
  { id: "art", label: "Art & Design", emoji: "🎨" },
  { id: "business", label: "Business", emoji: "📊" },
];

const GOALS = [
  { id: "master", label: "Master core concepts", icon: Target },
  { id: "exam", label: "Prepare for an exam", icon: BookOpen },
  { id: "skills", label: "Build practical skills", icon: Sparkles },
  { id: "explore", label: "Explore new topics", icon: Brain },
];

const SCHEDULES = [
  { id: "light", label: "Light", desc: "2-3 hours/week", hours: 2.5 },
  { id: "moderate", label: "Moderate", desc: "5-8 hours/week", hours: 6.5 },
  { id: "intensive", label: "Intensive", desc: "10-15 hours/week", hours: 12.5 },
  { id: "full", label: "Full-time", desc: "20+ hours/week", hours: 25 },
];

const STEPS = [
  { title: "Subjects", subtitle: "What do you want to learn?" },
  { title: "Goals", subtitle: "What are you aiming for?" },
  { title: "Schedule", subtitle: "How much time can you invest?" },
  { title: "Ready!", subtitle: "Let's personalize your experience" },
];

export default function OnboardingPage() {
  const [step, setStep] = useState(0);
  const [selectedSubjects, setSelectedSubjects] = useState<string[]>([]);
  const [selectedGoals, setSelectedGoals] = useState<string[]>([]);
  const [selectedSchedule, setSelectedSchedule] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const { refresh } = useAuth();
  const router = useRouter();

  function toggleSubject(id: string) {
    setSelectedSubjects((prev) =>
      prev.includes(id) ? prev.filter((s) => s !== id) : [...prev, id]
    );
  }

  function toggleGoal(id: string) {
    setSelectedGoals((prev) =>
      prev.includes(id) ? prev.filter((g) => g !== id) : [...prev, id]
    );
  }

  function canProceed() {
    if (step === 0) return selectedSubjects.length > 0;
    if (step === 1) return selectedGoals.length > 0;
    if (step === 2) return selectedSchedule !== null;
    return true;
  }

  async function handleComplete() {
    setSubmitting(true);
    const schedule = SCHEDULES.find((s) => s.id === selectedSchedule);
    await api.completeOnboarding({
      subjects: selectedSubjects.map((id) => ({
        id,
        label: SUBJECTS.find((s) => s.id === id)?.label || id,
      })),
      learning_goals: {
        goals: selectedGoals.map((id) => ({
          id,
          label: GOALS.find((g) => g.id === id)?.label || id,
        })),
      },
      weekly_schedule: {
        intensity: selectedSchedule,
        hours_per_week: schedule?.hours || 5,
      },
    });
    await refresh();
    setSubmitting(false);
    router.replace("/");
  }

  return (
    <div className="min-h-screen flex items-center justify-center p-4 bg-[var(--background)]">
      <div className="w-full max-w-lg">
        {/* Progress */}
        <div className="flex items-center gap-2 mb-8">
          {STEPS.map((_, i) => (
            <div
              key={i}
              className={`flex-1 h-1.5 rounded-full transition-colors ${
                i <= step ? "bg-[var(--primary)]" : "bg-[var(--muted)]"
              }`}
            />
          ))}
        </div>

        {/* Step header */}
        <div className="text-center mb-8">
          <h1 className="text-2xl font-bold">{STEPS[step].title}</h1>
          <p className="text-sm text-[var(--muted-foreground)] mt-1">
            {STEPS[step].subtitle}
          </p>
        </div>

        {/* Step content */}
        <div className="rounded-2xl border border-[var(--border)] bg-[var(--card)] p-6">
          {/* Step 0: Subjects */}
          {step === 0 && (
            <div className="grid grid-cols-2 gap-3">
              {SUBJECTS.map((subject) => {
                const selected = selectedSubjects.includes(subject.id);
                return (
                  <button
                    key={subject.id}
                    onClick={() => toggleSubject(subject.id)}
                    className={`flex items-center gap-3 px-4 py-3 rounded-xl border text-sm font-medium transition-all text-left ${
                      selected
                        ? "border-[var(--primary)] bg-[var(--primary)]/10 text-[var(--primary)]"
                        : "border-[var(--border)] hover:border-[var(--muted-foreground)] text-[var(--foreground)]"
                    }`}
                  >
                    <span className="text-lg">{subject.emoji}</span>
                    <span className="flex-1">{subject.label}</span>
                    {selected && <Check className="w-4 h-4" />}
                  </button>
                );
              })}
            </div>
          )}

          {/* Step 1: Goals */}
          {step === 1 && (
            <div className="space-y-3">
              {GOALS.map((goal) => {
                const selected = selectedGoals.includes(goal.id);
                const Icon = goal.icon;
                return (
                  <button
                    key={goal.id}
                    onClick={() => toggleGoal(goal.id)}
                    className={`flex items-center gap-4 w-full px-4 py-3.5 rounded-xl border text-sm font-medium transition-all text-left ${
                      selected
                        ? "border-[var(--primary)] bg-[var(--primary)]/10 text-[var(--primary)]"
                        : "border-[var(--border)] hover:border-[var(--muted-foreground)] text-[var(--foreground)]"
                    }`}
                  >
                    <div
                      className={`w-10 h-10 rounded-xl flex items-center justify-center ${
                        selected
                          ? "bg-[var(--primary)]/20"
                          : "bg-[var(--muted)]"
                      }`}
                    >
                      <Icon className="w-5 h-5" />
                    </div>
                    <span className="flex-1">{goal.label}</span>
                    {selected && <Check className="w-4 h-4" />}
                  </button>
                );
              })}
            </div>
          )}

          {/* Step 2: Schedule */}
          {step === 2 && (
            <div className="space-y-3">
              {SCHEDULES.map((sched) => {
                const selected = selectedSchedule === sched.id;
                return (
                  <button
                    key={sched.id}
                    onClick={() => setSelectedSchedule(sched.id)}
                    className={`flex items-center gap-4 w-full px-4 py-3.5 rounded-xl border text-sm font-medium transition-all text-left ${
                      selected
                        ? "border-[var(--primary)] bg-[var(--primary)]/10 text-[var(--primary)]"
                        : "border-[var(--border)] hover:border-[var(--muted-foreground)] text-[var(--foreground)]"
                    }`}
                  >
                    <div
                      className={`w-10 h-10 rounded-xl flex items-center justify-center ${
                        selected
                          ? "bg-[var(--primary)]/20"
                          : "bg-[var(--muted)]"
                      }`}
                    >
                      <Clock className="w-5 h-5" />
                    </div>
                    <div className="flex-1">
                      <p className="font-medium">{sched.label}</p>
                      <p className="text-xs text-[var(--muted-foreground)]">
                        {sched.desc}
                      </p>
                    </div>
                    {selected && <Check className="w-4 h-4" />}
                  </button>
                );
              })}
            </div>
          )}

          {/* Step 3: Summary */}
          {step === 3 && (
            <div className="space-y-4">
              <div className="flex items-center justify-center mb-2">
                <div className="w-16 h-16 rounded-2xl bg-gradient-to-br from-indigo-500 to-purple-600 flex items-center justify-center shadow-lg shadow-indigo-500/25">
                  <Sparkles className="w-8 h-8 text-white" />
                </div>
              </div>
              <p className="text-center text-sm text-[var(--muted-foreground)]">
                We&apos;ll personalize your learning experience based on:
              </p>
              <div className="space-y-2 text-sm">
                <div className="flex items-center gap-2 px-3 py-2 rounded-lg bg-[var(--muted)]">
                  <BookOpen className="w-4 h-4 text-[var(--primary)]" />
                  <span>
                    {selectedSubjects.length} subject
                    {selectedSubjects.length !== 1 ? "s" : ""}:{" "}
                    {selectedSubjects
                      .map(
                        (id) => SUBJECTS.find((s) => s.id === id)?.label || id
                      )
                      .join(", ")}
                  </span>
                </div>
                <div className="flex items-center gap-2 px-3 py-2 rounded-lg bg-[var(--muted)]">
                  <Target className="w-4 h-4 text-[var(--primary)]" />
                  <span>
                    {selectedGoals
                      .map(
                        (id) => GOALS.find((g) => g.id === id)?.label || id
                      )
                      .join(", ")}
                  </span>
                </div>
                <div className="flex items-center gap-2 px-3 py-2 rounded-lg bg-[var(--muted)]">
                  <Clock className="w-4 h-4 text-[var(--primary)]" />
                  <span>
                    {SCHEDULES.find((s) => s.id === selectedSchedule)?.desc ||
                      "Custom schedule"}
                  </span>
                </div>
              </div>
            </div>
          )}
        </div>

        {/* Navigation */}
        <div className="flex items-center justify-between mt-6">
          <button
            onClick={() => setStep(Math.max(0, step - 1))}
            disabled={step === 0}
            className="flex items-center gap-1 px-4 py-2 rounded-xl text-sm font-medium text-[var(--muted-foreground)] hover:text-[var(--foreground)] disabled:opacity-30 transition-colors"
          >
            <ChevronLeft className="w-4 h-4" />
            Back
          </button>

          {step < 3 ? (
            <button
              onClick={() => setStep(step + 1)}
              disabled={!canProceed()}
              className="flex items-center gap-1 px-6 py-2.5 rounded-xl bg-[var(--primary)] text-[var(--primary-foreground)] text-sm font-medium hover:opacity-90 disabled:opacity-50 transition-all"
            >
              Continue
              <ChevronRight className="w-4 h-4" />
            </button>
          ) : (
            <button
              onClick={handleComplete}
              disabled={submitting}
              className="flex items-center gap-2 px-6 py-2.5 rounded-xl bg-gradient-to-r from-indigo-500 to-purple-600 text-white text-sm font-medium hover:opacity-90 disabled:opacity-50 transition-all shadow-lg shadow-indigo-500/25"
            >
              {submitting && <Loader2 className="w-4 h-4 animate-spin" />}
              {submitting ? "Setting up..." : "Start Learning"}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
