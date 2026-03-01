"""Tests for Phase 8 — Competitive Differentiators.

Covers:
1. AdaptiveRouter — routing decisions, core agent selection, budget
   exhaustion, full-pipeline interval, need scoring, value density.
2. ConfidenceCalibrator — record_outcome, calibrate, trust weights,
   cold-start, exponential decay, clamping, reset, summary.
3. GPS Engine integration — routing in debug_trace, agent skipping,
   confidence calibration wiring.
"""

from __future__ import annotations

import math

import pytest

from learning_navigator.agents.base import (
    AgentCapability,
    AgentMetadata,
    BaseAgent,
)
from learning_navigator.contracts.events import (
    LearnerEvent,
    LearnerEventType,
    NextBestAction,
)
from learning_navigator.contracts.learner_state import (
    BKTParams,
    ConceptState,
    LearnerState,
)
from learning_navigator.contracts.messages import MessageEnvelope, MessageType
from learning_navigator.engine.adaptive_router import (
    AdaptiveRouter,
    RoutingDecision,
    _AgentNeedScore,
)
from learning_navigator.engine.confidence_calibrator import (
    AgentCalibration,
    CalibrationRecord,
    ConfidenceCalibrator,
)
from learning_navigator.engine.event_bus import InMemoryEventBus
from learning_navigator.engine.gps_engine import LearningGPSEngine
from learning_navigator.storage.local_store import (
    LocalJsonMemoryStore,
    LocalJsonPortfolioLogger,
)

# ── Helpers ────────────────────────────────────────────────────────


class _StubAgent(BaseAgent):
    """Minimal agent stub for testing the router."""

    def __init__(self, agent_id: str, cost_tier: int = 1) -> None:
        meta = AgentMetadata(
            agent_id=agent_id,
            display_name=agent_id.replace("_", " ").title(),
            version="0.1.0",
            capabilities=[AgentCapability.DIAGNOSE],
            cost_tier=cost_tier,
        )
        super().__init__(metadata=meta)

    async def handle(self, message: MessageEnvelope) -> MessageEnvelope:
        return MessageEnvelope(
            message_type=MessageType.AGENT_RESPONSE,
            source_agent_id=self.agent_id,
            target_agent_id="engine",
            payload={"ok": True},
        )


def _make_agents(
    spec: dict[str, int] | None = None,
) -> dict[str, BaseAgent]:
    """Build a dict of stub agents. spec = {agent_id: cost_tier}."""
    if spec is None:
        spec = {
            "diagnoser": 1,
            "motivation": 1,
            "drift-detector": 1,
            "skill-state": 1,
            "behavior": 1,
            "decay": 1,
            "generative-replay": 2,
            "time-optimizer": 2,
            "planner": 2,
            "evaluator": 2,
            "reflection": 2,
        }
    return {aid: _StubAgent(aid, cost) for aid, cost in spec.items()}


def _default_state(
    uncertainty: float = 0.5,
    n_concepts: int = 2,
) -> LearnerState:
    """Build a learner state with controllable uncertainty."""
    concepts: dict[str, ConceptState] = {}
    for i in range(n_concepts):
        cid = f"concept-{i}"
        concepts[cid] = ConceptState(
            concept_id=cid,
            mastery_estimate=1.0 - uncertainty,
            bkt=BKTParams(p_know=1.0 - uncertainty),
        )
    return LearnerState(learner_id="test-learner", concepts=concepts)


def _quiz_event(
    learner_id: str = "learner-1",
    concept_id: str = "algebra",
    score: float = 0.8,
) -> LearnerEvent:
    return LearnerEvent(
        event_id="evt-1",
        learner_id=learner_id,
        event_type=LearnerEventType.QUIZ_RESULT,
        concept_id=concept_id,
        data={"score": score, "max_score": 1.0},
    )


# ═══════════════════════════════════════════════════════════════════
# AdaptiveRouter Tests
# ═══════════════════════════════════════════════════════════════════


