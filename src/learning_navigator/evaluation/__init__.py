"""Evaluation harness — scenario-driven quality assessment of the GPS Engine.

Provides:
- Pre-defined learner journey scenarios (multi-step event sequences).
- Metric computation: recommendation quality, confidence calibration,
  pipeline coverage, safety, latency.
- Report generation with pass/fail assertions per scenario.
- CLI integration via ``learning-nav evaluate``.
"""

from learning_navigator.evaluation.harness import EvaluationHarness, EvaluationResult
from learning_navigator.evaluation.metrics import (
    MetricSuite,
    QualityMetrics,
)
from learning_navigator.evaluation.scenarios import (
    EvalScenario,
    ScenarioStep,
    get_all_scenarios,
)

__all__ = [
    "EvalScenario",
    "EvaluationHarness",
    "EvaluationResult",
    "MetricSuite",
    "QualityMetrics",
    "ScenarioStep",
    "get_all_scenarios",
]
