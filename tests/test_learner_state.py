"""Tests for LearnerState domain model — BKT, concept state, state helpers."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from learning_navigator.contracts.learner_state import (
    BehavioralAnomaly,
    BKTParams,
    ConceptRelation,
    ConceptRelationType,
    ConceptState,
    DriftSignal,
    LearnerState,
    MotivationLevel,
    MotivationState,
    TimeBudget,
)


class TestBKTParams:
    """Validate BKT update mechanics."""

    def test_defaults(self) -> None:
        bkt = BKTParams()
        assert bkt.p_know == 0.3
        assert bkt.mastery == 0.3

    def test_correct_answer_increases_mastery(self) -> None:
        bkt = BKTParams(p_know=0.3)
        updated = bkt.update(correct=True)
        assert updated.p_know > bkt.p_know

    def test_incorrect_answer_decreases_mastery(self) -> None:
        bkt = BKTParams(p_know=0.7)
        updated = bkt.update(correct=False)
        assert updated.p_know < bkt.p_know

    def test_mastery_bounded_at_1(self) -> None:
        bkt = BKTParams(p_know=0.99, p_transit=0.5)
        updated = bkt.update(correct=True)
        assert updated.p_know <= 1.0

    def test_mastery_stays_in_range(self) -> None:
        bkt = BKTParams(p_know=0.01)
        updated = bkt.update(correct=False)
        assert 0.0 <= updated.p_know <= 1.0

    def test_multiple_correct_converges_to_mastery(self) -> None:
        bkt = BKTParams(p_know=0.1)
        for _ in range(20):
            bkt = bkt.update(correct=True)
        assert bkt.p_know > 0.9

    def test_uncertainty_max_at_half(self) -> None:
        bkt = BKTParams(p_know=0.5)
        assert bkt.uncertainty == pytest.approx(1.0, abs=0.01)

    def test_uncertainty_zero_at_extremes(self) -> None:
        assert BKTParams(p_know=0.0).uncertainty == 0.0
        assert BKTParams(p_know=1.0).uncertainty == 0.0

    def test_uncertainty_symmetric(self) -> None:
        u_low = BKTParams(p_know=0.2).uncertainty
        u_high = BKTParams(p_know=0.8).uncertainty
        assert u_low == pytest.approx(u_high, abs=1e-9)


class TestConceptState:
    def test_mastery_delegates_to_bkt(self) -> None:
        cs = ConceptState(concept_id="algebra-101", bkt=BKTParams(p_know=0.75))
        assert cs.mastery == 0.75

    def test_default_forgetting_score(self) -> None:
        cs = ConceptState(concept_id="c1")
        assert cs.forgetting_score == 0.0

    def test_difficulty_range(self) -> None:
        with pytest.raises(ValueError):
            ConceptState(concept_id="c1", difficulty=1.5)


class TestLearnerState:
    def _make_state(self) -> LearnerState:
        """Build a learner state with a few concepts and relations."""
        s = LearnerState(learner_id="student-42")
        s.upsert_concept(
            ConceptState(
                concept_id="algebra",
                display_name="Algebra Basics",
                bkt=BKTParams(p_know=0.4),
                difficulty=0.5,
            )
        )
        s.upsert_concept(
            ConceptState(
                concept_id="calculus",
                display_name="Calculus I",
                bkt=BKTParams(p_know=0.2),
                difficulty=0.8,
            )
        )
        s.upsert_concept(
            ConceptState(
                concept_id="geometry",
                display_name="Geometry",
                bkt=BKTParams(p_know=0.85),
                difficulty=0.3,
            )
        )
        s.concept_relations = [
            ConceptRelation(
                source_concept_id="algebra",
                target_concept_id="calculus",
                relation_type=ConceptRelationType.PREREQUISITE,
            ),
            ConceptRelation(
                source_concept_id="geometry",
                target_concept_id="calculus",
                relation_type=ConceptRelationType.RELATED,
            ),
        ]
        return s

    def test_get_concept(self) -> None:
        s = self._make_state()
        c = s.get_concept("algebra")
        assert c is not None
        assert c.mastery == pytest.approx(0.4)

    def test_get_concept_missing(self) -> None:
        s = self._make_state()
        assert s.get_concept("nonexistent") is None

    def test_weak_concepts(self) -> None:
        s = self._make_state()
        weak = s.weak_concepts(threshold=0.5)
        ids = [c.concept_id for c in weak]
        assert "calculus" in ids
        assert "algebra" in ids
        assert "geometry" not in ids
        # Should be sorted ascending by mastery
        assert weak[0].concept_id == "calculus"

    def test_average_mastery(self) -> None:
        s = self._make_state()
        avg = s.average_mastery()
        expected = (0.4 + 0.2 + 0.85) / 3
        assert avg == pytest.approx(expected, abs=1e-6)

    def test_average_mastery_empty(self) -> None:
        s = LearnerState(learner_id="empty")
        assert s.average_mastery() == 0.0

    def test_average_uncertainty(self) -> None:
        s = self._make_state()
        assert 0.0 < s.average_uncertainty() < 1.0

    def test_average_uncertainty_empty(self) -> None:
        s = LearnerState(learner_id="empty")
        assert s.average_uncertainty() == 1.0

    def test_prerequisites_for(self) -> None:
        s = self._make_state()
        prereqs = s.prerequisites_for("calculus")
        assert "algebra" in prereqs
        # geometry -> calculus is RELATED, not PREREQUISITE
        assert "geometry" not in prereqs

    def test_dependents_of(self) -> None:
        s = self._make_state()
        deps = s.dependents_of("algebra")
        assert "calculus" in deps

    def test_high_forgetting_concepts(self) -> None:
        s = self._make_state()
        # No forgetting yet
        assert s.high_forgetting_concepts(threshold=0.5) == []
        # Set forgetting on algebra
        alg = s.get_concept("algebra")
        assert alg is not None
        alg_updated = alg.model_copy(update={"forgetting_score": 0.8})
        s.upsert_concept(alg_updated)
        high = s.high_forgetting_concepts(threshold=0.5)
        assert len(high) == 1
        assert high[0].concept_id == "algebra"

    def test_inactivity_hours_none_when_never_active(self) -> None:
        s = LearnerState(learner_id="new")
        assert s.inactivity_hours() is None

    def test_inactivity_hours_when_active(self) -> None:
        s = LearnerState(
            learner_id="active",
            last_active=datetime.now(timezone.utc) - timedelta(hours=5),
        )
        hours = s.inactivity_hours()
        assert hours is not None
        assert hours == pytest.approx(5.0, abs=0.1)

    def test_roundtrip_json(self) -> None:
        s = self._make_state()
        s.motivation = MotivationState(level=MotivationLevel.HIGH, score=0.9)
        s.active_drift_signals = [
            DriftSignal(drift_type="topic_drift", severity=0.6)
        ]
        s.behavioral_anomalies = [
            BehavioralAnomaly(anomaly_type="late_night_cramming", severity=0.4)
        ]
        s.time_budget = TimeBudget(total_hours_per_week=15, deadline=datetime(2026, 6, 1, tzinfo=timezone.utc))

        json_str = s.model_dump_json()
        restored = LearnerState.model_validate_json(json_str)

        assert restored.learner_id == "student-42"
        assert len(restored.concepts) == 3
        assert restored.motivation.level == MotivationLevel.HIGH
        assert len(restored.active_drift_signals) == 1
        assert len(restored.behavioral_anomalies) == 1
        assert restored.time_budget.total_hours_per_week == 15

    def test_global_confidence_default(self) -> None:
        s = LearnerState(learner_id="x")
        assert s.global_confidence == 0.5

    def test_schema_version(self) -> None:
        s = LearnerState(learner_id="x")
        assert s.schema_version == "1.0.0"