class TestRoutingDecision:
    """Basic RoutingDecision dataclass tests."""

    def test_fields(self) -> None:
        rd = RoutingDecision(
            selected_agents=["a"],
            skipped_agents=["b"],
            routing_rationale={"a": "yes", "b": "no"},
            total_cost=1.0,
            budget=10.0,
            uncertainty_score=0.5,
            full_pipeline=False,
        )
        assert rd.selected_agents == ["a"]
        assert rd.skipped_agents == ["b"]
        assert not rd.full_pipeline

    def test_full_pipeline_flag(self) -> None:
        rd = RoutingDecision(
            selected_agents=["a", "b"],
            skipped_agents=[],
            routing_rationale={},
            total_cost=2.0,
            budget=10.0,
            uncertainty_score=0.5,
            full_pipeline=True,
        )
        assert rd.full_pipeline
        assert len(rd.skipped_agents) == 0


class TestAgentNeedScore:
    """Test the internal _AgentNeedScore value density."""

    def test_value_density_normal(self) -> None:
        s = _AgentNeedScore(agent_id="a", need=0.8, cost=2)
        assert s.value_density == pytest.approx(0.4)

    def test_value_density_zero_cost(self) -> None:
        s = _AgentNeedScore(agent_id="a", need=0.5, cost=0)
        assert s.value_density == float("inf")

    def test_value_density_high_need(self) -> None:
        s = _AgentNeedScore(agent_id="a", need=1.0, cost=1)
        assert s.value_density == pytest.approx(1.0)


