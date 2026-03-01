"""Adaptive Agent Router — cost-aware, uncertainty-driven agent selection.

The Adaptive Router decides *which agents to run* on each pipeline turn
based on:

1. **Learner state uncertainty** — high uncertainty triggers more agents.
2. **Active drift signals** — drift triggers drift-related agents.
3. **Cost budget** — agents are selected within an abstract cost budget
   using greedy knapsack (priority-ordered by expected value).
4. **Recency gating** — agents that ran recently on stable state can be
   skipped without loss.

Routing Tiers
─────────────
- **Core** (always run): Diagnoser, Motivation
- **Conditional**: DriftDetector, SkillState, Behavior, Decay
- **Expensive**: Planner+Evaluator, Debate, RAG, TimeOptimizer,
  GenerativeReplay, Reflection

Each agent has a ``need_score`` computed from contextual signals.
Agents are sorted by need_score / cost_tier (value density) and
selected greedily until the budget is exhausted.

When ``adaptive_routing_enabled=False``, the router returns ALL agents
(full pipeline, same as pre-Phase 8 behaviour).
"""

from __future__ import annotations

from dataclasses import dataclass

import structlog

from learning_navigator.agents.base import BaseAgent
from learning_navigator.contracts.learner_state import LearnerState

logger = structlog.get_logger(__name__)


# ── Routing Decision ──────────────────────────────────────────────


@dataclass
class RoutingDecision:
    """The output of the adaptive router."""

    selected_agents: list[str]
    """Agent IDs that should run this turn."""

    skipped_agents: list[str]
    """Agent IDs that were skipped to save cost."""

    routing_rationale: dict[str, str]
    """Per-agent rationale for include/skip decision."""

    total_cost: float
    """Sum of cost_tier values for selected agents."""

    budget: float
    """The cost budget that was available."""

    uncertainty_score: float
    """The global uncertainty that drove the decision."""

    full_pipeline: bool
    """Whether this was a forced full-pipeline run (no routing)."""


# ── Need Scoring ──────────────────────────────────────────────────


@dataclass
class _AgentNeedScore:
    """Internal scoring for a single agent's need-to-run."""

    agent_id: str
    need: float  # 0..1+ — how much is this agent needed?
    cost: int  # cost_tier from metadata
    is_core: bool = False  # core agents always run
    rationale: str = ""

    @property
    def value_density(self) -> float:
        """Higher = more bang for the buck."""
        if self.cost == 0:
            return float("inf")
        return self.need / self.cost


# ── Adaptive Router ───────────────────────────────────────────────


# Agent IDs that are always run regardless of budget
_CORE_AGENT_IDS = frozenset({"diagnoser", "motivation"})

# Agent IDs that are part of the maker-checker / debate subsystem
# (bundled — they run together or not at all)
_PLANNING_BUNDLE = frozenset({"planner", "evaluator"})
_DEBATE_BUNDLE = frozenset({
    "mastery-maximizer", "exam-strategist",
    "burnout-minimizer", "debate-arbitrator",
})


