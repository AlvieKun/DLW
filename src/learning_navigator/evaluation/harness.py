"""Evaluation harness — runs scenarios through the GPS Engine and collects metrics.

The harness:
1. Instantiates a fresh engine per scenario (isolated state).
2. Feeds each step's event through ``engine.process_event()``.
3. Checks expectations via ``check_expectation()``.
4. Aggregates metrics and produces a structured ``EvaluationResult``.

Usage::

    harness = EvaluationHarness()
    result = await harness.run_all()
    print(result.summary())
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any

import structlog

from learning_navigator.contracts.events import (
    LearnerEvent,
    NextBestAction,
)
from learning_navigator.engine.event_bus import InMemoryEventBus
from learning_navigator.engine.gps_engine import LearningGPSEngine
from learning_navigator.evaluation.metrics import (
    MetricSuite,
    QualityMetrics,
    StepResult,
    aggregate_scenario_metrics,
    aggregate_suite_metrics,
    check_expectation,
)
from learning_navigator.evaluation.scenarios import (
    EvalScenario,
    ScenarioStep,
    get_all_scenarios,
)
from learning_navigator.storage.local_store import (
    LocalJsonMemoryStore,
    LocalJsonPortfolioLogger,
)

logger = structlog.get_logger(__name__)


# ── Result container ───────────────────────────────────────────────


@dataclass
class ScenarioResult:
    """Full result of running one evaluation scenario."""

    scenario: EvalScenario
    metrics: QualityMetrics
    nbas: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None


@dataclass
class EvaluationResult:
    """Top-level result of running the full evaluation suite."""

    suite: MetricSuite
    scenario_results: list[ScenarioResult] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def all_passed(self) -> bool:
        return self.suite.all_passed and not self.errors

    def summary(self) -> str:
        """Human-readable summary."""
        lines: list[str] = [
            "",
            "=" * 68,
            "  EVALUATION HARNESS REPORT",
            "=" * 68,
            "",
            f"  Scenarios: {self.suite.passed_scenarios}/{self.suite.total_scenarios} passed",
            f"  Steps:     {self.suite.passed_steps}/{self.suite.total_steps} passed",
            f"  Confidence (mean): {self.suite.overall_mean_confidence:.3f}",
            f"  Latency (mean):    {self.suite.overall_mean_latency_ms:.1f} ms",
            "",
        ]

        for sr in self.scenario_results:
            status = "PASS" if sr.metrics.all_passed else "FAIL"
            lines.append(
                f"  [{status}] {sr.scenario.name} "
                f"({sr.metrics.passed_steps}/{sr.metrics.total_steps} steps)"
            )
            if not sr.metrics.all_passed:
                for step_r in sr.metrics.step_results:
                    if not step_r.passed:
                        for f in step_r.failures:
                            lines.append(f"         step {step_r.step_index}: {f}")
            if sr.error:
                lines.append(f"         ERROR: {sr.error}")

        if self.errors:
            lines.append("")
            lines.append("  Global errors:")
            for err in self.errors:
                lines.append(f"    - {err}")

        lines.extend(["", "=" * 68])
        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        """Serialisable dictionary form of the report."""
        return {
            "passed": self.all_passed,
            "scenarios": {
                "total": self.suite.total_scenarios,
                "passed": self.suite.passed_scenarios,
                "failed": self.suite.failed_scenarios,
            },
            "steps": {
                "total": self.suite.total_steps,
                "passed": self.suite.passed_steps,
                "failed": self.suite.failed_steps,
            },
            "confidence_mean": round(self.suite.overall_mean_confidence, 4),
            "latency_mean_ms": round(self.suite.overall_mean_latency_ms, 2),
            "scenario_details": [
                {
                    "name": sr.scenario.name,
                    "passed": sr.metrics.all_passed,
                    "pass_rate": round(sr.metrics.pass_rate, 4),
                    "mean_confidence": round(sr.metrics.mean_confidence, 4),
                    "mean_latency_ms": round(sr.metrics.mean_latency_ms, 2),
                    "step_failures": [
                        {
                            "step": step_r.step_index,
                            "description": step_r.description,
                            "failures": step_r.failures,
                        }
                        for step_r in sr.metrics.step_results
                        if not step_r.passed
                    ],
                    "error": sr.error,
                }
                for sr in self.scenario_results
            ],
            "errors": self.errors,
        }


# ── Harness ────────────────────────────────────────────────────────


class EvaluationHarness:
    """Runs evaluation scenarios and collects quality metrics.

    Parameters
    ----------
    data_dir : str | None
        Temporary directory for local stores.  If *None*, uses a fresh
        temp directory per scenario (recommended for isolation).
    scenarios : list[EvalScenario] | None
        Override the built-in scenario set.
    debate_enabled : bool
        Whether to enable strategic debate in the engine.
    adaptive_routing_enabled : bool
        Whether to enable adaptive routing.
    """

    def __init__(
        self,
        data_dir: str | None = None,
        scenarios: list[EvalScenario] | None = None,
        debate_enabled: bool = True,
        adaptive_routing_enabled: bool = False,
    ) -> None:
        self._data_dir = data_dir
        self._scenarios = scenarios or get_all_scenarios()
        self._debate_enabled = debate_enabled
        self._adaptive_routing = adaptive_routing_enabled

    def _create_engine(self, tmp_dir: str) -> LearningGPSEngine:
        """Create an isolated engine instance for one scenario."""
        import pathlib

        data_path = pathlib.Path(tmp_dir)
        data_path.mkdir(parents=True, exist_ok=True)

        memory_store = LocalJsonMemoryStore(data_dir=data_path)
        portfolio_logger = LocalJsonPortfolioLogger(data_dir=data_path)
        event_bus = InMemoryEventBus()

        return LearningGPSEngine(
            memory_store=memory_store,
            portfolio_logger=portfolio_logger,
            event_bus=event_bus,
            debate_enabled=self._debate_enabled,
            adaptive_routing_enabled=self._adaptive_routing,
        )

    async def run_scenario(
        self, scenario: EvalScenario, tmp_dir: str
    ) -> ScenarioResult:
        """Run a single evaluation scenario end-to-end."""
        engine = self._create_engine(tmp_dir)
        step_results: list[StepResult] = []
        nbas: list[NextBestAction] = []

        log = logger.bind(scenario=scenario.name)
        log.info("eval.scenario.start", steps=len(scenario.steps))

        error: str | None = None

        for idx, step in enumerate(scenario.steps):
            event = LearnerEvent(
                event_id=f"eval-{scenario.name}-{idx}-{uuid.uuid4().hex[:6]}",
                learner_id=scenario.learner_id,
                event_type=step.event_type,
                concept_id=step.concept_id,
                data=step.data,
                source=step.source,
            )

            try:
                t0 = time.perf_counter()
                nba = await engine.process_event(event)
                latency_ms = (time.perf_counter() - t0) * 1000.0
            except Exception as exc:
                log.error("eval.step.error", step=idx, error=str(exc))
                error = f"Step {idx} raised: {exc}"
                step_results.append(
                    StepResult(
                        step_index=idx,
                        description=step.description,
                        passed=False,
                        failures=[f"Exception: {exc}"],
                        latency_ms=0.0,
                    )
                )
                continue

            result = check_expectation(nba, step.expectation, latency_ms)
            result.step_index = idx
            result.description = step.description
            step_results.append(result)
            nbas.append(nba)

            log.debug(
                "eval.step.done",
                step=idx,
                passed=result.passed,
                confidence=nba.confidence,
                latency=f"{latency_ms:.1f}ms",
            )

        metrics = aggregate_scenario_metrics(scenario.name, step_results, nbas)

        log.info(
            "eval.scenario.done",
            passed=metrics.all_passed,
            pass_rate=f"{metrics.pass_rate:.1%}",
        )

        return ScenarioResult(
            scenario=scenario,
            metrics=metrics,
            nbas=[n.model_dump(mode="json", exclude={"timestamp"}) for n in nbas],
            error=error,
        )

    async def run_all(self, base_tmp_dir: str | None = None) -> EvaluationResult:
        """Run all scenarios and produce a full evaluation report."""
        import pathlib
        import tempfile

        if base_tmp_dir:
            base = pathlib.Path(base_tmp_dir)
        else:
            base = pathlib.Path(tempfile.mkdtemp(prefix="eval-harness-"))

        scenario_results: list[ScenarioResult] = []
        global_errors: list[str] = []

        logger.info(
            "eval.suite.start",
            scenarios=len(self._scenarios),
            base_dir=str(base),
        )

        for scenario in self._scenarios:
            scenario_dir = str(base / scenario.name)
            try:
                result = await self.run_scenario(scenario, scenario_dir)
                scenario_results.append(result)
            except Exception as exc:
                global_errors.append(f"Scenario '{scenario.name}' crashed: {exc}")
                logger.error(
                    "eval.scenario.crash",
                    scenario=scenario.name,
                    error=str(exc),
                )

        all_metrics = [sr.metrics for sr in scenario_results]
        suite = aggregate_suite_metrics(all_metrics)

        evaluation_result = EvaluationResult(
            suite=suite,
            scenario_results=scenario_results,
            errors=global_errors,
        )

        logger.info(
            "eval.suite.done",
            passed=evaluation_result.all_passed,
            scenarios=f"{suite.passed_scenarios}/{suite.total_scenarios}",
            steps=f"{suite.passed_steps}/{suite.total_steps}",
        )

        return evaluation_result