class TestAdaptiveRouter:
    """Adaptive router unit tests."""

    def test_full_pipeline_when_disabled(self) -> None:
        agents = _make_agents()
        router = AdaptiveRouter(agents=agents, enabled=False)
        state = _default_state()

        decision = router.route(state)

        assert decision.full_pipeline
        assert len(decision.skipped_agents) == 0
        assert set(decision.selected_agents) == set(agents.keys())

    def test_core_agents_always_selected(self) -> None:
        agents = _make_agents()
        router = AdaptiveRouter(agents=agents, enabled=True, budget=2.0)
        state = _default_state(uncertainty=0.0)

        decision = router.route(state)

        assert "diagnoser" in decision.selected_agents
        assert "motivation" in decision.selected_agents

    def test_budget_limits_selection(self) -> None:
        """With a tiny budget, only core agents should fit."""
        agents = _make_agents()
        router = AdaptiveRouter(agents=agents, enabled=True, budget=2.0)
        # Low uncertainty → low need for most agents
        state = _default_state(uncertainty=0.05)

        decision = router.route(state)

        # Core agents cost 1+1=2, budget is 2 → no room for others
        assert decision.total_cost <= 2.0 + 0.01
        assert "diagnoser" in decision.selected_agents
        assert "motivation" in decision.selected_agents

    def test_high_uncertainty_selects_more_agents(self) -> None:
        agents = _make_agents()
        router = AdaptiveRouter(agents=agents, enabled=True, budget=20.0)
        state = _default_state(uncertainty=0.8)

        decision = router.route(state)

        # High uncertainty + big budget should select many agents
        assert len(decision.selected_agents) > 4

    def test_full_pipeline_interval(self) -> None:
        """Every N turns, force full pipeline."""
        agents = _make_agents()
        router = AdaptiveRouter(
            agents=agents, enabled=True, budget=3.0,
            full_pipeline_interval=3,
        )
        state = _default_state(uncertainty=0.1)

        # Turns 1, 2 = normal routing; turn 3 = full pipeline
        d1 = router.route(state)
        d2 = router.route(state)
        d3 = router.route(state)

        assert not d1.full_pipeline
        assert not d2.full_pipeline
        assert d3.full_pipeline  # 3rd turn forces full
        assert set(d3.selected_agents) == set(agents.keys())

    def test_skipped_agents_have_rationale(self) -> None:
        agents = _make_agents()
        router = AdaptiveRouter(agents=agents, enabled=True, budget=3.0)
        state = _default_state(uncertainty=0.1)

        decision = router.route(state)

        for skipped in decision.skipped_agents:
            assert skipped in decision.routing_rationale
            assert "skip" in decision.routing_rationale[skipped]

    def test_selected_agents_have_rationale(self) -> None:
        agents = _make_agents()
        router = AdaptiveRouter(agents=agents, enabled=True, budget=20.0)
        state = _default_state(uncertainty=0.5)

        decision = router.route(state)

        for selected in decision.selected_agents:
            assert selected in decision.routing_rationale

    def test_total_cost_matches_selected(self) -> None:
        agents = _make_agents()
        router = AdaptiveRouter(agents=agents, enabled=True, budget=20.0)
        state = _default_state(uncertainty=0.5)

        decision = router.route(state)

        expected = sum(
            agents[aid].metadata.cost_tier
            for aid in decision.selected_agents
        )
        assert decision.total_cost == pytest.approx(expected)

    def test_uncertainty_score_in_decision(self) -> None:
        agents = _make_agents()
        router = AdaptiveRouter(agents=agents, enabled=True, budget=20.0)
        state = _default_state(uncertainty=0.42)

        decision = router.route(state)

        # The decision should record the uncertainty from the state
        assert decision.uncertainty_score == pytest.approx(
            state.average_uncertainty(), abs=0.01,
        )

    def test_turn_counter_increments(self) -> None:
        agents = _make_agents()
        router = AdaptiveRouter(agents=agents, enabled=True)
        state = _default_state()

        assert router.turn_counter == 0
        router.route(state)
        assert router.turn_counter == 1
        router.route(state)
        assert router.turn_counter == 2

    def test_turn_counter_settable(self) -> None:
        agents = _make_agents()
        router = AdaptiveRouter(agents=agents, enabled=True)

        router.turn_counter = 10
        assert router.turn_counter == 10

    def test_drift_increases_drift_detector_selection(self) -> None:
        agents = _make_agents()
        router = AdaptiveRouter(
            agents=agents, enabled=True, budget=5.0,
        )
        state = _default_state(uncertainty=0.1)

        # With drift, drift_detector more likely to be selected
        decision = router.route(state, recent_drift_count=3)
        assert "drift-detector" in decision.selected_agents

    def test_decay_risk_selects_decay_agents(self) -> None:
        agents = _make_agents()
        router = AdaptiveRouter(
            agents=agents, enabled=True, budget=8.0,
        )
        state = _default_state(uncertainty=0.2)

        decision = router.route(state, has_decay_risk=True)

        # Decay risk should select decay and possibly generative_replay
        assert "decay" in decision.selected_agents

    def test_low_need_agents_skipped(self) -> None:
        """Agents with need < 0.1 are always skipped."""
        agents = _make_agents()
        router = AdaptiveRouter(
            agents=agents, enabled=True, budget=20.0,
        )
        # p_know=1.0 → entropy uncertainty = 0.0 → base need ≈ 0
        # plus no drift, no anomalies, no decay
        concepts = {
            "c1": ConceptState(
                concept_id="c1",
                mastery_estimate=1.0,
                bkt=BKTParams(p_know=1.0),
            ),
        }
        state = LearnerState(learner_id="test", concepts=concepts)

        decision = router.route(state)

        # With zero uncertainty & no signals, some agents should be skipped
        assert len(decision.skipped_agents) > 0

    def test_empty_agents_returns_empty_selection(self) -> None:
        router = AdaptiveRouter(agents={}, enabled=True, budget=10.0)
        state = _default_state()

        decision = router.route(state)

        assert decision.selected_agents == []
        assert decision.skipped_agents == []


