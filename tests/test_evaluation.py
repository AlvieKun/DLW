"""Tests for Phase 10 — Evaluation Harness.

Covers:
- Scenario definitions and registry
- Metric computation and expectation checking
- End-to-end harness execution
- Report generation
- Edge cases: empty scenarios, all-pass, all-fail
"""

from __future__ import annotations

import pytest

from learning_navigator.contracts.events import (
    LearnerEventType,
    NextBestAction,
)
from learning_navigator.evaluation.harness import (
    EvaluationHarness,
    EvaluationResult,
    ScenarioResult,
)
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
    StepExpectation,
    get_all_scenarios,
    get_scenarios_by_tag,
    scenario_cold_start,
    scenario_happy_path,
    scenario_struggling_learner,
)


# ═══════════════════════════════════════════════════════════════════
# Scenario Registry Tests
# ═══════════════════════════════════════════════════════════════════


class TestScenarioRegistry:
    """Tests for scenario definitions and the registry."""

    def test_get_all_scenarios_returns_multiple(self) -> None:
        scenarios = get_all_scenarios()
        assert len(scenarios) >= 8, f"Expected >=8 scenarios, got {len(scenarios)}"

    def test_all_scenarios_have_names(self) -> None:
        for s in get_all_scenarios():
            assert s.name, f"Scenario missing name: {s}"
            assert s.description, f"Scenario {s.name} missing description"
            assert s.learner_id, f"Scenario {s.name} missing learner_id"
            assert len(s.steps) > 0, f"Scenario {s.name} has no steps"

    def test_all_scenarios_have_unique_names(self) -> None:
        names = [s.name for s in get_all_scenarios()]
        assert len(names) == len(set(names)), f"Duplicate names: {names}"

    def test_all_scenarios_have_unique_learner_ids(self) -> None:
        ids = [s.learner_id for s in get_all_scenarios()]
        assert len(ids) == len(set(ids)), f"Duplicate learner IDs: {ids}"

    def test_get_scenarios_by_tag_core(self) -> None:
        core = get_scenarios_by_tag("core")
        assert len(core) >= 5, "Expected at least 5 core scenarios"
        for s in core:
            assert "core" in s.tags

    def test_get_scenarios_by_tag_safety(self) -> None:
        safety = get_scenarios_by_tag("safety")
        assert len(safety) >= 2
        for s in safety:
            assert "safety" in s.tags

    def test_get_scenarios_by_tag_nonexistent(self) -> None:
        result = get_scenarios_by_tag("nonexistent-tag")
        assert result == []

    def test_scenario_happy_path_structure(self) -> None:
        s = scenario_happy_path()
        assert s.name == "happy-path-progression"
        assert len(s.steps) == 3
        assert all(
            step.event_type == LearnerEventType.QUIZ_RESULT
            for step in s.steps
        )
        # Scores should be increasing
        scores = [step.data["score"] for step in s.steps]
        assert scores == sorted(scores)

    def test_scenario_struggling_learner_structure(self) -> None:
        s = scenario_struggling_learner()
        assert s.name == "struggling-learner"
        assert len(s.steps) >= 3
        # Should end with a sentiment signal
        assert s.steps[-1].event_type == LearnerEventType.SENTIMENT_SIGNAL

    def test_scenario_cold_start_single_step(self) -> None:
        s = scenario_cold_start()
        assert s.name == "cold-start"
        assert len(s.steps) == 1

    def test_each_step_has_valid_event_type(self) -> None:
        for scenario in get_all_scenarios():
            for step in scenario.steps:
                assert isinstance(step.event_type, LearnerEventType)

    def test_step_expectations_have_valid_bounds(self) -> None:
        for scenario in get_all_scenarios():
            for step in scenario.steps:
                exp = step.expectation
                assert 0.0 <= exp.min_confidence <= exp.max_confidence <= 1.0
                assert 0.0 <= exp.min_gain <= exp.max_gain <= 1.0


# ═══════════════════════════════════════════════════════════════════
# Expectation Checker Tests
# ═══════════════════════════════════════════════════════════════════