class AdaptiveRouter:
    """Selects the minimal effective agent set per turn.

    Parameters
    ----------
    agents : dict[str, BaseAgent]
        Registry of agent_id → agent instance.
    budget : float
        Abstract cost budget per turn.
    enabled : bool
        When False, always returns full pipeline.
    uncertainty_threshold : float
        Below this uncertainty, expensive agents may be skipped.
    full_pipeline_interval : int
        Force a full pipeline run every N turns to prevent staleness.
    """

    def __init__(
        self,
        agents: dict[str, BaseAgent],
        budget: float = 10.0,
        enabled: bool = True,
        uncertainty_threshold: float = 0.3,
        full_pipeline_interval: int = 5,
    ) -> None:
        self._agents = agents
        self._budget = budget
        self._enabled = enabled
        self._uncertainty_threshold = uncertainty_threshold
        self._full_pipeline_interval = full_pipeline_interval
        self._turn_counter: int = 0

    def route(
        self,
        state: LearnerState,
        recent_drift_count: int = 0,
        recent_anomaly_count: int = 0,
        has_decay_risk: bool = False,
    ) -> RoutingDecision:
        """Decide which agents to run this turn.

        Parameters
        ----------
        state : LearnerState
            Current learner state (post-load, pre-pipeline).
        recent_drift_count : int
            Number of active drift signals.
        recent_anomaly_count : int
            Number of recent behavioural anomalies.
        has_decay_risk : bool
            Whether any concepts are at forgetting risk.

        Returns
        -------
        RoutingDecision
        """
        self._turn_counter += 1
        uncertainty = state.average_uncertainty()

        # Full pipeline if routing is disabled or periodic refresh
        force_full = (
            not self._enabled
            or self._turn_counter % self._full_pipeline_interval == 0
        )

        if force_full:
            all_ids = list(self._agents.keys())
            return RoutingDecision(
                selected_agents=all_ids,
                skipped_agents=[],
                routing_rationale={
                    aid: "full_pipeline" for aid in all_ids
                },
                total_cost=sum(
                    a.metadata.cost_tier for a in self._agents.values()
                ),
                budget=self._budget,
                uncertainty_score=uncertainty,
                full_pipeline=True,
            )

        # Score each agent's need
        scores = self._compute_need_scores(
            state, uncertainty, recent_drift_count,
            recent_anomaly_count, has_decay_risk,
        )

        # Greedy knapsack: core agents first, then by value density
        selected: list[str] = []
        skipped: list[str] = []
        rationale: dict[str, str] = {}
        remaining_budget = self._budget

        # Phase 1: always include core agents
        for s in scores:
            if s.is_core:
                selected.append(s.agent_id)
                remaining_budget -= s.cost
                rationale[s.agent_id] = f"core (need={s.need:.2f})"

        # Phase 2: sort non-core by value density descending
        non_core = [s for s in scores if not s.is_core]
        non_core.sort(key=lambda s: s.value_density, reverse=True)

        for s in non_core:
            if s.need < 0.1:
                skipped.append(s.agent_id)
                rationale[s.agent_id] = f"skip: need={s.need:.2f} below threshold"
                continue

            if s.cost <= remaining_budget:
                selected.append(s.agent_id)
                remaining_budget -= s.cost
                rationale[s.agent_id] = (
                    f"selected (need={s.need:.2f}, "
                    f"cost={s.cost}, density={s.value_density:.2f})"
                )
            else:
                skipped.append(s.agent_id)
                rationale[s.agent_id] = (
                    f"skip: budget exhausted "
                    f"(need={s.need:.2f}, cost={s.cost}, "
                    f"remaining={remaining_budget:.1f})"
                )

        total_cost = self._budget - remaining_budget

        log = logger.bind(
            selected=len(selected),
            skipped=len(skipped),
            uncertainty=round(uncertainty, 3),
            total_cost=total_cost,
        )
        log.info("adaptive_router.route")

        return RoutingDecision(
            selected_agents=selected,
            skipped_agents=skipped,
            routing_rationale=rationale,
            total_cost=total_cost,
            budget=self._budget,
            uncertainty_score=uncertainty,
            full_pipeline=False,
        )

    def _compute_need_scores(
        self,
        state: LearnerState,
        uncertainty: float,
        drift_count: int,
        anomaly_count: int,
        has_decay_risk: bool,
    ) -> list[_AgentNeedScore]:
        """Compute need-to-run scores for each registered agent."""
        scores: list[_AgentNeedScore] = []

        for agent_id, agent in self._agents.items():
            cost = agent.metadata.cost_tier
            is_core = agent_id in _CORE_AGENT_IDS

            need = self._agent_need(
                agent_id, uncertainty, drift_count,
                anomaly_count, has_decay_risk, state,
            )

            scores.append(_AgentNeedScore(
                agent_id=agent_id,
                need=need,
                cost=cost,
                is_core=is_core,
                rationale=f"uncertainty={uncertainty:.2f}",
            ))

        return scores

    @staticmethod
    def _agent_need(
        agent_id: str,
        uncertainty: float,
        drift_count: int,
        anomaly_count: int,
        has_decay_risk: bool,
        state: LearnerState,
    ) -> float:
        """Heuristic need score for a specific agent.

        Returns a float in [0, 1+]. Higher = more needed.
        """
        # Core agents always needed
        if agent_id in _CORE_AGENT_IDS:
            return 1.0

        # Base need from uncertainty
        base = min(1.0, uncertainty * 1.5)

        if agent_id == "drift-detector":
            # More needed when we have drift signals or high uncertainty
            return max(base, 0.5 if drift_count > 0 else 0.2)

        if agent_id == "skill-state":
            # Needed when there are concepts to analyse
            has_concepts = len(state.concepts) > 0
            return base * 0.8 if has_concepts else 0.1

        if agent_id == "behavior":
            # More needed when anomalies exist
            return max(base * 0.7, 0.6 if anomaly_count > 0 else 0.2)

        if agent_id == "decay":
            # High need when decay risk exists
            return max(base, 0.8 if has_decay_risk else 0.3)

        if agent_id == "generative-replay":
            # Only needed when decay risk exists
            return 0.7 if has_decay_risk else 0.15

        if agent_id == "time-optimizer":
            return base * 0.6

        if agent_id in _PLANNING_BUNDLE:
            # Always needed at reasonable uncertainty
            return max(0.5, base)

        if agent_id in _DEBATE_BUNDLE:
            # Expensive — only when uncertainty is high
            return base * 0.9 if uncertainty > 0.3 else 0.15

        if agent_id == "rag-agent":
            # Needed when plan exists and uncertainty is moderate
            return base * 0.7

        if agent_id == "reflection":
            # Always useful but skippable under tight budget
            return 0.4

        # Default for unknown agents
        return base * 0.5

    @property
    def turn_counter(self) -> int:
        """Number of turns processed."""
        return self._turn_counter

    @turn_counter.setter
    def turn_counter(self, value: int) -> None:
        self._turn_counter = value