class TestAdaptiveRouterNeedScoring:
    """Test the _agent_need static method."""

    def test_core_agent_always_1(self) -> None:
        state = _default_state(uncertainty=0.0)
        need = AdaptiveRouter._agent_need(
            "diagnoser", 0.0, 0, 0, False, state,
        )
        assert need == 1.0

    def test_motivation_always_1(self) -> None:
        state = _default_state()
        need = AdaptiveRouter._agent_need(
            "motivation", 0.5, 0, 0, False, state,
        )
        assert need == 1.0

    def test_drift_detector_high_with_drift(self) -> None:
        state = _default_state()
        need = AdaptiveRouter._agent_need(
            "drift-detector", 0.2, 3, 0, False, state,
        )
        assert need >= 0.5

    def test_drift_detector_low_without_drift(self) -> None:
        state = _default_state(uncertainty=0.1)
        need = AdaptiveRouter._agent_need(
            "drift-detector", 0.1, 0, 0, False, state,
        )
        assert need <= 0.3

    def test_decay_high_with_risk(self) -> None:
        state = _default_state()
        need = AdaptiveRouter._agent_need(
            "decay", 0.2, 0, 0, True, state,
        )
        assert need >= 0.7

    def test_generative_replay_high_with_decay(self) -> None:
        state = _default_state()
        need = AdaptiveRouter._agent_need(
            "generative-replay", 0.2, 0, 0, True, state,
        )
        assert need >= 0.5

    def test_generative_replay_low_without_decay(self) -> None:
        state = _default_state()
        need = AdaptiveRouter._agent_need(
            "generative-replay", 0.2, 0, 0, False, state,
        )
        assert need < 0.2

    def test_behavior_high_with_anomalies(self) -> None:
        state = _default_state()
        need = AdaptiveRouter._agent_need(
            "behavior", 0.2, 0, 3, False, state,
        )
        assert need >= 0.5

    def test_reflection_moderate(self) -> None:
        state = _default_state()
        need = AdaptiveRouter._agent_need(
            "reflection", 0.5, 0, 0, False, state,
        )
        assert need == pytest.approx(0.4)

    def test_unknown_agent_gets_base_need(self) -> None:
        state = _default_state(uncertainty=0.5)
        need = AdaptiveRouter._agent_need(
            "unknown-agent", 0.5, 0, 0, False, state,
        )
        assert 0.0 < need < 1.0


# ═══════════════════════════════════════════════════════════════════
# ConfidenceCalibrator Tests
# ═══════════════════════════════════════════════════════════════════


class TestCalibrationRecord:
    """Basic CalibrationRecord data tests."""

    def test_fields(self) -> None:
        rec = CalibrationRecord(
            reported_confidence=0.8,
            actual_accuracy=0.7,
            timestamp_epoch=12345.0,
        )
        assert rec.reported_confidence == 0.8
        assert rec.actual_accuracy == 0.7
        assert rec.timestamp_epoch == 12345.0

    def test_default_timestamp(self) -> None:
        rec = CalibrationRecord(
            reported_confidence=0.5,
            actual_accuracy=0.5,
        )
        assert rec.timestamp_epoch == 0.0


class TestAgentCalibration:
    """AgentCalibration dataclass tests."""

    def test_observation_count_empty(self) -> None:
        cal = AgentCalibration(agent_id="test")
        assert cal.observation_count == 0
        assert cal.trust_weight == 1.0

    def test_observation_count_with_history(self) -> None:
        cal = AgentCalibration(
            agent_id="test",
            history=[
                CalibrationRecord(0.5, 0.5),
                CalibrationRecord(0.6, 0.6),
            ],
        )
        assert cal.observation_count == 2