def _make_nba(**overrides) -> NextBestAction:
    """Helper to create a NextBestAction with sensible defaults."""
    defaults = {
        "action_id": "test-1",
        "learner_id": "test-learner",
        "recommended_action": "study:algebra",
        "rationale": "Based on diagnosis",
        "confidence": 0.75,
        "expected_learning_gain": 0.1,
        "risk_assessment": {},
        "debug_trace": {"pipeline_steps": [
            {"agent": "diagnoser", "confidence": 0.8},
            {"agent": "motivation", "level": "medium"},
            {"agent": "maker_checker", "verdict": "approved", "rounds": 1, "issues": 0},
        ]},
    }
    defaults.update(overrides)
    return NextBestAction(**defaults)


class TestExpectationChecker:
    """Tests for check_expectation()."""

    def test_passes_when_all_constraints_met(self) -> None:
        nba = _make_nba(confidence=0.75)
        exp = StepExpectation(min_confidence=0.3, max_confidence=1.0)
        result = check_expectation(nba, exp)
        assert result.passed
        assert result.failures == []

    def test_fails_when_confidence_too_low(self) -> None:
        nba = _make_nba(confidence=0.1)
        exp = StepExpectation(min_confidence=0.5)
        result = check_expectation(nba, exp)
        assert not result.passed
        assert any("confidence" in f and "min" in f for f in result.failures)

    def test_fails_when_confidence_too_high(self) -> None:
        nba = _make_nba(confidence=0.95)
        exp = StepExpectation(max_confidence=0.5)
        result = check_expectation(nba, exp)
        assert not result.passed
        assert any("confidence" in f and "max" in f for f in result.failures)

    def test_fails_when_gain_too_low(self) -> None:
        nba = _make_nba(expected_learning_gain=0.01)
        exp = StepExpectation(min_gain=0.5)
        result = check_expectation(nba, exp)
        assert not result.passed
        assert any("gain" in f for f in result.failures)

    def test_fails_when_gain_too_high(self) -> None:
        nba = _make_nba(expected_learning_gain=0.9)
        exp = StepExpectation(max_gain=0.5)
        result = check_expectation(nba, exp)
        assert not result.passed

    def test_action_contains_match(self) -> None:
        nba = _make_nba(recommended_action="study:algebra")
        exp = StepExpectation(action_contains=["study", "review"])
        result = check_expectation(nba, exp)
        assert result.passed

    def test_action_contains_no_match(self) -> None:
        nba = _make_nba(recommended_action="study:algebra")
        exp = StepExpectation(action_contains=["advance", "skip"])
        result = check_expectation(nba, exp)
        assert not result.passed
        assert any("action" in f for f in result.failures)

    def test_rationale_empty_check(self) -> None:
        nba = _make_nba(rationale="")
        exp = StepExpectation(rationale_non_empty=True)
        result = check_expectation(nba, exp)
        assert not result.passed
        assert any("rationale" in f for f in result.failures)

    def test_rationale_empty_allowed(self) -> None:
        nba = _make_nba(rationale="")
        exp = StepExpectation(rationale_non_empty=False)
        result = check_expectation(nba, exp)
        assert result.passed

    def test_required_risk_key_present(self) -> None:
        nba = _make_nba(risk_assessment={"burnout": 0.5})
        exp = StepExpectation(required_risk_keys=["burnout"])
        result = check_expectation(nba, exp)
        assert result.passed

    def test_required_risk_key_missing(self) -> None:
        nba = _make_nba(risk_assessment={})
        exp = StepExpectation(required_risk_keys=["burnout"])
        result = check_expectation(nba, exp)
        assert not result.passed
        assert any("burnout" in f for f in result.failures)

    def test_forbidden_risk_key_absent(self) -> None:
        nba = _make_nba(risk_assessment={})
        exp = StepExpectation(forbidden_risk_keys=["crash"])
        result = check_expectation(nba, exp)
        assert result.passed

    def test_forbidden_risk_key_present(self) -> None:
        nba = _make_nba(risk_assessment={"crash": 1.0})
        exp = StepExpectation(forbidden_risk_keys=["crash"])
        result = check_expectation(nba, exp)
        assert not result.passed

    def test_pipeline_coverage_met(self) -> None:
        nba = _make_nba(debug_trace={"pipeline_steps": [
            {"agent": "a"}, {"agent": "b"}, {"agent": "c"},
        ]})
        exp = StepExpectation(min_pipeline_steps=3)
        result = check_expectation(nba, exp)
        assert result.passed

    def test_pipeline_coverage_not_met(self) -> None:
        nba = _make_nba(debug_trace={"pipeline_steps": [{"agent": "a"}]})
        exp = StepExpectation(min_pipeline_steps=5)
        result = check_expectation(nba, exp)
        assert not result.passed

    def test_skipped_steps_excluded_from_coverage(self) -> None:
        nba = _make_nba(debug_trace={"pipeline_steps": [
            {"agent": "a"},
            {"agent": "b", "skipped": True},
            {"agent": "c"},
        ]})
        exp = StepExpectation(min_pipeline_steps=3)
        result = check_expectation(nba, exp)
        assert not result.passed  # only 2 active steps

    def test_multiple_failures_accumulated(self) -> None:
        nba = _make_nba(confidence=0.1, rationale="", expected_learning_gain=0.01)
        exp = StepExpectation(
            min_confidence=0.5,
            rationale_non_empty=True,
            min_gain=0.5,
        )
        result = check_expectation(nba, exp)
        assert not result.passed
        assert len(result.failures) >= 3

    def test_latency_recorded(self) -> None:
        nba = _make_nba()
        result = check_expectation(nba, StepExpectation(), latency_ms=42.5)
        assert result.latency_ms == 42.5

    def test_nba_dict_stored_in_result(self) -> None:
        nba = _make_nba()
        result = check_expectation(nba, StepExpectation())
        assert "action_id" in result.nba
        assert result.nba["learner_id"] == "test-learner"

    def test_default_expectation_passes_valid_nba(self) -> None:
        """Default StepExpectation should pass any valid NBA."""
        nba = _make_nba()
        result = check_expectation(nba, StepExpectation())
        assert result.passed


