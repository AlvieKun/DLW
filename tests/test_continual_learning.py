"""Tests for Phase 5: Decay Agent + Generative Replay Agent."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from learning_navigator.agents.decay import DecayAgent
from learning_navigator.agents.generative_replay import GenerativeReplayAgent
from learning_navigator.contracts.learner_state import (
    BKTParams,
    ConceptRelation,
    ConceptRelationType,
    ConceptState,
    LearnerState,
)
from learning_navigator.contracts.messages import MessageEnvelope, MessageType

# ── Helpers ────────────────────────────────────────────────────────


def _make_state(**overrides) -> LearnerState:
    defaults = {"learner_id": "test-learner"}
    defaults.update(overrides)
    return LearnerState(**defaults)


def _concept(
    cid: str,
    mastery: float = 0.5,
    last_practiced: datetime | None = None,
    practice_count: int = 0,
    difficulty: float = 0.5,
    forgetting_score: float = 0.0,
    spacing_history: list[float] | None = None,
) -> ConceptState:
    return ConceptState(
        concept_id=cid,
        bkt=BKTParams(p_know=mastery),
        last_practiced=last_practiced,
        practice_count=practice_count,
        difficulty=difficulty,
        forgetting_score=forgetting_score,
        spacing_history=spacing_history or [],
    )


def _prereq(src: str, tgt: str) -> ConceptRelation:
    return ConceptRelation(
        source_concept_id=src,
        target_concept_id=tgt,
        relation_type=ConceptRelationType.PREREQUISITE,
    )


def _related(src: str, tgt: str) -> ConceptRelation:
    return ConceptRelation(
        source_concept_id=src,
        target_concept_id=tgt,
        relation_type=ConceptRelationType.RELATED,
    )


def _decay_msg(payload: dict) -> MessageEnvelope:
    return MessageEnvelope(
        message_type=MessageType.DECAY_REQUEST,
        source_agent_id="engine",
        target_agent_id="decay",
        payload=payload,
    )


def _replay_msg(payload: dict) -> MessageEnvelope:
    return MessageEnvelope(
        message_type=MessageType.REPLAY_REQUEST,
        source_agent_id="engine",
        target_agent_id="generative-replay",
        payload=payload,
    )


# ══════════════════════════════════════════════════════════════════
#  Decay Agent Tests
# ══════════════════════════════════════════════════════════════════


class TestDecayAgent:
    @pytest.fixture()
    def agent(self) -> DecayAgent:
        return DecayAgent()

    @pytest.mark.asyncio()
    async def test_metadata(self, agent: DecayAgent) -> None:
        assert agent.agent_id == "decay"
        assert agent.metadata.cost_tier == 1

    @pytest.mark.asyncio()
    async def test_empty_state(self, agent: DecayAgent) -> None:
        state = _make_state()
        msg = _decay_msg({"learner_state": state.model_dump(mode="json")})
        resp = await agent.handle(msg)
        assert resp.payload["summary"]["total_concepts"] == 0
        assert resp.payload["at_risk"] == []
        assert resp.payload["review_schedule"] == []

    @pytest.mark.asyncio()
    async def test_recently_practiced_low_forgetting(self, agent: DecayAgent) -> None:
        """A concept practiced 1 hour ago should have low forgetting."""
        now = datetime.now(timezone.utc)
        state = _make_state()
        state.upsert_concept(
            _concept("algebra", mastery=0.7, last_practiced=now - timedelta(hours=1), practice_count=5)
        )
        msg = _decay_msg({"learner_state": state.model_dump(mode="json")})
        resp = await agent.handle(msg)

        report = resp.payload["concept_reports"]["algebra"]
        assert report["forgetting_score"] < 0.2
        assert report["retention"] > 0.8
        assert resp.payload["at_risk_count"] == 0

    @pytest.mark.asyncio()
    async def test_long_ago_practiced_high_forgetting(self, agent: DecayAgent) -> None:
        """A concept practiced 200 hours ago with no repetitions should have high forgetting."""
        now = datetime.now(timezone.utc)
        state = _make_state()
        state.upsert_concept(
            _concept("biology", mastery=0.5, last_practiced=now - timedelta(hours=200), practice_count=1)
        )
        msg = _decay_msg({"learner_state": state.model_dump(mode="json")})
        resp = await agent.handle(msg)

        report = resp.payload["concept_reports"]["biology"]
        assert report["forgetting_score"] > 0.5
        assert resp.payload["at_risk_count"] == 1

    @pytest.mark.asyncio()
    async def test_never_practiced_max_forgetting(self, agent: DecayAgent) -> None:
        """A never-practiced concept should have very high forgetting."""
        state = _make_state()
        state.upsert_concept(_concept("physics", mastery=0.3, last_practiced=None, practice_count=0))
        msg = _decay_msg({"learner_state": state.model_dump(mode="json")})
        resp = await agent.handle(msg)

        report = resp.payload["concept_reports"]["physics"]
        assert report["forgetting_score"] > 0.9
        assert report["hours_since_practice"] == 720.0  # 30 days default

    @pytest.mark.asyncio()
    async def test_high_repetition_increases_stability(self, agent: DecayAgent) -> None:
        """More practice reps should increase stability, reducing forgetting at same time gap."""
        now = datetime.now(timezone.utc)
        state = _make_state()

        # Low reps
        state.upsert_concept(
            _concept("c1", mastery=0.6, last_practiced=now - timedelta(hours=48), practice_count=1)
        )
        # High reps
        state.upsert_concept(
            _concept("c2", mastery=0.6, last_practiced=now - timedelta(hours=48), practice_count=15)
        )

        msg = _decay_msg({"learner_state": state.model_dump(mode="json")})
        resp = await agent.handle(msg)

        r1 = resp.payload["concept_reports"]["c1"]
        r2 = resp.payload["concept_reports"]["c2"]
        assert r2["stability_hours"] > r1["stability_hours"]
        assert r2["forgetting_score"] < r1["forgetting_score"]

    @pytest.mark.asyncio()
    async def test_expanding_spacing_boosts_stability(self, agent: DecayAgent) -> None:
        """Expanding spacing intervals should give higher stability than contracting."""
        now = datetime.now(timezone.utc)
        state = _make_state()

        # Expanding intervals
        state.upsert_concept(
            _concept("expanding", mastery=0.6, last_practiced=now - timedelta(hours=24),
                     practice_count=4, spacing_history=[6, 12, 24, 48])
        )
        # Contracting intervals
        state.upsert_concept(
            _concept("contracting", mastery=0.6, last_practiced=now - timedelta(hours=24),
                     practice_count=4, spacing_history=[48, 24, 12, 6])
        )

        msg = _decay_msg({"learner_state": state.model_dump(mode="json")})
        resp = await agent.handle(msg)

        r_exp = resp.payload["concept_reports"]["expanding"]
        r_con = resp.payload["concept_reports"]["contracting"]
        assert r_exp["stability_hours"] > r_con["stability_hours"]

    @pytest.mark.asyncio()
    async def test_difficulty_affects_stability(self, agent: DecayAgent) -> None:
        """Easy concepts should have higher stability than hard ones."""
        now = datetime.now(timezone.utc)
        state = _make_state()

        state.upsert_concept(
            _concept("easy", mastery=0.6, last_practiced=now - timedelta(hours=24),
                     practice_count=3, difficulty=0.1)
        )
        state.upsert_concept(
            _concept("hard", mastery=0.6, last_practiced=now - timedelta(hours=24),
                     practice_count=3, difficulty=0.9)
        )

        msg = _decay_msg({"learner_state": state.model_dump(mode="json")})
        resp = await agent.handle(msg)

        assert resp.payload["concept_reports"]["easy"]["stability_hours"] > \
               resp.payload["concept_reports"]["hard"]["stability_hours"]

    @pytest.mark.asyncio()
    async def test_review_schedule_sorted_by_urgency(self, agent: DecayAgent) -> None:
        """Review schedule should be sorted by urgency (forgetting) descending."""
        now = datetime.now(timezone.utc)
        state = _make_state()

        state.upsert_concept(_concept("fresh", mastery=0.8, last_practiced=now - timedelta(hours=1), practice_count=5))
        state.upsert_concept(_concept("stale", mastery=0.5, last_practiced=now - timedelta(hours=100), practice_count=1))

        msg = _decay_msg({"learner_state": state.model_dump(mode="json")})
        resp = await agent.handle(msg)

        schedule = resp.payload["review_schedule"]
        assert len(schedule) == 2
        assert schedule[0]["concept_id"] == "stale"
        assert schedule[0]["urgency"] >= schedule[1]["urgency"]

    @pytest.mark.asyncio()
    async def test_review_action_types(self, agent: DecayAgent) -> None:
        """Review actions should match mastery and forgetting levels."""
        now = datetime.now(timezone.utc)
        state = _make_state()

        # Urgent review: high forgetting
        state.upsert_concept(_concept("urgent", mastery=0.5, last_practiced=now - timedelta(hours=300), practice_count=1))
        # Learn new: low mastery
        state.upsert_concept(_concept("new", mastery=0.2, last_practiced=now - timedelta(hours=2), practice_count=1))

        msg = _decay_msg({"learner_state": state.model_dump(mode="json")})
        resp = await agent.handle(msg)

        schedule = {r["concept_id"]: r for r in resp.payload["review_schedule"]}
        assert schedule["urgent"]["action"] in ("urgent_review", "spaced_review")
        assert schedule["new"]["action"] == "learn_new"

    @pytest.mark.asyncio()
    async def test_confidence_scales_with_concepts(self, agent: DecayAgent) -> None:
        """More concepts should give higher confidence."""
        now = datetime.now(timezone.utc)
        state = _make_state()
        for i in range(10):
            state.upsert_concept(_concept(f"c{i}", mastery=0.5, last_practiced=now, practice_count=1))

        msg = _decay_msg({"learner_state": state.model_dump(mode="json")})
        resp = await agent.handle(msg)
        assert resp.confidence >= 0.8

    @pytest.mark.asyncio()
    async def test_next_review_hours_positive(self, agent: DecayAgent) -> None:
        """Next review time should always be positive."""
        now = datetime.now(timezone.utc)
        state = _make_state()
        state.upsert_concept(_concept("c1", mastery=0.6, last_practiced=now, practice_count=3))

        msg = _decay_msg({"learner_state": state.model_dump(mode="json")})
        resp = await agent.handle(msg)

        report = resp.payload["concept_reports"]["c1"]
        assert report["next_review_hours"] > 0

    @pytest.mark.asyncio()
    async def test_stability_floor(self, agent: DecayAgent) -> None:
        """Stability should never go below 1 hour."""
        now = datetime.now(timezone.utc)
        state = _make_state()
        # Hard concept, no reps, low mastery -> stability floored
        state.upsert_concept(_concept("floor", mastery=0.1, difficulty=1.0, last_practiced=now, practice_count=0))

        msg = _decay_msg({"learner_state": state.model_dump(mode="json")})
        resp = await agent.handle(msg)

        assert resp.payload["concept_reports"]["floor"]["stability_hours"] >= 1.0


# ══════════════════════════════════════════════════════════════════
#  Generative Replay Agent Tests
# ══════════════════════════════════════════════════════════════════


class TestGenerativeReplayAgent:
    @pytest.fixture()
    def agent(self) -> GenerativeReplayAgent:
        return GenerativeReplayAgent()

    @pytest.mark.asyncio()
    async def test_metadata(self, agent: GenerativeReplayAgent) -> None:
        assert agent.agent_id == "generative-replay"
        assert agent.metadata.cost_tier == 2

    @pytest.mark.asyncio()
    async def test_empty_state(self, agent: GenerativeReplayAgent) -> None:
        state = _make_state()
        msg = _replay_msg({
            "learner_state": state.model_dump(mode="json"),
            "decay_report": {},
        })
        resp = await agent.handle(msg)
        assert resp.payload["replay_plan"] == []
        assert resp.payload["total_exercises"] == 0

    @pytest.mark.asyncio()
    async def test_no_replay_when_all_retained(self, agent: GenerativeReplayAgent) -> None:
        """Concepts with low forgetting scores should not trigger replay."""
        state = _make_state()
        state.upsert_concept(_concept("c1", mastery=0.8, forgetting_score=0.1))

        msg = _replay_msg({
            "learner_state": state.model_dump(mode="json"),
            "decay_report": {
                "concept_reports": {"c1": {"forgetting_score": 0.1}},
            },
        })
        resp = await agent.handle(msg)
        assert resp.payload["replay_plan"] == []

    @pytest.mark.asyncio()
    async def test_replay_generated_for_at_risk(self, agent: GenerativeReplayAgent) -> None:
        """Concepts above forgetting threshold with sufficient mastery get exercises."""
        state = _make_state()
        state.upsert_concept(_concept("c1", mastery=0.6, forgetting_score=0.6))

        msg = _replay_msg({
            "learner_state": state.model_dump(mode="json"),
            "decay_report": {
                "concept_reports": {"c1": {"forgetting_score": 0.6}},
            },
        })
        resp = await agent.handle(msg)

        assert resp.payload["concepts_targeted"] == 1
        assert resp.payload["total_exercises"] >= 2
        plan = resp.payload["replay_plan"][0]
        assert plan["concept_id"] == "c1"
        assert len(plan["exercises"]) >= 2

    @pytest.mark.asyncio()
    async def test_no_replay_for_very_low_mastery(self, agent: GenerativeReplayAgent) -> None:
        """Concepts with mastery below min_mastery_for_replay should not get replay."""
        state = _make_state()
        state.upsert_concept(_concept("c1", mastery=0.1, forgetting_score=0.8))

        msg = _replay_msg({
            "learner_state": state.model_dump(mode="json"),
            "decay_report": {
                "concept_reports": {"c1": {"forgetting_score": 0.8}},
            },
        })
        resp = await agent.handle(msg)
        assert resp.payload["replay_plan"] == []

    @pytest.mark.asyncio()
    async def test_fragility_ordering(self, agent: GenerativeReplayAgent) -> None:
        """Higher fragility concepts should appear first in replay plan."""
        state = _make_state()
        # High fragility: high mastery * high forgetting
        state.upsert_concept(_concept("fragile", mastery=0.8, forgetting_score=0.7))
        # Lower fragility: medium mastery * medium forgetting
        state.upsert_concept(_concept("moderate", mastery=0.5, forgetting_score=0.5))

        msg = _replay_msg({
            "learner_state": state.model_dump(mode="json"),
            "decay_report": {
                "concept_reports": {
                    "fragile": {"forgetting_score": 0.7},
                    "moderate": {"forgetting_score": 0.5},
                },
            },
        })
        resp = await agent.handle(msg)

        plan = resp.payload["replay_plan"]
        assert len(plan) == 2
        assert plan[0]["concept_id"] == "fragile"
        assert plan[0]["fragility"] > plan[1]["fragility"]

    @pytest.mark.asyncio()
    async def test_exercise_types_vary_with_mastery(self, agent: GenerativeReplayAgent) -> None:
        """Low mastery should get recognition exercises; high mastery should get synthesis."""
        state = _make_state()
        state.upsert_concept(_concept("low", mastery=0.3, forgetting_score=0.6))
        state.upsert_concept(_concept("high", mastery=0.8, forgetting_score=0.6))

        msg = _replay_msg({
            "learner_state": state.model_dump(mode="json"),
            "decay_report": {
                "concept_reports": {
                    "low": {"forgetting_score": 0.6},
                    "high": {"forgetting_score": 0.6},
                },
            },
        })
        resp = await agent.handle(msg)

        plans = {p["concept_id"]: p for p in resp.payload["replay_plan"]}
        low_types = {e["type"] for e in plans["low"]["exercises"]}
        high_types = {e["type"] for e in plans["high"]["exercises"]}
        assert "recognition" in low_types
        assert "synthesis" in high_types

    @pytest.mark.asyncio()
    async def test_exercise_difficulty_calibrated(self, agent: GenerativeReplayAgent) -> None:
        """Exercise difficulty should be in a reasonable range near mastery."""
        state = _make_state()
        state.upsert_concept(_concept("c1", mastery=0.6, forgetting_score=0.5, difficulty=0.5))

        msg = _replay_msg({
            "learner_state": state.model_dump(mode="json"),
            "decay_report": {
                "concept_reports": {"c1": {"forgetting_score": 0.5}},
            },
        })
        resp = await agent.handle(msg)

        exercises = resp.payload["replay_plan"][0]["exercises"]
        for ex in exercises:
            assert 0.05 <= ex["difficulty"] <= 0.95

    @pytest.mark.asyncio()
    async def test_max_replay_concepts_cap(self, agent: GenerativeReplayAgent) -> None:
        """Should not exceed max_replay_concepts."""
        state = _make_state()
        for i in range(15):
            state.upsert_concept(_concept(f"c{i}", mastery=0.5, forgetting_score=0.7))

        msg = _replay_msg({
            "learner_state": state.model_dump(mode="json"),
            "decay_report": {
                "concept_reports": {f"c{i}": {"forgetting_score": 0.7} for i in range(15)},
            },
        })
        resp = await agent.handle(msg)
        assert resp.payload["concepts_targeted"] <= 8

    @pytest.mark.asyncio()
    async def test_interleaved_sets_for_related_concepts(self, agent: GenerativeReplayAgent) -> None:
        """Related concepts should produce interleaved practice sets."""
        state = _make_state()
        state.upsert_concept(_concept("algebra", mastery=0.6, forgetting_score=0.6))
        state.upsert_concept(_concept("calculus", mastery=0.5, forgetting_score=0.5))
        state.concept_relations.append(_prereq("algebra", "calculus"))

        msg = _replay_msg({
            "learner_state": state.model_dump(mode="json"),
            "decay_report": {
                "concept_reports": {
                    "algebra": {"forgetting_score": 0.6},
                    "calculus": {"forgetting_score": 0.5},
                },
            },
        })
        resp = await agent.handle(msg)

        interleaved = resp.payload["interleaved_sets"]
        assert len(interleaved) >= 1
        concepts_in_sets = interleaved[0]["concepts"]
        assert "algebra" in concepts_in_sets
        assert "calculus" in concepts_in_sets

    @pytest.mark.asyncio()
    async def test_no_interleaving_single_concept(self, agent: GenerativeReplayAgent) -> None:
        """With only one concept, no interleaved sets should be generated."""
        state = _make_state()
        state.upsert_concept(_concept("c1", mastery=0.6, forgetting_score=0.6))

        msg = _replay_msg({
            "learner_state": state.model_dump(mode="json"),
            "decay_report": {
                "concept_reports": {"c1": {"forgetting_score": 0.6}},
            },
        })
        resp = await agent.handle(msg)
        assert resp.payload["interleaved_sets"] == []

    @pytest.mark.asyncio()
    async def test_fallback_to_state_forgetting_score(self, agent: GenerativeReplayAgent) -> None:
        """When decay_report has no data for a concept, use state's forgetting_score."""
        state = _make_state()
        state.upsert_concept(_concept("c1", mastery=0.6, forgetting_score=0.6))

        msg = _replay_msg({
            "learner_state": state.model_dump(mode="json"),
            "decay_report": {},  # no concept_reports
        })
        resp = await agent.handle(msg)

        assert resp.payload["concepts_targeted"] == 1
        assert resp.payload["total_exercises"] >= 2

    @pytest.mark.asyncio()
    async def test_exercise_has_expected_fields(self, agent: GenerativeReplayAgent) -> None:
        """Each exercise should contain all expected fields."""
        state = _make_state()
        state.upsert_concept(_concept("c1", mastery=0.5, forgetting_score=0.5))

        msg = _replay_msg({
            "learner_state": state.model_dump(mode="json"),
            "decay_report": {"concept_reports": {"c1": {"forgetting_score": 0.5}}},
        })
        resp = await agent.handle(msg)

        ex = resp.payload["replay_plan"][0]["exercises"][0]
        assert "exercise_index" in ex
        assert "type" in ex
        assert "target_concept" in ex
        assert "difficulty" in ex
        assert "estimated_minutes" in ex
        assert "hints_available" in ex

    @pytest.mark.asyncio()
    async def test_estimated_minutes_positive(self, agent: GenerativeReplayAgent) -> None:
        """All exercise types should have positive estimated minutes."""
        state = _make_state()
        state.upsert_concept(_concept("c1", mastery=0.5, forgetting_score=0.5))

        msg = _replay_msg({
            "learner_state": state.model_dump(mode="json"),
            "decay_report": {"concept_reports": {"c1": {"forgetting_score": 0.5}}},
        })
        resp = await agent.handle(msg)

        for ex in resp.payload["replay_plan"][0]["exercises"]:
            assert ex["estimated_minutes"] > 0

    @pytest.mark.asyncio()
    async def test_higher_forgetting_more_exercises(self, agent: GenerativeReplayAgent) -> None:
        """Higher forgetting should produce more exercises per concept."""
        state = _make_state()
        state.upsert_concept(_concept("low_f", mastery=0.6, forgetting_score=0.35))
        state.upsert_concept(_concept("high_f", mastery=0.6, forgetting_score=0.95))

        msg = _replay_msg({
            "learner_state": state.model_dump(mode="json"),
            "decay_report": {
                "concept_reports": {
                    "low_f": {"forgetting_score": 0.35},
                    "high_f": {"forgetting_score": 0.95},
                },
            },
        })
        resp = await agent.handle(msg)

        plans = {p["concept_id"]: p for p in resp.payload["replay_plan"]}
        assert len(plans["high_f"]["exercises"]) >= len(plans["low_f"]["exercises"])

    @pytest.mark.asyncio()
    async def test_hints_for_low_mastery(self, agent: GenerativeReplayAgent) -> None:
        """Exercises for concepts with mastery < 0.5 should have hints enabled."""
        state = _make_state()
        state.upsert_concept(_concept("c1", mastery=0.35, forgetting_score=0.5))

        msg = _replay_msg({
            "learner_state": state.model_dump(mode="json"),
            "decay_report": {"concept_reports": {"c1": {"forgetting_score": 0.5}}},
        })
        resp = await agent.handle(msg)

        for ex in resp.payload["replay_plan"][0]["exercises"]:
            assert ex["hints_available"] is True

    @pytest.mark.asyncio()
    async def test_interleaved_with_related_relation(self, agent: GenerativeReplayAgent) -> None:
        """RELATED relation type should also trigger interleaving."""
        state = _make_state()
        state.upsert_concept(_concept("a", mastery=0.6, forgetting_score=0.5))
        state.upsert_concept(_concept("b", mastery=0.5, forgetting_score=0.5))
        state.concept_relations.append(_related("a", "b"))

        msg = _replay_msg({
            "learner_state": state.model_dump(mode="json"),
            "decay_report": {
                "concept_reports": {
                    "a": {"forgetting_score": 0.5},
                    "b": {"forgetting_score": 0.5},
                },
            },
        })
        resp = await agent.handle(msg)

        interleaved = resp.payload["interleaved_sets"]
        assert len(interleaved) >= 1
