"""Learner State domain model — the core data structure of the system.

The LearnerState captures everything the system knows about a learner at a
point in time.  It is the *single source of truth* consumed by all agents.

Design decisions
────────────────
• Pydantic models for validation + serialization.
• Uncertainty is first-class: every numeric estimate carries a confidence
  interval or explicit uncertainty field.
• BKT (Bayesian Knowledge Tracing) parameters per concept enable principled
  mastery estimation.
• Knowledge graph edges are stored inline (adjacency list) for simplicity;
  a full graph DB is overkill for v1 but the interface is ready.
• All timestamps are UTC datetime.
• The model is versioned via ``schema_version`` to support migrations.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

# ── BKT Parameters ────────────────────────────────────────────────────────

class BKTParams(BaseModel):
    """Bayesian Knowledge Tracing parameters for a single concept.

    Standard BKT has four parameters:
    • p_know  — P(learner knows the concept)  (posterior, updated)
    • p_init  — P(knew before any practice)
    • p_transit — P(learn | didn't know) per opportunity
    • p_slip — P(wrong | knows)
    • p_guess — P(right | doesn't know)
    """

    p_know: float = Field(default=0.3, ge=0.0, le=1.0)
    p_init: float = Field(default=0.3, ge=0.0, le=1.0)
    p_transit: float = Field(default=0.1, ge=0.0, le=1.0)
    p_slip: float = Field(default=0.1, ge=0.0, le=1.0)
    p_guess: float = Field(default=0.25, ge=0.0, le=1.0)

    def update(self, correct: bool) -> BKTParams:
        """Return a new BKTParams with updated p_know after an observation.

        This is the standard BKT posterior update:
        1. Compute P(knew | observation) via Bayes' rule.
        2. Add learning probability for transition.
        """
        if correct:
            p_correct_given_know = 1.0 - self.p_slip
            p_correct_given_not = self.p_guess
            p_know_given_obs = (
                (self.p_know * p_correct_given_know)
                / (
                    self.p_know * p_correct_given_know
                    + (1.0 - self.p_know) * p_correct_given_not
                )
            )
        else:
            p_wrong_given_know = self.p_slip
            p_wrong_given_not = 1.0 - self.p_guess
            p_know_given_obs = (
                (self.p_know * p_wrong_given_know)
                / (
                    self.p_know * p_wrong_given_know
                    + (1.0 - self.p_know) * p_wrong_given_not
                )
            )

        # Apply learning transition
        new_p_know = p_know_given_obs + (1.0 - p_know_given_obs) * self.p_transit

        return self.model_copy(update={"p_know": min(new_p_know, 1.0)})

    @property
    def mastery(self) -> float:
        """Convenience alias — mastery is p_know."""
        return self.p_know

    @property
    def uncertainty(self) -> float:
        """Entropy-based uncertainty: max at p_know=0.5, min at 0 or 1.

        Returns a value in [0, 1] where 1 = maximum uncertainty.
        """
        p = self.p_know
        if p <= 0.0 or p >= 1.0:
            return 0.0
        import math

        entropy = -(p * math.log2(p) + (1 - p) * math.log2(1 - p))
        return entropy  # already in [0, 1] for binary entropy


# ── Knowledge Graph ───────────────────────────────────────────────────────

class ConceptRelationType(str, Enum):
    """Types of edges in the knowledge graph."""

    PREREQUISITE = "prerequisite"
    COREQUISITE = "corequisite"
    EXTENDS = "extends"
    RELATED = "related"


class ConceptRelation(BaseModel):
    """A directed edge in the knowledge graph."""

    source_concept_id: str
    target_concept_id: str
    relation_type: ConceptRelationType
    weight: float = Field(default=1.0, ge=0.0, le=1.0)


# ── Concept State ─────────────────────────────────────────────────────────

class ConceptState(BaseModel):
    """Per-concept state within the learner model."""

    concept_id: str
    display_name: str = ""
    bkt: BKTParams = Field(default_factory=BKTParams)

    # Forgetting / decay
    last_practiced: datetime | None = None
    practice_count: int = 0
    forgetting_score: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="0=fully retained, 1=fully forgotten. Updated by Decay Agent.",
    )
    spacing_history: list[float] = Field(
        default_factory=list,
        description="Inter-practice intervals in hours, most recent last.",
    )

    # Difficulty estimate (used by Decay Agent parameterisation)
    difficulty: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="0=easy, 1=hard. Can be set by curriculum or inferred.",
    )

    @property
    def mastery(self) -> float:
        return self.bkt.mastery

    @property
    def uncertainty(self) -> float:
        return self.bkt.uncertainty


# ── Motivation & Behavioral Signals ──────────────────────────────────────

class MotivationLevel(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    CRITICAL = "critical"


class MotivationState(BaseModel):
    """Estimated motivation with trend tracking."""

    level: MotivationLevel = MotivationLevel.MEDIUM
    score: float = Field(default=0.5, ge=0.0, le=1.0)
    trend: float = Field(
        default=0.0,
        ge=-1.0,
        le=1.0,
        description="Positive = improving, negative = declining.",
    )
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    last_updated: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class DriftSignal(BaseModel):
    """A detected drift away from learning goals."""

    drift_type: str  # e.g., "topic_drift", "disengagement", "difficulty_mismatch"
    severity: float = Field(ge=0.0, le=1.0)
    detected_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    details: dict[str, Any] = Field(default_factory=dict)


class BehavioralAnomaly(BaseModel):
    """A detected anomaly in learner behavior patterns."""

    anomaly_type: str
    severity: float = Field(ge=0.0, le=1.0)
    detected_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    evidence: dict[str, Any] = Field(default_factory=dict)
    resolved: bool = False


# ── Time Budget ───────────────────────────────────────────────────────────

class TimeBudget(BaseModel):
    """Learner's time constraints and allocation preferences."""

    total_hours_per_week: float = Field(default=10.0, ge=0.0)
    hours_remaining_this_week: float = Field(default=10.0, ge=0.0)
    preferred_session_minutes: int = Field(default=45, ge=5)
    deadline: datetime | None = None
    priority_concept_ids: list[str] = Field(default_factory=list)


# ── The Full Learner State ────────────────────────────────────────────────

class LearnerState(BaseModel):
    """Complete learner state — the single source of truth for all agents.

    This is a point-in-time snapshot.  The MemoryStore persists the latest
    version and the PortfolioLog keeps the full history.
    """

    # Identity & versioning
    schema_version: str = "1.0.0"
    learner_id: str
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    # ── Per-concept mastery (BKT + decay) ──────────────────────────────
    concepts: dict[str, ConceptState] = Field(
        default_factory=dict,
        description="Keyed by concept_id.",
    )

    # ── Knowledge graph (adjacency list) ───────────────────────────────
    concept_relations: list[ConceptRelation] = Field(default_factory=list)

    # ── Motivation & engagement ────────────────────────────────────────
    motivation: MotivationState = Field(default_factory=MotivationState)

    # ── Drift signals ──────────────────────────────────────────────────
    active_drift_signals: list[DriftSignal] = Field(default_factory=list)

    # ── Behavioral anomalies ───────────────────────────────────────────
    behavioral_anomalies: list[BehavioralAnomaly] = Field(default_factory=list)

    # ── Time budget ────────────────────────────────────────────────────
    time_budget: TimeBudget = Field(default_factory=TimeBudget)

    # ── Session tracking ───────────────────────────────────────────────
    session_count: int = 0
    last_active: datetime | None = None
    total_practice_time_hours: float = 0.0

    # ── Global uncertainty ─────────────────────────────────────────────
    global_confidence: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Orchestrator's overall confidence in this state estimate.",
    )

    # ── Extension slot ─────────────────────────────────────────────────
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Arbitrary metadata for extensions / custom agents.",
    )

    # ── Helpers ────────────────────────────────────────────────────────

    def get_concept(self, concept_id: str) -> ConceptState | None:
        """Look up a concept state by ID."""
        return self.concepts.get(concept_id)

    def upsert_concept(self, concept: ConceptState) -> None:
        """Insert or update a concept state."""
        self.concepts[concept.concept_id] = concept
        self.updated_at = datetime.now(timezone.utc)

    def weak_concepts(self, threshold: float = 0.5) -> list[ConceptState]:
        """Return concepts with mastery below a threshold, sorted ascending."""
        weak = [c for c in self.concepts.values() if c.mastery < threshold]
        return sorted(weak, key=lambda c: c.mastery)

    def high_forgetting_concepts(self, threshold: float = 0.5) -> list[ConceptState]:
        """Return concepts whose forgetting score exceeds a threshold."""
        return sorted(
            [c for c in self.concepts.values() if c.forgetting_score > threshold],
            key=lambda c: c.forgetting_score,
            reverse=True,
        )

    def average_mastery(self) -> float:
        """Mean mastery across all tracked concepts."""
        if not self.concepts:
            return 0.0
        return sum(c.mastery for c in self.concepts.values()) / len(self.concepts)

    def average_uncertainty(self) -> float:
        """Mean uncertainty across all tracked concepts."""
        if not self.concepts:
            return 1.0
        return sum(c.uncertainty for c in self.concepts.values()) / len(self.concepts)

    def prerequisites_for(self, concept_id: str) -> list[str]:
        """Return concept IDs that are prerequisites for the given concept."""
        return [
            r.source_concept_id
            for r in self.concept_relations
            if r.target_concept_id == concept_id
            and r.relation_type == ConceptRelationType.PREREQUISITE
        ]

    def dependents_of(self, concept_id: str) -> list[str]:
        """Return concept IDs that depend on the given concept."""
        return [
            r.target_concept_id
            for r in self.concept_relations
            if r.source_concept_id == concept_id
            and r.relation_type == ConceptRelationType.PREREQUISITE
        ]

    def inactivity_hours(self) -> float | None:
        """Hours since last activity, or None if never active."""
        if self.last_active is None:
            return None
        delta = datetime.now(timezone.utc) - self.last_active
        return delta.total_seconds() / 3600.0