# ═══════════════════════════════════════════════════════════════════
# Metric Aggregation Tests
# ═══════════════════════════════════════════════════════════════════


class TestMetricAggregation:
    """Tests for aggregate_scenario_metrics and aggregate_suite_metrics."""

    def test_aggregate_scenario_all_pass(self) -> None:
        steps = [
            StepResult(step_index=0, description="s1", passed=True, latency_ms=10.0),
            StepResult(step_index=1, description="s2", passed=True, latency_ms=20.0),
        ]
        nbas = [
            _make_nba(confidence=0.7, expected_learning_gain=0.1),
            _make_nba(confidence=0.9, expected_learning_gain=0.15),
        ]
        m = aggregate_scenario_metrics("test", steps, nbas)
        assert m.total_steps == 2
        assert m.passed_steps == 2
        assert m.failed_steps == 0
        assert m.all_passed
        assert m.pass_rate == 1.0
        assert m.mean_confidence == pytest.approx(0.8)
        assert m.mean_latency_ms == pytest.approx(15.0)
        assert m.max_latency_ms == pytest.approx(20.0)

    def test_aggregate_scenario_partial_fail(self) -> None:
        steps = [
            StepResult(step_index=0, description="s1", passed=True, latency_ms=5.0),
            StepResult(step_index=1, description="s2", passed=False, failures=["low conf"], latency_ms=8.0),
        ]
        nbas = [
            _make_nba(confidence=0.6),
            _make_nba(confidence=0.3),
        ]
        m = aggregate_scenario_metrics("test", steps, nbas)
        assert m.total_steps == 2
        assert m.passed_steps == 1
        assert m.failed_steps == 1
        assert m.pass_rate == 0.5
        assert not m.all_passed

    def test_aggregate_scenario_empty(self) -> None:
        m = aggregate_scenario_metrics("empty", [], [])
        assert m.total_steps == 0
        assert m.pass_rate == 0.0
        assert not m.all_passed  # 0 steps = not passed

    def test_aggregate_suite_metrics(self) -> None:
        m1 = QualityMetrics(
            scenario_name="s1", total_steps=3, passed_steps=3,
            failed_steps=0, mean_confidence=0.8, mean_latency_ms=10.0,
        )
        m2 = QualityMetrics(
            scenario_name="s2", total_steps=2, passed_steps=1,
            failed_steps=1, mean_confidence=0.5, mean_latency_ms=20.0,
        )
        suite = aggregate_suite_metrics([m1, m2])
        assert suite.total_scenarios == 2
        assert suite.passed_scenarios == 1
        assert suite.failed_scenarios == 1
        assert suite.total_steps == 5
        assert suite.passed_steps == 4
        assert suite.failed_steps == 1
        assert suite.overall_mean_confidence == pytest.approx(0.65)
        assert suite.overall_mean_latency_ms == pytest.approx(15.0)
        assert suite.scenario_pass_rate == 0.5
        assert suite.step_pass_rate == pytest.approx(0.8)
        assert not suite.all_passed

    def test_aggregate_suite_all_pass(self) -> None:
        m1 = QualityMetrics(
            scenario_name="s1", total_steps=1, passed_steps=1, failed_steps=0,
            mean_confidence=0.9, mean_latency_ms=5.0,
        )
        suite = aggregate_suite_metrics([m1])
        assert suite.all_passed
        assert suite.scenario_pass_rate == 1.0

    def test_aggregate_suite_empty(self) -> None:
        suite = aggregate_suite_metrics([])
        assert suite.total_scenarios == 0
        assert not suite.all_passed

    def test_confidence_stddev_computed(self) -> None:
        steps = [
            StepResult(step_index=0, description="s1", passed=True, latency_ms=1.0),
            StepResult(step_index=1, description="s2", passed=True, latency_ms=1.0),
        ]
        nbas = [
            _make_nba(confidence=0.3),
            _make_nba(confidence=0.9),
        ]
        m = aggregate_scenario_metrics("test", steps, nbas)
        assert m.confidence_stddev > 0.0

    def test_pipeline_coverage_mean(self) -> None:
        steps = [
            StepResult(step_index=0, description="s1", passed=True, latency_ms=1.0),
        ]
        nbas = [
            _make_nba(debug_trace={"pipeline_steps": [
                {"agent": "a"}, {"agent": "b"}, {"agent": "c"},
            ]}),
        ]
        m = aggregate_scenario_metrics("test", steps, nbas)
        assert m.pipeline_coverage_mean == 3.0