class TestConfidenceCalibrator:
    """Confidence calibrator unit tests."""

    def test_cold_start_returns_raw(self) -> None:
        """With no history, calibrate returns raw confidence."""
        cal = ConfidenceCalibrator()
        result = cal.calibrate("agent-a", 0.75)
        assert result == 0.75

    def test_cold_start_below_min_obs(self) -> None:
        """Fewer than min_observations → no adjustment."""
        cal = ConfidenceCalibrator(min_observations=3)
        cal.record_outcome("agent-a", 0.8, 0.8)
        cal.record_outcome("agent-a", 0.8, 0.8)
        # Only 2 observations, need 3
        result = cal.calibrate("agent-a", 0.75)
        assert result == 0.75

    def test_perfectly_calibrated_agent(self) -> None:
        """Agent that always reports correctly → trust_weight ≈ 1.0."""
        cal = ConfidenceCalibrator(min_observations=3)
        for _ in range(5):
            cal.record_outcome("agent-a", 0.8, 0.8)

        weight = cal.get_trust_weight("agent-a")
        assert weight == pytest.approx(1.0, abs=0.01)

        result = cal.calibrate("agent-a", 0.9)
        assert result == pytest.approx(0.9, abs=0.02)

    def test_over_confident_agent_downweighted(self) -> None:
        """Agent reports 0.9 but actual is 0.6 → trust decreases."""
        cal = ConfidenceCalibrator(min_observations=3)
        for _ in range(5):
            cal.record_outcome("agent-a", 0.9, 0.6)

        weight = cal.get_trust_weight("agent-a")
        assert weight < 1.0
        # ratio = 0.6/0.9 ≈ 0.667 → weight should be ~0.667
        assert weight == pytest.approx(0.667, abs=0.05)

        result = cal.calibrate("agent-a", 0.9)
        assert result < 0.9

    def test_under_confident_agent_upweighted(self) -> None:
        """Agent reports 0.5 but actual is 0.8 → trust increases."""
        cal = ConfidenceCalibrator(min_observations=3)
        for _ in range(5):
            cal.record_outcome("agent-a", 0.5, 0.8)

        weight = cal.get_trust_weight("agent-a")
        assert weight > 1.0
        # ratio = 0.8/0.5 = 1.6 → clamped to 1.5
        assert weight == pytest.approx(1.5, abs=0.05)

    def test_trust_weight_clamped_low(self) -> None:
        """Very over-confident agent is clamped to 0.3."""
        cal = ConfidenceCalibrator(min_observations=3)
        for _ in range(5):
            cal.record_outcome("agent-a", 0.9, 0.1)

        weight = cal.get_trust_weight("agent-a")
        assert weight >= 0.3

    def test_trust_weight_clamped_high(self) -> None:
        """Very under-confident agent is clamped to 1.5."""
        cal = ConfidenceCalibrator(min_observations=3)
        for _ in range(5):
            cal.record_outcome("agent-a", 0.1, 0.9)

        weight = cal.get_trust_weight("agent-a")
        assert weight <= 1.5

    def test_calibrate_clamped_to_01(self) -> None:
        """Calibrated confidence clamped to [0, 1]."""
        cal = ConfidenceCalibrator(min_observations=3)
        for _ in range(5):
            cal.record_outcome("agent-a", 0.5, 0.8)

        # High raw * high trust could exceed 1.0
        result = cal.calibrate("agent-a", 0.95)
        assert result <= 1.0
        assert result >= 0.0

    def test_decay_weights_recent_more(self) -> None:
        """More recent observations should count more."""
        cal = ConfidenceCalibrator(decay_factor=0.5, min_observations=3)
        # First 3: agent is well-calibrated
        for _ in range(3):
            cal.record_outcome("agent-a", 0.8, 0.8)
        # Next 3: agent becomes over-confident
        for _ in range(3):
            cal.record_outcome("agent-a", 0.8, 0.4)

        # With decay=0.5, recent (over-confident) should dominate
        weight = cal.get_trust_weight("agent-a")
        assert weight < 0.7  # Skews toward recent 0.4/0.8=0.5 ratio

    def test_max_history_trimming(self) -> None:
        """History is trimmed to max_history."""
        cal = ConfidenceCalibrator(max_history=5, min_observations=3)
        for _ in range(10):
            cal.record_outcome("agent-a", 0.8, 0.6)

        agent_cal = cal._agents["agent-a"]
        assert len(agent_cal.history) == 5

    def test_multiple_agents_independent(self) -> None:
        """Calibration is per-agent."""
        cal = ConfidenceCalibrator(min_observations=3)
        for _ in range(5):
            cal.record_outcome("agent-a", 0.8, 0.8)
            cal.record_outcome("agent-b", 0.8, 0.4)

        weight_a = cal.get_trust_weight("agent-a")
        weight_b = cal.get_trust_weight("agent-b")

        assert weight_a > weight_b
        assert weight_a == pytest.approx(1.0, abs=0.05)
        assert weight_b < 0.7

    def test_get_all_weights(self) -> None:
        cal = ConfidenceCalibrator(min_observations=3)
        for _ in range(5):
            cal.record_outcome("agent-a", 0.8, 0.8)
            cal.record_outcome("agent-b", 0.8, 0.4)

        weights = cal.get_all_weights()
        assert "agent-a" in weights
        assert "agent-b" in weights

    def test_get_all_weights_empty(self) -> None:
        cal = ConfidenceCalibrator()
        weights = cal.get_all_weights()
        assert weights == {}

    def test_tracked_agents(self) -> None:
        cal = ConfidenceCalibrator()
        cal.record_outcome("agent-a", 0.5, 0.5)
        cal.record_outcome("agent-b", 0.5, 0.5)

        assert set(cal.tracked_agents) == {"agent-a", "agent-b"}

    def test_reset_single(self) -> None:
        cal = ConfidenceCalibrator()
        cal.record_outcome("agent-a", 0.5, 0.5)
        cal.record_outcome("agent-b", 0.5, 0.5)

        cal.reset("agent-a")
        assert "agent-a" not in cal.tracked_agents
        assert "agent-b" in cal.tracked_agents

    def test_reset_all(self) -> None:
        cal = ConfidenceCalibrator()
        cal.record_outcome("agent-a", 0.5, 0.5)
        cal.record_outcome("agent-b", 0.5, 0.5)

        cal.reset()
        assert cal.tracked_agents == []

    def test_get_trust_weight_unknown_agent(self) -> None:
        cal = ConfidenceCalibrator()
        assert cal.get_trust_weight("nonexistent") == 1.0

    def test_calibration_summary(self) -> None:
        cal = ConfidenceCalibrator(min_observations=3)
        for _ in range(5):
            cal.record_outcome("agent-a", 0.8, 0.6)

        summary = cal.get_calibration_summary()
        assert "agent-a" in summary
        assert summary["agent-a"]["observations"] == 5
        assert 0.0 < summary["agent-a"]["trust_weight"] < 1.0

    def test_near_zero_confidence_no_penalty(self) -> None:
        """Near-zero reported confidence doesn't cause division issues."""
        cal = ConfidenceCalibrator(min_observations=3)
        for _ in range(5):
            cal.record_outcome("agent-a", 0.005, 0.5)

        weight = cal.get_trust_weight("agent-a")
        assert math.isfinite(weight)


