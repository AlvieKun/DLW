"""Evaluation metrics — quantitative quality measures for pipeline output.

Computes per-step and aggregate metrics across scenario runs:

• **Recommendation quality**: confidence calibration, gain plausibility,
  action-type coverage.
• **Safety**: risk flag presence/absence, overload detection.
• **Pipeline coverage**: how many agents contributed to each result.
• **Latency**: wall-clock time per pipeline run.
• **Consistency**: variance of confidence across repeated identical events.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from typing import Any

from learning_navigator.contracts.events import NextBestAction
from learning_navigator.evaluation.scenarios import StepExpectation


# ── Per-step result ────────────────────────────────────────────────


@dataclass
class StepResult:
    """Outcome of evaluating a single scenario step."""

    step_index: int
    description: str
    passed: bool
    failures: list[str] = field(default_factory=list)
    nba: dict[str, Any] = field(default_factory=dict)
    latency_ms: float = 0.0


# ── Quality metrics (aggregated over a scenario) ──────────────────


@dataclass
class QualityMetrics:
    """Aggregate quality metrics for one scenario run."""

    scenario_name: str
    total_steps: int = 0
    passed_steps: int = 0
    failed_steps: int = 0

    # Per-step results
    step_results: list[StepResult] = field(default_factory=list)

    # Aggregates
    mean_confidence: float = 0.0
    confidence_stddev: float = 0.0
    mean_gain: float = 0.0
    mean_latency_ms: float = 0.0
    max_latency_ms: float = 0.0
    pipeline_coverage_mean: float = 0.0  # avg agent steps per run

    @property
    def pass_rate(self) -> float:
        """Fraction of steps that passed all expectations."""
        return self.passed_steps / self.total_steps if self.total_steps else 0.0

    @property
    def all_passed(self) -> bool:
        return self.failed_steps == 0 and self.total_steps > 0


# ── Metric suite (all scenarios) ──────────────────────────────────


@dataclass
class MetricSuite:
    """Collection of quality metrics across all evaluated scenarios."""

    scenario_metrics: list[QualityMetrics] = field(default_factory=list)
    total_scenarios: int = 0
    passed_scenarios: int = 0
    failed_scenarios: int = 0
    total_steps: int = 0
    passed_steps: int = 0
    failed_steps: int = 0
    overall_mean_confidence: float = 0.0
    overall_mean_latency_ms: float = 0.0

    @property
    def scenario_pass_rate(self) -> float:
        return self.passed_scenarios / self.total_scenarios if self.total_scenarios else 0.0

    @property
    def step_pass_rate(self) -> float:
        return self.passed_steps / self.total_steps if self.total_steps else 0.0

    @property
    def all_passed(self) -> bool:
        return self.failed_scenarios == 0 and self.total_scenarios > 0


# ── Expectation checker ───────────────────────────────────────────


def check_expectation(
    nba: NextBestAction,
    expectation: StepExpectation,
    latency_ms: float = 0.0,
) -> StepResult:
    """Validate a NextBestAction against a StepExpectation.

    Returns a StepResult with pass/fail and a list of failure reasons.
    """
    failures: list[str] = []

    # Confidence bounds
    if nba.confidence < expectation.min_confidence:
        failures.append(
            f"confidence {nba.confidence:.3f} < min {expectation.min_confidence}"
        )
    if nba.confidence > expectation.max_confidence:
        failures.append(
            f"confidence {nba.confidence:.3f} > max {expectation.max_confidence}"
        )

    # Learning gain bounds
    if nba.expected_learning_gain < expectation.min_gain:
        failures.append(
            f"gain {nba.expected_learning_gain:.3f} < min {expectation.min_gain}"
        )
    if nba.expected_learning_gain > expectation.max_gain:
        failures.append(
            f"gain {nba.expected_learning_gain:.3f} > max {expectation.max_gain}"
        )

    # Action substring check
    if expectation.action_contains:
        action_lower = nba.recommended_action.lower()
        if not any(sub.lower() in action_lower for sub in expectation.action_contains):
            failures.append(
                f"action '{nba.recommended_action}' does not contain any of "
                f"{expectation.action_contains}"
            )

    # Rationale
    if expectation.rationale_non_empty and not nba.rationale.strip():
        failures.append("rationale is empty")

    # Required risk keys
    for key in expectation.required_risk_keys:
        if key not in nba.risk_assessment:
            failures.append(f"missing required risk key: {key}")

    # Forbidden risk keys
    for key in expectation.forbidden_risk_keys:
        if key in nba.risk_assessment:
            failures.append(f"found forbidden risk key: {key}")

    # Pipeline coverage
    pipeline_steps = nba.debug_trace.get("pipeline_steps", [])
    active_steps = [s for s in pipeline_steps if not s.get("skipped")]
    if len(active_steps) < expectation.min_pipeline_steps:
        failures.append(
            f"pipeline coverage {len(active_steps)} < min {expectation.min_pipeline_steps}"
        )

    return StepResult(
        step_index=0,  # caller sets this
        description="",  # caller sets this
        passed=len(failures) == 0,
        failures=failures,
        nba=nba.model_dump(mode="json", exclude={"timestamp"}),
        latency_ms=latency_ms,
    )


# ── Aggregation helpers ───────────────────────────────────────────


def aggregate_scenario_metrics(
    scenario_name: str,
    step_results: list[StepResult],
    nbas: list[NextBestAction],
) -> QualityMetrics:
    """Compute aggregate metrics from per-step results."""
    total = len(step_results)
    passed = sum(1 for r in step_results if r.passed)

    confidences = [n.confidence for n in nbas]
    gains = [n.expected_learning_gain for n in nbas]
    latencies = [r.latency_ms for r in step_results]

    # Pipeline coverage: count non-skipped steps
    coverages: list[int] = []
    for n in nbas:
        steps = n.debug_trace.get("pipeline_steps", [])
        active = [s for s in steps if not s.get("skipped")]
        coverages.append(len(active))

    return QualityMetrics(
        scenario_name=scenario_name,
        total_steps=total,
        passed_steps=passed,
        failed_steps=total - passed,
        step_results=step_results,
        mean_confidence=statistics.mean(confidences) if confidences else 0.0,
        confidence_stddev=statistics.stdev(confidences) if len(confidences) >= 2 else 0.0,
        mean_gain=statistics.mean(gains) if gains else 0.0,
        mean_latency_ms=statistics.mean(latencies) if latencies else 0.0,
        max_latency_ms=max(latencies) if latencies else 0.0,
        pipeline_coverage_mean=statistics.mean(coverages) if coverages else 0.0,
    )


def aggregate_suite_metrics(
    scenario_metrics: list[QualityMetrics],
) -> MetricSuite:
    """Roll up all scenario metrics into a single suite summary."""
    total_scenarios = len(scenario_metrics)
    passed_scenarios = sum(1 for m in scenario_metrics if m.all_passed)
    total_steps = sum(m.total_steps for m in scenario_metrics)
    passed_steps = sum(m.passed_steps for m in scenario_metrics)

    all_confidences = [m.mean_confidence for m in scenario_metrics if m.total_steps > 0]
    all_latencies = [m.mean_latency_ms for m in scenario_metrics if m.total_steps > 0]

    return MetricSuite(
        scenario_metrics=scenario_metrics,
        total_scenarios=total_scenarios,
        passed_scenarios=passed_scenarios,
        failed_scenarios=total_scenarios - passed_scenarios,
        total_steps=total_steps,
        passed_steps=passed_steps,
        failed_steps=total_steps - passed_steps,
        overall_mean_confidence=(
            statistics.mean(all_confidences) if all_confidences else 0.0
        ),
        overall_mean_latency_ms=(
            statistics.mean(all_latencies) if all_latencies else 0.0
        ),
    )