# ═══════════════════════════════════════════════════════════════════
# Quality Metrics Properties
# ═══════════════════════════════════════════════════════════════════


class TestQualityMetricsProperties:
    def test_pass_rate_zero_steps(self) -> None:
        m = QualityMetrics(scenario_name="x", total_steps=0)
        assert m.pass_rate == 0.0

    def test_all_passed_with_failures(self) -> None:
        m = QualityMetrics(scenario_name="x", total_steps=2, passed_steps=1, failed_steps=1)
        assert not m.all_passed


class TestMetricSuiteProperties:
    def test_scenario_pass_rate_zero(self) -> None:
        suite = MetricSuite(total_scenarios=0)
        assert suite.scenario_pass_rate == 0.0

    def test_step_pass_rate_zero(self) -> None:
        suite = MetricSuite(total_steps=0)
        assert suite.step_pass_rate == 0.0


# ═══════════════════════════════════════════════════════════════════
# End-to-End Harness Tests
# ═══════════════════════════════════════════════════════════════════


class TestEvaluationHarness:
    """Integration tests for the full evaluation harness."""

    @pytest.mark.asyncio()
    async def test_run_single_scenario(self, tmp_path) -> None:
        """Run cold-start (1 step) and verify result structure."""
        harness = EvaluationHarness(
            scenarios=[scenario_cold_start()],
            debate_enabled=True,
        )
        result = await harness.run_all(base_tmp_dir=str(tmp_path))

        assert isinstance(result, EvaluationResult)
        assert result.suite.total_scenarios == 1
        assert result.suite.total_steps == 1
        assert len(result.scenario_results) == 1

        sr = result.scenario_results[0]
        assert sr.scenario.name == "cold-start"
        assert sr.metrics.total_steps == 1
        assert len(sr.nbas) == 1

    @pytest.mark.asyncio()
    async def test_run_happy_path_scenario(self, tmp_path) -> None:
        """Run happy-path (3 steps) and verify multi-step execution."""
        harness = EvaluationHarness(
            scenarios=[scenario_happy_path()],
        )
        result = await harness.run_all(base_tmp_dir=str(tmp_path))

        sr = result.scenario_results[0]
        assert sr.metrics.total_steps == 3
        assert len(sr.nbas) == 3
        # All steps should produce valid NBAs with non-zero confidence
        for nba_dict in sr.nbas:
            assert nba_dict["confidence"] >= 0.0
            assert nba_dict["rationale"]

    @pytest.mark.asyncio()
    async def test_run_struggling_learner_scenario(self, tmp_path) -> None:
        """Run struggling-learner scenario with 4 steps."""
        harness = EvaluationHarness(
            scenarios=[scenario_struggling_learner()],
        )
        result = await harness.run_all(base_tmp_dir=str(tmp_path))

        sr = result.scenario_results[0]
        assert sr.metrics.total_steps == 4
        assert len(sr.nbas) >= 3

    @pytest.mark.asyncio()
    async def test_run_all_built_in_scenarios(self, tmp_path) -> None:
        """Run ALL built-in scenarios — smoke test for the full eval suite."""
        harness = EvaluationHarness()
        result = await harness.run_all(base_tmp_dir=str(tmp_path))

        assert result.suite.total_scenarios == len(get_all_scenarios())
        assert result.suite.total_steps > 0
        assert len(result.errors) == 0
        # Every scenario should have produced at least some NBAs
        for sr in result.scenario_results:
            assert len(sr.nbas) > 0

    @pytest.mark.asyncio()
    async def test_scenario_isolation(self, tmp_path) -> None:
        """Verify scenarios don't share state across runs."""
        harness = EvaluationHarness(
            scenarios=[scenario_cold_start(), scenario_happy_path()],
        )
        result = await harness.run_all(base_tmp_dir=str(tmp_path))

        assert result.suite.total_scenarios == 2
        # Each scenario has its own learner_id
        lr_ids = {sr.scenario.learner_id for sr in result.scenario_results}
        assert len(lr_ids) == 2

    @pytest.mark.asyncio()
    async def test_custom_scenario_via_harness(self, tmp_path) -> None:
        """Create a custom scenario on the fly and run it."""
        custom = EvalScenario(
            name="custom-test",
            description="Minimal custom scenario",
            learner_id="eval-custom",
            steps=[
                ScenarioStep(
                    event_type=LearnerEventType.QUIZ_RESULT,
                    concept_id="test-concept",
                    data={"score": 0.7, "max_score": 1.0},
                    description="Simple quiz",
                    expectation=StepExpectation(
                        min_confidence=0.0,
                        rationale_non_empty=True,
                    ),
                ),
            ],
        )
        harness = EvaluationHarness(scenarios=[custom])
        result = await harness.run_all(base_tmp_dir=str(tmp_path))

        assert result.suite.total_scenarios == 1
        sr = result.scenario_results[0]
        assert sr.scenario.name == "custom-test"
        assert sr.metrics.total_steps == 1

    @pytest.mark.asyncio()
    async def test_latency_tracking(self, tmp_path) -> None:
        """Verify latency is tracked per step."""
        harness = EvaluationHarness(
            scenarios=[scenario_cold_start()],
        )
        result = await harness.run_all(base_tmp_dir=str(tmp_path))

        sr = result.scenario_results[0]
        assert sr.metrics.mean_latency_ms > 0.0
        for step_r in sr.metrics.step_results:
            assert step_r.latency_ms >= 0.0

    @pytest.mark.asyncio()
    async def test_adaptive_routing_mode(self, tmp_path) -> None:
        """Run with adaptive routing enabled."""
        harness = EvaluationHarness(
            scenarios=[scenario_cold_start()],
            adaptive_routing_enabled=True,
        )
        result = await harness.run_all(base_tmp_dir=str(tmp_path))
        assert result.suite.total_scenarios == 1
        assert result.suite.total_steps == 1