# ═══════════════════════════════════════════════════════════════════
# GPS Engine Integration Tests
# ═══════════════════════════════════════════════════════════════════


@pytest.fixture()
def memory_store(tmp_path) -> LocalJsonMemoryStore:
    return LocalJsonMemoryStore(data_dir=tmp_path)


@pytest.fixture()
def portfolio_logger(tmp_path) -> LocalJsonPortfolioLogger:
    return LocalJsonPortfolioLogger(data_dir=tmp_path)


@pytest.fixture()
def event_bus() -> InMemoryEventBus:
    return InMemoryEventBus()


@pytest.fixture()
def engine_routing_disabled(
    memory_store, portfolio_logger, event_bus,
) -> LearningGPSEngine:
    """Engine with routing disabled — all agents always run."""
    return LearningGPSEngine(
        memory_store=memory_store,
        portfolio_logger=portfolio_logger,
        event_bus=event_bus,
        adaptive_routing_enabled=False,
    )


@pytest.fixture()
def engine_routing_enabled(
    memory_store, portfolio_logger, event_bus,
) -> LearningGPSEngine:
    """Engine with routing enabled."""
    return LearningGPSEngine(
        memory_store=memory_store,
        portfolio_logger=portfolio_logger,
        event_bus=event_bus,
        adaptive_routing_enabled=True,
        cost_budget_per_turn=20.0,
    )


@pytest.fixture()
def engine_routing_tight_budget(
    memory_store, portfolio_logger, event_bus,
) -> LearningGPSEngine:
    """Engine with routing enabled and very tight budget."""
    return LearningGPSEngine(
        memory_store=memory_store,
        portfolio_logger=portfolio_logger,
        event_bus=event_bus,
        adaptive_routing_enabled=True,
        cost_budget_per_turn=2.0,
    )


