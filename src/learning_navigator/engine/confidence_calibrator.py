"""Confidence Calibrator — dynamic agent confidence weighting.

Agents self-report confidence, but self-assessment can be systematically
biased.  The Confidence Calibrator:

1. **Tracks** each agent's reported confidence vs actual outcome accuracy.
2. **Computes** a calibration factor (trust_weight) per agent using
   exponential-decay weighted history.
3. **Adjusts** raw agent confidence to produce calibrated confidence.

This creates a *self-correcting ensemble* without retraining individual
agents.  Over-confident agents get down-weighted; under-confident agents
get up-weighted.

Cold-start behaviour
────────────────────
When no calibration history exists, all agents get trust_weight=1.0
(no adjustment).  The system learns calibration organically as outcomes
arrive via ``record_outcome()``.

Exponential decay
─────────────────
Recent observations matter more.  Each observation's weight decays by
``decay_factor`` per subsequent observation, so the effective window is
approximately ``1 / (1 - decay_factor)`` observations.
Default: 0.9 → ~10-observation effective window.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


@dataclass
class CalibrationRecord:
    """A single calibration observation for one agent."""

    reported_confidence: float
    actual_accuracy: float
    timestamp_epoch: float = 0.0


@dataclass
class AgentCalibration:
    """Calibration state for a single agent."""

    agent_id: str
    history: list[CalibrationRecord] = field(default_factory=list)
    trust_weight: float = 1.0

    @property
    def observation_count(self) -> int:
        return len(self.history)


class ConfidenceCalibrator:
    """Tracks and adjusts agent confidence based on outcome history.

    Parameters
    ----------
    decay_factor : float
        Exponential decay for older observations (0..1).
        Higher = longer memory. Default 0.9.
    max_history : int
        Maximum observations to keep per agent. Default 100.
    min_observations : int
        Minimum observations before we start adjusting. Default 3.
    """

    def __init__(
        self,
        decay_factor: float = 0.9,
        max_history: int = 100,
        min_observations: int = 3,
    ) -> None:
        self._decay = decay_factor
        self._max_history = max_history
        self._min_obs = min_observations
        self._agents: dict[str, AgentCalibration] = {}

    def record_outcome(
        self,
        agent_id: str,
        reported_confidence: float,
        actual_accuracy: float,
        timestamp_epoch: float = 0.0,
    ) -> None:
        """Record an observation linking reported confidence to actual accuracy.

        Parameters
        ----------
        agent_id : str
            Which agent this observation is for.
        reported_confidence : float
            What the agent claimed (0..1).
        actual_accuracy : float
            How accurate the prediction actually was (0..1).
        timestamp_epoch : float
            Optional epoch timestamp for ordering.
        """
        if agent_id not in self._agents:
            self._agents[agent_id] = AgentCalibration(agent_id=agent_id)

        cal = self._agents[agent_id]
        cal.history.append(CalibrationRecord(
            reported_confidence=reported_confidence,
            actual_accuracy=actual_accuracy,
            timestamp_epoch=timestamp_epoch,
        ))

        # Trim to max
        if len(cal.history) > self._max_history:
            cal.history = cal.history[-self._max_history:]

        # Recompute trust weight
        cal.trust_weight = self._compute_trust_weight(cal)

        logger.debug(
            "calibrator.record",
            agent_id=agent_id,
            reported=round(reported_confidence, 3),
            actual=round(actual_accuracy, 3),
            trust_weight=round(cal.trust_weight, 3),
            observations=len(cal.history),
        )

    def calibrate(self, agent_id: str, raw_confidence: float) -> float:
        """Return calibrated confidence for an agent.

        If the agent has insufficient history, returns raw_confidence.
        Otherwise, applies the trust_weight as a scaling factor,
        clamped to [0, 1].
        """
        cal = self._agents.get(agent_id)
        if cal is None or cal.observation_count < self._min_obs:
            return raw_confidence

        adjusted = raw_confidence * cal.trust_weight
        return max(0.0, min(1.0, adjusted))

    def get_trust_weight(self, agent_id: str) -> float:
        """Return the current trust weight for an agent (1.0 = default)."""
        cal = self._agents.get(agent_id)
        if cal is None:
            return 1.0
        return cal.trust_weight

    def get_all_weights(self) -> dict[str, float]:
        """Return trust weights for all tracked agents."""
        return {
            aid: cal.trust_weight
            for aid, cal in self._agents.items()
        }

    def get_calibration_summary(self) -> dict[str, Any]:
        """Return a summary of calibration state for telemetry."""
        summary: dict[str, Any] = {}
        for aid, cal in self._agents.items():
            summary[aid] = {
                "trust_weight": round(cal.trust_weight, 4),
                "observations": cal.observation_count,
                "avg_reported": round(self._weighted_avg(
                    cal, lambda r: r.reported_confidence
                ), 3) if cal.observation_count > 0 else None,
                "avg_actual": round(self._weighted_avg(
                    cal, lambda r: r.actual_accuracy
                ), 3) if cal.observation_count > 0 else None,
            }
        return summary

    def _compute_trust_weight(self, cal: AgentCalibration) -> float:
        """Compute trust weight from calibration history.

        Strategy:
        - Compute weighted average of (actual / reported) ratio.
        - Use exponential decay so recent observations count more.
        - Clamp to [0.3, 1.5] to prevent extreme adjustments.
        - If fewer than min_observations, return 1.0 (no adjustment).
        """
        if cal.observation_count < self._min_obs:
            return 1.0

        total_weight = 0.0
        weighted_ratio_sum = 0.0
        n = len(cal.history)

        for i, record in enumerate(cal.history):
            # More recent records get higher weight
            age = n - 1 - i  # 0 for newest
            w = self._decay ** age

            # Ratio: how accurate was the agent relative to what it claimed?
            if record.reported_confidence > 0.01:
                ratio = record.actual_accuracy / record.reported_confidence
            else:
                ratio = 1.0  # Don't penalise near-zero confidence

            total_weight += w
            weighted_ratio_sum += w * ratio

        if total_weight < 1e-9:
            return 1.0

        raw_weight = weighted_ratio_sum / total_weight

        # Clamp to reasonable range
        clamped = max(0.3, min(1.5, raw_weight))

        return clamped

    def _weighted_avg(
        self,
        cal: AgentCalibration,
        extractor: Any,
    ) -> float:
        """Compute decay-weighted average of a field."""
        total_w = 0.0
        total_v = 0.0
        n = len(cal.history)
        for i, record in enumerate(cal.history):
            age = n - 1 - i
            w = self._decay ** age
            total_w += w
            total_v += w * extractor(record)
        if total_w < 1e-9:
            return 0.0
        return total_v / total_w

    @property
    def tracked_agents(self) -> list[str]:
        """Agent IDs with calibration data."""
        return list(self._agents.keys())

    def reset(self, agent_id: str | None = None) -> None:
        """Reset calibration data for one or all agents."""
        if agent_id is not None:
            self._agents.pop(agent_id, None)
        else:
            self._agents.clear()