# ═══════════════════════════════════════════════════════════════════
# Report Generation Tests
# ═══════════════════════════════════════════════════════════════════


class TestReportGeneration:
    """Tests for report output formats."""

    @pytest.mark.asyncio()
    async def test_summary_text_output(self, tmp_path) -> None:
        """Verify summary() produces readable text."""
        harness = EvaluationHarness(
            scenarios=[scenario_cold_start()],
        )
        result = await harness.run_all(base_tmp_dir=str(tmp_path))
        summary = result.summary()

        assert "EVALUATION HARNESS REPORT" in summary
        assert "cold-start" in summary
        assert "Scenarios:" in summary
        assert "Steps:" in summary

    @pytest.mark.asyncio()
    async def test_to_dict_output(self, tmp_path) -> None:
        """Verify to_dict() produces a valid serialisable dict."""
        harness = EvaluationHarness(
            scenarios=[scenario_cold_start()],
        )
        result = await harness.run_all(base_tmp_dir=str(tmp_path))
        d = result.to_dict()

        assert "passed" in d
        assert "scenarios" in d
        assert "steps" in d
        assert "confidence_mean" in d
        assert "latency_mean_ms" in d
        assert "scenario_details" in d
        assert len(d["scenario_details"]) == 1
        assert d["scenario_details"][0]["name"] == "cold-start"

    @pytest.mark.asyncio()
    async def test_to_dict_serialisable(self, tmp_path) -> None:
        """Verify to_dict() output is JSON-serialisable."""
        import json

        harness = EvaluationHarness(
            scenarios=[scenario_cold_start()],
        )
        result = await harness.run_all(base_tmp_dir=str(tmp_path))
        d = result.to_dict()
        serialised = json.dumps(d)
        assert isinstance(serialised, str)
        assert len(serialised) > 10

    @pytest.mark.asyncio()
    async def test_summary_shows_failures(self, tmp_path) -> None:
        """A scenario with impossible expectations should show failures."""
        impossible = EvalScenario(
            name="impossible",
            description="Expectation that cannot be met",
            learner_id="eval-impossible",
            steps=[
                ScenarioStep(
                    event_type=LearnerEventType.QUIZ_RESULT,
                    concept_id="x",
                    data={"score": 0.5, "max_score": 1.0},
                    description="Will fail",
                    expectation=StepExpectation(
                        min_confidence=0.99,
                        max_confidence=1.0,
                        action_contains=["nonexistent_action_xyz"],
                    ),
                ),
            ],
        )
        harness = EvaluationHarness(scenarios=[impossible])
        result = await harness.run_all(base_tmp_dir=str(tmp_path))

        assert not result.all_passed
        summary = result.summary()
        assert "FAIL" in summary

    def test_evaluation_result_all_passed_with_errors(self) -> None:
        """all_passed should be False when there are global errors."""
        suite = MetricSuite(
            total_scenarios=1, passed_scenarios=1,
            total_steps=1, passed_steps=1,
        )
        result = EvaluationResult(suite=suite, errors=["something broke"])
        assert not result.all_passed

    def test_evaluation_result_all_passed_clean(self) -> None:
        suite = MetricSuite(
            total_scenarios=1, passed_scenarios=1,
            total_steps=1, passed_steps=1,
        )
        result = EvaluationResult(suite=suite)
        assert result.all_passed


