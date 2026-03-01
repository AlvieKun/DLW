"""Evaluation scenarios — pre-defined learner journeys for quality assessment.

Each scenario describes a multi-step sequence of learner events and the
expected properties of the system's responses (confidence ranges,
action types, safety constraints, etc.).

Scenarios cover:
1. Happy-path progression
2. Struggling learner (repeated failure)
3. Drift after inactivity
4. High-achiever acceleration
5. Motivation crisis
6. Multi-concept prerequisite chain
7. Exam deadline pressure
8. Cold-start (brand-new learner)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from learning_navigator.contracts.events import LearnerEventType


@dataclass
class StepExpectation:
    """What we expect from a single pipeline response."""

    # Action type must contain one of these substrings (empty = any)
    action_contains: list[str] = field(default_factory=list)

    # Confidence bounds
    min_confidence: float = 0.0
    max_confidence: float = 1.0

    # Risk keys that must / must-not be present
    required_risk_keys: list[str] = field(default_factory=list)
    forbidden_risk_keys: list[str] = field(default_factory=list)

    # Expected learning gain range
    min_gain: float = 0.0
    max_gain: float = 1.0

    # Rationale must be non-empty
    rationale_non_empty: bool = True

    # Pipeline coverage: minimum agent steps in debug_trace
    min_pipeline_steps: int = 0


@dataclass
class ScenarioStep:
    """A single event in a scenario sequence."""

    event_type: LearnerEventType
    concept_id: str | None = None
    data: dict[str, Any] = field(default_factory=dict)
    source: str = "eval-harness"
    description: str = ""
    expectation: StepExpectation = field(default_factory=StepExpectation)


@dataclass
class EvalScenario:
    """A complete evaluation scenario — a named sequence of steps."""

    name: str
    description: str
    learner_id: str
    steps: list[ScenarioStep]
    tags: list[str] = field(default_factory=list)


# ═══════════════════════════════════════════════════════════════════
# Pre-defined Scenarios
# ═══════════════════════════════════════════════════════════════════


def scenario_happy_path() -> EvalScenario:
    """Learner progresses smoothly through a concept."""
    return EvalScenario(
        name="happy-path-progression",
        description="Learner answers quiz correctly, showing steady improvement",
        learner_id="eval-happy",
        tags=["core", "regression"],
        steps=[
            ScenarioStep(
                event_type=LearnerEventType.QUIZ_RESULT,
                concept_id="algebra",
                data={"score": 0.6, "max_score": 1.0},
                description="Moderate quiz score — system should plan review",
                expectation=StepExpectation(
                    min_confidence=0.3,
                    rationale_non_empty=True,
                    min_pipeline_steps=3,
                ),
            ),
            ScenarioStep(
                event_type=LearnerEventType.QUIZ_RESULT,
                concept_id="algebra",
                data={"score": 0.85, "max_score": 1.0},
                description="Strong score — confidence should increase",
                expectation=StepExpectation(
                    min_confidence=0.3,
                    rationale_non_empty=True,
                ),
            ),
            ScenarioStep(
                event_type=LearnerEventType.QUIZ_RESULT,
                concept_id="algebra",
                data={"score": 0.95, "max_score": 1.0},
                description="Near mastery — system may recommend advancing",
                expectation=StepExpectation(
                    min_confidence=0.4,
                    rationale_non_empty=True,
                ),
            ),
        ],
    )


def scenario_struggling_learner() -> EvalScenario:
    """Learner repeatedly fails — system must detect and adapt."""
    return EvalScenario(
        name="struggling-learner",
        description="Repeated low scores should trigger prerequisite review and burnout avoidance",
        learner_id="eval-struggle",
        tags=["core", "safety"],
        steps=[
            ScenarioStep(
                event_type=LearnerEventType.QUIZ_RESULT,
                concept_id="calculus",
                data={"score": 0.2, "max_score": 1.0},
                description="Very low score — first failure",
                expectation=StepExpectation(
                    min_confidence=0.2,
                    rationale_non_empty=True,
                ),
            ),
            ScenarioStep(
                event_type=LearnerEventType.QUIZ_RESULT,
                concept_id="calculus",
                data={"score": 0.15, "max_score": 1.0},
                description="Second failure — pattern emerging",
                expectation=StepExpectation(
                    min_confidence=0.2,
                    rationale_non_empty=True,
                ),
            ),
            ScenarioStep(
                event_type=LearnerEventType.QUIZ_RESULT,
                concept_id="calculus",
                data={"score": 0.1, "max_score": 1.0},
                description="Third failure — should recommend prerequisite review",
                expectation=StepExpectation(
                    min_confidence=0.2,
                    rationale_non_empty=True,
                ),
            ),
            ScenarioStep(
                event_type=LearnerEventType.SENTIMENT_SIGNAL,
                concept_id="calculus",
                data={"sentiment": "frustrated", "intensity": 0.9},
                description="Frustration signal — burnout risk should appear",
                expectation=StepExpectation(
                    rationale_non_empty=True,
                ),
            ),
        ],
    )


def scenario_inactivity_drift() -> EvalScenario:
    """Learner returns after extended inactivity."""
    return EvalScenario(
        name="inactivity-drift",
        description="Long gap then return — decay and drift detection should activate",
        learner_id="eval-drift",
        tags=["core", "continual-learning"],
        steps=[
            ScenarioStep(
                event_type=LearnerEventType.QUIZ_RESULT,
                concept_id="statistics",
                data={"score": 0.8, "max_score": 1.0},
                description="Good baseline score",
                expectation=StepExpectation(
                    min_confidence=0.3,
                ),
            ),
            ScenarioStep(
                event_type=LearnerEventType.INACTIVITY_GAP,
                data={"gap_hours": 720, "last_active_concept": "statistics"},
                description="30-day inactivity gap",
                expectation=StepExpectation(
                    rationale_non_empty=True,
                ),
            ),
            ScenarioStep(
                event_type=LearnerEventType.QUIZ_RESULT,
                concept_id="statistics",
                data={"score": 0.4, "max_score": 1.0},
                description="Score dropped after gap — decay should be detected",
                expectation=StepExpectation(
                    min_confidence=0.2,
                    rationale_non_empty=True,
                ),
            ),
        ],
    )


def scenario_high_achiever() -> EvalScenario:
    """Consistently excellent learner — system should accelerate."""
    return EvalScenario(
        name="high-achiever-acceleration",
        description="Top performer should be challenged, not held back",
        learner_id="eval-achiever",
        tags=["core"],
        steps=[
            ScenarioStep(
                event_type=LearnerEventType.QUIZ_RESULT,
                concept_id="linear-algebra",
                data={"score": 0.95, "max_score": 1.0},
                description="Excellent score",
                expectation=StepExpectation(
                    min_confidence=0.4,
                ),
            ),
            ScenarioStep(
                event_type=LearnerEventType.QUIZ_RESULT,
                concept_id="linear-algebra",
                data={"score": 0.98, "max_score": 1.0},
                description="Near-perfect — should advance to next concept",
                expectation=StepExpectation(
                    min_confidence=0.4,
                    rationale_non_empty=True,
                ),
            ),
            ScenarioStep(
                event_type=LearnerEventType.TIME_ON_TASK,
                concept_id="linear-algebra",
                data={"minutes": 15, "completed_exercises": 5},
                description="Fast completion — not under-challenged",
                expectation=StepExpectation(
                    rationale_non_empty=True,
                ),
            ),
        ],
    )


def scenario_motivation_crisis() -> EvalScenario:
    """Learner motivation collapses — system must handle safely."""
    return EvalScenario(
        name="motivation-crisis",
        description="Sharp motivation drop should trigger supportive, low-intensity recs",
        learner_id="eval-motivation",
        tags=["core", "safety"],
        steps=[
            ScenarioStep(
                event_type=LearnerEventType.QUIZ_RESULT,
                concept_id="geometry",
                data={"score": 0.7, "max_score": 1.0},
                description="Decent baseline",
                expectation=StepExpectation(
                    min_confidence=0.3,
                ),
            ),
            ScenarioStep(
                event_type=LearnerEventType.SENTIMENT_SIGNAL,
                data={"sentiment": "overwhelmed", "intensity": 0.95},
                description="Severe overwhelm signal",
                expectation=StepExpectation(
                    rationale_non_empty=True,
                ),
            ),
            ScenarioStep(
                event_type=LearnerEventType.MOTIVATION_SIGNAL,
                data={"motivation_level": "critical", "self_efficacy": 0.1},
                description="Critical motivation — system should be gentle",
                expectation=StepExpectation(
                    rationale_non_empty=True,
                ),
            ),
        ],
    )


def scenario_prerequisite_chain() -> EvalScenario:
    """Learner working through a prerequisite dependency chain."""
    return EvalScenario(
        name="prerequisite-chain",
        description="Multi-concept chain: algebra → calculus, testing prerequisite enforcement",
        learner_id="eval-prereq",
        tags=["core", "planning"],
        steps=[
            ScenarioStep(
                event_type=LearnerEventType.QUIZ_RESULT,
                concept_id="algebra",
                data={"score": 0.4, "max_score": 1.0},
                description="Low algebra — prerequisite for calculus",
                expectation=StepExpectation(
                    min_confidence=0.2,
                    rationale_non_empty=True,
                ),
            ),
            ScenarioStep(
                event_type=LearnerEventType.QUIZ_RESULT,
                concept_id="calculus",
                data={"score": 0.3, "max_score": 1.0},
                description="Attempting calculus without algebra mastery",
                expectation=StepExpectation(
                    rationale_non_empty=True,
                ),
            ),
            ScenarioStep(
                event_type=LearnerEventType.QUIZ_RESULT,
                concept_id="algebra",
                data={"score": 0.85, "max_score": 1.0},
                description="Algebra improved — calculus should now be viable",
                expectation=StepExpectation(
                    min_confidence=0.3,
                    rationale_non_empty=True,
                ),
            ),
        ],
    )


def scenario_exam_deadline() -> EvalScenario:
    """Approaching exam deadline — time pressure."""
    return EvalScenario(
        name="exam-deadline-pressure",
        description="Near-deadline scenario should bias toward exam-strategic recommendations",
        learner_id="eval-exam",
        tags=["core", "debate"],
        steps=[
            ScenarioStep(
                event_type=LearnerEventType.QUIZ_RESULT,
                concept_id="probability",
                data={"score": 0.5, "max_score": 1.0},
                description="50% mastery with deadline approaching",
                expectation=StepExpectation(
                    rationale_non_empty=True,
                ),
            ),
            ScenarioStep(
                event_type=LearnerEventType.SELF_REPORT,
                data={
                    "exam_in_days": 3,
                    "topics_remaining": ["probability", "statistics"],
                    "stress_level": "high",
                },
                description="Self-report: exam in 3 days, high stress",
                expectation=StepExpectation(
                    rationale_non_empty=True,
                ),
            ),
            ScenarioStep(
                event_type=LearnerEventType.TIME_ON_TASK,
                concept_id="probability",
                data={"minutes": 120, "completed_exercises": 20},
                description="Intense cramming session",
                expectation=StepExpectation(
                    rationale_non_empty=True,
                ),
            ),
        ],
    )


def scenario_cold_start() -> EvalScenario:
    """Brand-new learner — no history."""
    return EvalScenario(
        name="cold-start",
        description="First interaction ever — system must handle gracefully with no prior data",
        learner_id="eval-cold-start",
        tags=["core", "regression"],
        steps=[
            ScenarioStep(
                event_type=LearnerEventType.QUIZ_RESULT,
                concept_id="python-basics",
                data={"score": 0.6, "max_score": 1.0},
                description="First-ever event for this learner",
                expectation=StepExpectation(
                    min_confidence=0.2,
                    rationale_non_empty=True,
                    min_pipeline_steps=3,
                ),
            ),
        ],
    )


# ─── Registry ─────────────────────────────────────────────────────

_SCENARIOS: list[EvalScenario] | None = None


def get_all_scenarios() -> list[EvalScenario]:
    """Return all built-in evaluation scenarios."""
    global _SCENARIOS  # noqa: PLW0603
    if _SCENARIOS is None:
        _SCENARIOS = [
            scenario_happy_path(),
            scenario_struggling_learner(),
            scenario_inactivity_drift(),
            scenario_high_achiever(),
            scenario_motivation_crisis(),
            scenario_prerequisite_chain(),
            scenario_exam_deadline(),
            scenario_cold_start(),
        ]
    return _SCENARIOS


def get_scenarios_by_tag(tag: str) -> list[EvalScenario]:
    """Filter scenarios by tag."""
    return [s for s in get_all_scenarios() if tag in s.tags]