class TestGPSEngineAdaptiveRouting:
    """Integration tests for adaptive routing in the engine."""

    @pytest.mark.asyncio()
    async def test_routing_disabled_runs_all_agents(
        self, engine_routing_disabled,
    ) -> None:
        event = _quiz_event()
        result = await engine_routing_disabled.process_event(event)

        assert isinstance(result, NextBestAction)
        # With routing disabled, debug_trace should have routing info
        routing = result.debug_trace.get("routing", {})
        assert routing.get("full_pipeline") is True
        assert len(routing.get("skipped", [])) == 0

    @pytest.mark.asyncio()
    async def test_routing_enabled_has_routing_trace(
        self, engine_routing_enabled,
    ) -> None:
        event = _quiz_event()
        result = await engine_routing_enabled.process_event(event)

        assert isinstance(result, NextBestAction)
        routing = result.debug_trace.get("routing", {})
        assert "selected" in routing
        assert "skipped" in routing
        assert "uncertainty" in routing
        assert "budget" in routing

    @pytest.mark.asyncio()
    async def test_routing_enabled_produces_valid_nba(
        self, engine_routing_enabled,
    ) -> None:
        event = _quiz_event()
        result = await engine_routing_enabled.process_event(event)

        assert isinstance(result, NextBestAction)
        assert result.learner_id == "learner-1"
        assert 0.0 <= result.confidence <= 1.0

    @pytest.mark.asyncio()
    async def test_tight_budget_skips_agents(
        self, engine_routing_tight_budget,
    ) -> None:
        """With budget=2, many agents must be skipped."""
        event = _quiz_event()
        result = await engine_routing_tight_budget.process_event(event)

        assert isinstance(result, NextBestAction)
        routing = result.debug_trace.get("routing", {})
        # Tight budget should skip some agents
        assert len(routing.get("skipped", [])) > 0

    @pytest.mark.asyncio()
    async def test_pipeline_steps_record_skipped(
        self, engine_routing_tight_budget,
    ) -> None:
        """Skipped agents appear in pipeline_steps with skipped=True."""
        event = _quiz_event()
        result = await engine_routing_tight_budget.process_event(event)

        steps = result.debug_trace.get("pipeline_steps", [])
        skipped_steps = [s for s in steps if s.get("skipped")]
        # At least some steps should be marked as skipped
        assert len(skipped_steps) >= 1

    @pytest.mark.asyncio()
    async def test_core_agents_always_in_trace(
        self, engine_routing_tight_budget,
    ) -> None:
        """Diagnoser and motivation always run even with tight budget."""
        event = _quiz_event()
        result = await engine_routing_tight_budget.process_event(event)

        steps = result.debug_trace.get("pipeline_steps", [])
        agent_names = [s.get("agent") for s in steps]
        assert "diagnoser" in agent_names
        assert "motivation" in agent_names

        # They should NOT be skipped
        for step in steps:
            if step.get("agent") in ("diagnoser", "motivation"):
                assert not step.get("skipped", False)

    @pytest.mark.asyncio()
    async def test_engine_has_adaptive_router(
        self, engine_routing_enabled,
    ) -> None:
        assert hasattr(engine_routing_enabled, "adaptive_router")
        assert isinstance(
            engine_routing_enabled.adaptive_router, AdaptiveRouter,
        )

    @pytest.mark.asyncio()
    async def test_engine_has_confidence_calibrator(
        self, engine_routing_enabled,
    ) -> None:
        assert hasattr(engine_routing_enabled, "confidence_calibrator")
        assert isinstance(
            engine_routing_enabled.confidence_calibrator,
            ConfidenceCalibrator,
        )


class TestGPSEngineConfidenceCalibration:
    """Integration tests for confidence calibration in the engine."""

    @pytest.mark.asyncio()
    async def test_cold_start_no_adjustment(
        self, engine_routing_disabled,
    ) -> None:
        """With no calibration history, confidence passes through."""
        event = _quiz_event()
        result = await engine_routing_disabled.process_event(event)

        # Cold start: calibrator returns raw confidence (no adjustment)
        assert 0.0 <= result.confidence <= 1.0

    @pytest.mark.asyncio()
    async def test_calibrator_affects_confidence(
        self, engine_routing_disabled,
    ) -> None:
        """After recording outcomes, calibrator adjusts confidence."""
        engine = engine_routing_disabled
        # Record outcomes indicating engine is over-confident
        for _ in range(5):
            engine.confidence_calibrator.record_outcome(
                "engine", 0.9, 0.4,
            )

        event = _quiz_event()
        result = await engine.process_event(event)

        # Confidence should be scaled down
        # The maker-checker typically returns ~0.5-0.8 confidence,
        # and with a trust_weight of ~0.44, it should be < 0.5
        assert result.confidence < 0.6

    @pytest.mark.asyncio()
    async def test_multiple_events_are_stable(
        self, engine_routing_enabled,
    ) -> None:
        """Multiple events process without errors."""
        for i in range(3):
            event = _quiz_event(
                learner_id="learner-multi",
                concept_id=f"concept-{i}",
            )
            result = await engine_routing_enabled.process_event(event)
            assert isinstance(result, NextBestAction)
            assert 0.0 <= result.confidence <= 1.0