# ═══════════════════════════════════════════════════════════════════
# Edge Case Tests
# ═══════════════════════════════════════════════════════════════════


class TestEdgeCases:
    def test_step_expectation_defaults(self) -> None:
        """Default StepExpectation should be maximally permissive."""
        exp = StepExpectation()
        assert exp.min_confidence == 0.0
        assert exp.max_confidence == 1.0
        assert exp.min_gain == 0.0
        assert exp.max_gain == 1.0
        assert exp.action_contains == []
        assert exp.required_risk_keys == []
        assert exp.forbidden_risk_keys == []
        assert exp.rationale_non_empty is True
        assert exp.min_pipeline_steps == 0

    def test_scenario_step_defaults(self) -> None:
        step = ScenarioStep(
            event_type=LearnerEventType.QUIZ_RESULT,
        )
        assert step.concept_id is None
        assert step.data == {}
        assert step.source == "eval-harness"
        assert step.description == ""

    def test_eval_scenario_tags_default(self) -> None:
        s = EvalScenario(
            name="test", description="test", learner_id="t",
            steps=[ScenarioStep(event_type=LearnerEventType.CUSTOM)],
        )
        assert s.tags == []

    def test_step_result_dataclass(self) -> None:
        r = StepResult(step_index=0, description="d", passed=True)
        assert r.failures == []
        assert r.nba == {}
        assert r.latency_ms == 0.0

    def test_scenario_result_dataclass(self) -> None:
        scenario = scenario_cold_start()
        metrics = QualityMetrics(scenario_name="cold-start")
        sr = ScenarioResult(scenario=scenario, metrics=metrics)
        assert sr.error is None
        assert sr.nbas == []
