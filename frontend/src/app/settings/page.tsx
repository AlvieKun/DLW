"use client";

import { useState, useEffect } from "react";
import {
  User,
  Mail,
  BookOpen,
  Target,
  Clock,
  Shield,
  Save,
  Loader2,
  CheckCircle2,
} from "lucide-react";
import { Card, SectionHeader, Badge } from "@/components/ui";
import { useAuth } from "@/lib/auth-context";
import * as api from "@/lib/api/client";
import type { UserProfile } from "@/lib/api/types";

export default function SettingsPage() {
  const { user } = useAuth();
  const [profile, setProfile] = useState<UserProfile | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    async function load() {
      const { data } = await api.getProfile();
      if (data) setProfile(data);
      setLoading(false);
    }
    load();
  }, []);

  async function handleSave() {
    if (!profile) return;
    setSaving(true);
    await api.updateProfile({
      preferences: profile.preferences as Record<string, unknown> | undefined,
      weekly_schedule: profile.weekly_schedule as Record<string, unknown> | undefined,
    });
    setSaving(false);
    setSaved(true);
    setTimeout(() => setSaved(false), 2000);
  }

  const subjects = Array.isArray(profile?.subjects) ? profile.subjects : [];
  const goals = (profile?.learning_goals as Record<string, unknown>)?.goals;
  const goalList = Array.isArray(goals) ? goals : [];
  const schedule = profile?.weekly_schedule as Record<string, unknown> | null;

  return (
    <div className="space-y-6 max-w-2xl">
      <SectionHeader
        title="Settings"
        subtitle="Manage your account and learning preferences"
      />

      {/* Account Info */}
      <Card className="space-y-4">
        <h3 className="font-semibold flex items-center gap-2">
          <User className="w-4 h-4 text-[var(--primary)]" />
          Account
        </h3>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <div>
            <label className="text-xs text-[var(--muted-foreground)]">
              Display Name
            </label>
            <p className="text-sm font-medium mt-0.5">
              {user?.display_name || "—"}
            </p>
          </div>
          <div>
            <label className="text-xs text-[var(--muted-foreground)]">
              Email
            </label>
            <div className="flex items-center gap-2 mt-0.5">
              <Mail className="w-3.5 h-3.5 text-[var(--muted-foreground)]" />
              <p className="text-sm font-medium">{user?.email || "—"}</p>
            </div>
          </div>
          <div>
            <label className="text-xs text-[var(--muted-foreground)]">
              Member Since
            </label>
            <p className="text-sm font-medium mt-0.5">
              {user?.created_at
                ? new Date(user.created_at).toLocaleDateString("en-US", {
                    month: "long",
                    day: "numeric",
                    year: "numeric",
                  })
                : "—"}
            </p>
          </div>
          <div>
            <label className="text-xs text-[var(--muted-foreground)]">
              Onboarded
            </label>
            <div className="mt-0.5">
              <Badge variant={user?.onboarded ? "success" : "warning"}>
                {user?.onboarded ? "Complete" : "Pending"}
              </Badge>
            </div>
          </div>
        </div>
      </Card>

      {/* Learning Profile */}
      {!loading && profile && (
        <Card className="space-y-4">
          <h3 className="font-semibold flex items-center gap-2">
            <BookOpen className="w-4 h-4 text-[var(--primary)]" />
            Learning Profile
          </h3>

          {subjects.length > 0 && (
            <div>
              <label className="text-xs text-[var(--muted-foreground)] block mb-1.5">
                Subjects
              </label>
              <div className="flex flex-wrap gap-2">
                {subjects.map((s: Record<string, unknown>, i: number) => (
                  <Badge key={i} variant="info">
                    {String(s.label || s.id || "Unknown")}
                  </Badge>
                ))}
              </div>
            </div>
          )}

          {goalList.length > 0 && (
            <div>
              <label className="text-xs text-[var(--muted-foreground)] block mb-1.5">
                Goals
              </label>
              <div className="flex flex-wrap gap-2">
                {goalList.map((g: unknown, i: number) => {
                  const goal = g as Record<string, unknown>;
                  return (
                    <Badge key={i} variant="default">
                      <Target className="w-3 h-3 mr-1" />
                      {String(goal.label || goal.id || "Goal")}
                    </Badge>
                  );
                })}
              </div>
            </div>
          )}

          {schedule && (
            <div>
              <label className="text-xs text-[var(--muted-foreground)] block mb-1.5">
                Schedule
              </label>
              <div className="flex items-center gap-2">
                <Clock className="w-4 h-4 text-[var(--muted-foreground)]" />
                <span className="text-sm">
                  {String(schedule.intensity || "Custom")} —{" "}
                  {schedule.hours_per_week
                    ? `${schedule.hours_per_week} hrs/week`
                    : "Flexible"}
                </span>
              </div>
            </div>
          )}
        </Card>
      )}

      {/* Security */}
      <Card className="space-y-3">
        <h3 className="font-semibold flex items-center gap-2">
          <Shield className="w-4 h-4 text-[var(--primary)]" />
          Security
        </h3>
        <p className="text-sm text-[var(--muted-foreground)]">
          Session authentication via HttpOnly cookies. Your password is hashed
          with bcrypt and never stored in plaintext.
        </p>
      </Card>

      {/* Save */}
      {profile && (
        <div className="flex items-center gap-3">
          <button
            onClick={handleSave}
            disabled={saving}
            className="flex items-center gap-2 px-5 py-2.5 rounded-xl bg-[var(--primary)] text-[var(--primary-foreground)] text-sm font-medium hover:opacity-90 disabled:opacity-50 transition-colors"
          >
            {saving ? (
              <Loader2 className="w-4 h-4 animate-spin" />
            ) : (
              <Save className="w-4 h-4" />
            )}
            {saving ? "Saving..." : "Save Changes"}
          </button>
          {saved && (
            <span className="flex items-center gap-1 text-sm text-emerald-400">
              <CheckCircle2 className="w-4 h-4" />
              Saved
            </span>
          )}
        </div>
      )}
    </div>
  );
}
