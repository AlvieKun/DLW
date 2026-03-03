"use client";

import { useState, useEffect } from "react";
import { motion } from "framer-motion";
import {
  Server,
  CheckCircle2,
  XCircle,
  RefreshCw,
  Trash2,
  Copy,
  Wifi,
  WifiOff,
  Clock,
  Terminal,
  Cpu,
  ShieldCheck,
  AlertTriangle,
} from "lucide-react";
import {
  Card,
  Badge,
  SectionHeader,
  ErrorBanner,
} from "@/components/ui";
import { cn } from "@/lib/utils";
import {
  getHealth,
  getLearners,
  getCalibration,
  getApiLogs,
  clearApiLogs,
  getAgentsStatus,
  type HealthResponse,
} from "@/lib/api";
import type { AgentStatus, AgentSystemSummary } from "@/lib/api/types";

interface PingResult {
  endpoint: string;
  method: string;
  status: number;
  ok: boolean;
  durationMs: number;
  response: unknown;
  error?: string;
}

export default function DevToolsPage() {
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [healthError, setHealthError] = useState<string | null>(null);
  const [pingResults, setPingResults] = useState<PingResult[]>([]);
  const [pinging, setPinging] = useState(false);
  const [lastCallJson, setLastCallJson] = useState<string | null>(null);
  const [logs, setLogs] = useState(getApiLogs());
  const [agents, setAgents] = useState<AgentStatus[]>([]);
  const [agentSummary, setAgentSummary] = useState<AgentSystemSummary | null>(null);
  const [agentsLoading, setAgentsLoading] = useState(false);
  const backendUrl =
    process.env.NEXT_PUBLIC_API_BASE_URL || "http://127.0.0.1:8000";

  // Health check + agents on mount
  useEffect(() => {
    checkHealth();
    loadAgents();
  }, []);

  const loadAgents = async () => {
    setAgentsLoading(true);
    const res = await getAgentsStatus();
    if (res.data) {
      setAgents(res.data.agents);
      setAgentSummary(res.data.summary);
    }
    setAgentsLoading(false);
  };

  const checkHealth = async () => {
    setHealthError(null);
    const res = await getHealth();
    if (res.data) {
      setHealth(res.data);
    } else {
      setHealthError(res.error || "Unreachable");
    }
    setLogs(getApiLogs());
  };

  const pingEndpoints = async () => {
    setPinging(true);
    const results: PingResult[] = [];

    // Health
    const t0 = Date.now();
    const h = await getHealth();
    results.push({
      endpoint: "/health",
      method: "GET",
      status: h.status,
      ok: !h.error,
      durationMs: Date.now() - t0,
      response: h.data,
      error: h.error || undefined,
    });

    // Learners
    const t1 = Date.now();
    const l = await getLearners();
    results.push({
      endpoint: "/api/v1/learners",
      method: "GET",
      status: l.status,
      ok: !l.error,
      durationMs: Date.now() - t1,
      response: l.data,
      error: l.error || undefined,
    });

    // Calibration
    const t2 = Date.now();
    const c = await getCalibration();
    results.push({
      endpoint: "/api/v1/calibration",
      method: "GET",
      status: c.status,
      ok: !c.error,
      durationMs: Date.now() - t2,
      response: c.data,
      error: c.error || undefined,
    });

    setPingResults(results);
    setLastCallJson(JSON.stringify(results, null, 2));
    setLogs(getApiLogs());
    setPinging(false);
  };

  const copyJson = () => {
    if (lastCallJson) {
      navigator.clipboard.writeText(lastCallJson);
    }
  };

  return (
    <div className="space-y-6 max-w-5xl mx-auto">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Developer Tools</h1>
        <p className="text-sm text-[var(--muted-foreground)] mt-1">
          Backend diagnostics, endpoint testing, and AI agent status
        </p>
      </div>

      {/* Connection status */}
      <Card gradient className="flex items-center justify-between">
        <div className="flex items-center gap-4">
          <div
            className={cn(
              "flex items-center justify-center w-12 h-12 rounded-xl",
              health
                ? "bg-emerald-500/15 text-emerald-400"
                : "bg-red-500/15 text-red-400"
            )}
          >
            {health ? (
              <Wifi className="w-6 h-6" />
            ) : (
              <WifiOff className="w-6 h-6" />
            )}
          </div>
          <div>
            <p className="text-sm font-medium">
              {health ? "Backend Connected" : "Backend Unreachable"}
            </p>
            <p className="text-xs text-[var(--muted-foreground)] mt-0.5">
              {backendUrl}
            </p>
            {health && (
              <div className="flex items-center gap-2 mt-1">
                <Badge variant="success">v{health.version}</Badge>
                <Badge variant="muted">{health.environment}</Badge>
              </div>
            )}
            {healthError && (
              <p className="text-xs text-red-400 mt-1">{healthError}</p>
            )}
          </div>
        </div>
        <button
          onClick={checkHealth}
          className="flex items-center gap-2 px-4 py-2 rounded-xl bg-[var(--muted)] hover:bg-[var(--border)] transition-colors text-sm font-medium"
        >
          <RefreshCw className="w-4 h-4" />
          Refresh
        </button>
      </Card>

      {/* Ping endpoints */}
      <div>
        <SectionHeader
          title="Ping Endpoints"
          subtitle="Test all API endpoints"
          action={
            <button
              onClick={pingEndpoints}
              disabled={pinging}
              className="flex items-center gap-2 px-4 py-2 rounded-xl bg-[var(--primary)] text-[var(--primary-foreground)] text-sm font-medium hover:opacity-90 transition-opacity disabled:opacity-50"
            >
              {pinging ? (
                <RefreshCw className="w-4 h-4 animate-spin" />
              ) : (
                <Server className="w-4 h-4" />
              )}
              Ping All
            </button>
          }
        />

        {pingResults.length > 0 && (
          <div className="space-y-2">
            {pingResults.map((r, i) => (
              <motion.div
                key={r.endpoint}
                initial={{ opacity: 0, x: 12 }}
                animate={{ opacity: 1, x: 0 }}
                transition={{ delay: i * 0.05 }}
              >
                <Card className="flex items-center justify-between">
                  <div className="flex items-center gap-3">
                    {r.ok ? (
                      <CheckCircle2 className="w-4 h-4 text-emerald-400" />
                    ) : (
                      <XCircle className="w-4 h-4 text-red-400" />
                    )}
                    <div>
                      <p className="text-sm font-mono">
                        <span className="text-[var(--muted-foreground)]">
                          {r.method}
                        </span>{" "}
                        {r.endpoint}
                      </p>
                      {r.error && (
                        <p className="text-[10px] text-red-400 mt-0.5">
                          {r.error}
                        </p>
                      )}
                    </div>
                  </div>
                  <div className="flex items-center gap-3">
                    <Badge variant={r.ok ? "success" : "danger"}>
                      {r.status || "ERR"}
                    </Badge>
                    <span className="text-[10px] text-[var(--muted-foreground)] flex items-center gap-1">
                      <Clock className="w-3 h-3" />
                      {r.durationMs}ms
                    </span>
                  </div>
                </Card>
              </motion.div>
            ))}
          </div>
        )}
      </div>

      {/* Agent Diagnostics */}
      <div>
        <SectionHeader
          title="Agent Diagnostics"
          subtitle={agentSummary ? `Implementation status of all ${agentSummary.total} pipeline agents` : "Implementation status of pipeline agents"}
          action={
            <button
              onClick={loadAgents}
              disabled={agentsLoading}
              className="flex items-center gap-2 px-4 py-2 rounded-xl bg-[var(--muted)] hover:bg-[var(--border)] transition-colors text-sm font-medium"
            >
              <RefreshCw className={cn("w-4 h-4", agentsLoading && "animate-spin")} />
              Refresh
            </button>
          }
        />

        {agentSummary && (
          <Card gradient className="flex items-center gap-4 mb-4">
            <div
              className={cn(
                "w-12 h-12 rounded-xl flex items-center justify-center",
                agentSummary.health_level === "excellent"
                  ? "bg-emerald-500/15 text-emerald-400"
                  : agentSummary.health_level === "good"
                  ? "bg-sky-500/15 text-sky-400"
                  : "bg-amber-500/15 text-amber-400"
              )}
            >
              <ShieldCheck className="w-6 h-6" />
            </div>
            <div>
              <p className="text-sm font-medium">
                System Health:{" "}
                <span className="capitalize">{agentSummary.health_level}</span>{" "}
                ({agentSummary.health_pct}%)
              </p>
              <p className="text-xs text-[var(--muted-foreground)] mt-0.5">
                {agentSummary.implemented} implemented · {agentSummary.partial} partial · {agentSummary.stub} stub · {agentSummary.total} total
              </p>
            </div>
          </Card>
        )}

        {agents.length > 0 && (
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
            {agents.map((agent) => (
              <Card key={agent.agent_name} className="flex items-start gap-3 !p-3">
                <div
                  className={cn(
                    "w-8 h-8 rounded-lg flex items-center justify-center shrink-0 mt-0.5",
                    agent.status === "implemented"
                      ? "bg-emerald-500/15 text-emerald-400"
                      : agent.status === "partial"
                      ? "bg-amber-500/15 text-amber-400"
                      : "bg-red-500/15 text-red-400"
                  )}
                >
                  {agent.status === "implemented" ? (
                    <CheckCircle2 className="w-4 h-4" />
                  ) : agent.status === "partial" ? (
                    <AlertTriangle className="w-4 h-4" />
                  ) : (
                    <XCircle className="w-4 h-4" />
                  )}
                </div>
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-medium">{agent.agent_name}</span>
                    <Badge
                      variant={
                        agent.status === "implemented"
                          ? "success"
                          : agent.status === "partial"
                          ? "warning"
                          : "danger"
                      }
                    >
                      {agent.status}
                    </Badge>
                  </div>
                  <p className="text-[11px] text-[var(--muted-foreground)] mt-0.5 truncate">
                    {agent.evidence}
                  </p>
                  <p className="text-[10px] text-[var(--muted-foreground)] mt-0.5">
                    {agent.line_count} lines · {agent.method_count} methods
                  </p>
                </div>
              </Card>
            ))}
          </div>
        )}
      </div>

      {/* Raw JSON viewer */}
      <div>
        <SectionHeader
          title="Raw JSON"
          subtitle="Last API response"
          action={
            lastCallJson && (
              <button
                onClick={copyJson}
                className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-[var(--muted)] hover:bg-[var(--border)] text-xs font-medium transition-colors"
              >
                <Copy className="w-3 h-3" />
                Copy
              </button>
            )
          }
        />
        <Card>
          {lastCallJson ? (
            <pre className="text-[11px] leading-relaxed text-[var(--muted-foreground)] overflow-x-auto max-h-80 overflow-y-auto">
              {lastCallJson}
            </pre>
          ) : (
            <p className="text-sm text-[var(--muted-foreground)] text-center py-6">
              No API calls made yet. Click "Ping All" to test endpoints.
            </p>
          )}
        </Card>
      </div>

      {/* Request log */}
      <div>
        <SectionHeader
          title="Request Log"
          subtitle="Recent API calls (dev mode)"
          action={
            <button
              onClick={() => {
                clearApiLogs();
                setLogs([]);
              }}
              className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-[var(--muted)] hover:bg-[var(--border)] text-xs font-medium transition-colors"
            >
              <Trash2 className="w-3 h-3" />
              Clear
            </button>
          }
        />
        <Card>
          {logs.length > 0 ? (
            <div className="space-y-1 max-h-64 overflow-y-auto">
              {logs
                .slice()
                .reverse()
                .map((log, i) => (
                  <div
                    key={i}
                    className="flex items-center justify-between py-1.5 border-b border-[var(--border)] last:border-0"
                  >
                    <div className="flex items-center gap-2">
                      <span
                        className={cn(
                          "w-2 h-2 rounded-full shrink-0",
                          log.ok ? "bg-emerald-400" : "bg-red-400"
                        )}
                      />
                      <span className="text-[11px] font-mono text-[var(--muted-foreground)]">
                        {log.method}
                      </span>
                      <span className="text-[11px] font-mono truncate max-w-[200px]">
                        {log.url}
                      </span>
                    </div>
                    <div className="flex items-center gap-2 text-[10px] text-[var(--muted-foreground)]">
                      <span>{log.status || "ERR"}</span>
                      <span>{log.durationMs}ms</span>
                    </div>
                  </div>
                ))}
            </div>
          ) : (
            <div className="text-center py-6">
              <Terminal className="w-6 h-6 mx-auto text-[var(--muted-foreground)] mb-2" />
              <p className="text-xs text-[var(--muted-foreground)]">
                No requests logged yet.
              </p>
            </div>
          )}
        </Card>
      </div>
    </div>
  );
}
