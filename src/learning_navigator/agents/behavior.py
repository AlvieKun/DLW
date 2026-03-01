"""Behavior Agent — pattern anomaly detection in learner behaviour.

Detects abnormal behavioural patterns that may indicate problems the
other agents (Diagnoser, Drift Detector) would miss.  These are patterns
that emerge from *how* a learner interacts, not *what* they know.

Detected anomaly types:
• **cramming**       — high practice volume in short bursts before deadlines
• **rapid_guessing** — very short response times suggesting random guessing
• **avoidance**      — systematically skipping certain concepts
• **irregular_sessions** — highly variable session lengths / frequencies
• **late_night_study**   — sessions at unusual hours (risk of fatigue)
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any

import structlog

from learning_navigator.agents.base import (
    AgentCapability,
    AgentMetadata,
    AgentResponse,
    BaseAgent,
)
from learning_navigator.contracts.learner_state import (
    LearnerState,
)
from learning_navigator.contracts.messages import MessageEnvelope

logger = structlog.get_logger(__name__)


class BehaviorAgent(BaseAgent):
    """Analyses learner behaviour patterns and flags anomalies."""

    def __init__(
        self,
        cramming_threshold_hours: float = 24.0,
        cramming_min_sessions: int = 5,
        rapid_guess_max_seconds: float = 3.0,
        avoidance_min_concepts: int = 3,
        avoidance_practice_ratio: float = 0.2,
        irregular_cv_threshold: float = 0.8,
    ) -> None:
        super().__init__(
            AgentMetadata(
                agent_id="behavior",
                display_name="Behavior Agent",
                capabilities=[AgentCapability.BEHAVIOR_ANALYSIS],
                cost_tier=1,
                description="Detects behavioural anomalies: cramming, guessing, avoidance, irregular sessions.",
            )
        )
        self.cramming_threshold_hours = cramming_threshold_hours
        self.cramming_min_sessions = cramming_min_sessions
        self.rapid_guess_max_seconds = rapid_guess_max_seconds
        self.avoidance_min_concepts = avoidance_min_concepts
        self.avoidance_practice_ratio = avoidance_practice_ratio
        self.irregular_cv_threshold = irregular_cv_threshold

    async def handle(self, message: MessageEnvelope) -> AgentResponse:
        state_raw = message.payload.get("learner_state", {})
        event_raw = message.payload.get("event", {})
        state = LearnerState.model_validate(state_raw)

        log = logger.bind(
            agent=self.agent_id,
            learner_id=state.learner_id,
        )
        log.info("behavior.start")

        anomalies: list[dict[str, Any]] = []
        signals_checked: list[str] = []

        # 1. Cramming detection
        cramming = self._detect_cramming(state)
        signals_checked.append("cramming")
        if cramming:
            anomalies.append(cramming)

        # 2. Rapid guessing
        rapid = self._detect_rapid_guessing(state, event_raw)
        signals_checked.append("rapid_guessing")
        if rapid:
            anomalies.append(rapid)

        # 3. Concept avoidance
        avoidance = self._detect_avoidance(state)
        signals_checked.append("avoidance")
        if avoidance:
            anomalies.append(avoidance)

        # 4. Irregular sessions
        irregular = self._detect_irregular_sessions(state)
        signals_checked.append("irregular_sessions")
        if irregular:
            anomalies.append(irregular)

        # 5. Late-night study
        late_night = self._detect_late_night(state)
        signals_checked.append("late_night_study")
        if late_night:
            anomalies.append(late_night)

        max_severity = max((a["severity"] for a in anomalies), default=0.0)
        confidence = min(1.0, 0.4 + 0.1 * state.session_count)

        payload: dict[str, Any] = {
            "anomalies": anomalies,
            "anomaly_detected": len(anomalies) > 0,
            "anomaly_count": len(anomalies),
            "max_severity": round(max_severity, 3),
            "signals_checked": signals_checked,
            "confidence": round(confidence, 3),
        }

        rationale = self._build_rationale(anomalies)
        log.info("behavior.complete", anomaly_count=len(anomalies))

        return AgentResponse(
            source_agent_id=self.agent_id,
            confidence=confidence,
            payload=payload,
            rationale=rationale,
        )

    # ── detectors ───────────────────────────────────────────────────

    def _detect_cramming(self, state: LearnerState) -> dict[str, Any] | None:
        """Detect cramming: high practice volume concentrated near deadline.

        Heuristic: deadline within `cramming_threshold_hours` AND many recent
        sessions (session_count >= cramming_min_sessions) with most practice
        on a few concepts.
        """
        deadline = state.time_budget.deadline
        if deadline is None:
            return None

        now = datetime.now(timezone.utc)
        hours_to_deadline = (deadline - now).total_seconds() / 3600.0
        if hours_to_deadline > self.cramming_threshold_hours or hours_to_deadline < 0:
            return None

        if state.session_count < self.cramming_min_sessions:
            return None

        # Check concentration: variance of practice counts across concepts
        practice_counts = [c.practice_count for c in state.concepts.values()]
        if not practice_counts or max(practice_counts) < 3:
            return None

        severity = min(1.0, 0.4 + 0.3 * (1.0 - hours_to_deadline / self.cramming_threshold_hours))
        return {
            "anomaly_type": "cramming",
            "severity": round(severity, 3),
            "evidence": {
                "hours_to_deadline": round(hours_to_deadline, 1),
                "session_count": state.session_count,
                "max_practice_count": max(practice_counts),
            },
        }

    def _detect_rapid_guessing(
        self, state: LearnerState, event_raw: dict[str, Any]
    ) -> dict[str, Any] | None:
        """Detect rapid guessing from event metadata.

        Looks for `response_time_seconds` in event data.
        """
        event_data = event_raw.get("data", {})
        response_time = event_data.get("response_time_seconds")
        if response_time is None:
            return None

        if response_time > self.rapid_guess_max_seconds:
            return None

        # Also check: low mastery + quick response = likely guessing
        concept_id = event_raw.get("concept_id")
        mastery = 0.5
        if concept_id:
            concept = state.get_concept(concept_id)
            if concept:
                mastery = concept.mastery

        # Low mastery + fast response → high severity
        severity = min(1.0, 0.3 + 0.4 * (1.0 - mastery) + 0.3 * (1.0 - response_time / self.rapid_guess_max_seconds))
        return {
            "anomaly_type": "rapid_guessing",
            "severity": round(severity, 3),
            "evidence": {
                "response_time_seconds": response_time,
                "concept_id": concept_id,
                "mastery": round(mastery, 3),
            },
        }

    def _detect_avoidance(self, state: LearnerState) -> dict[str, Any] | None:
        """Detect concept avoidance: some concepts have much less practice.

        If the learner has >= `avoidance_min_concepts` concepts and some have
        practice_count < `avoidance_practice_ratio` x max_practice_count,
        flag avoidance.
        """
        if len(state.concepts) < self.avoidance_min_concepts:
            return None

        practice_counts = {
            cid: c.practice_count for cid, c in state.concepts.items()
        }
        max_practice = max(practice_counts.values(), default=0)
        if max_practice < 3:
            return None

        threshold = max_practice * self.avoidance_practice_ratio
        avoided = [
            cid for cid, count in practice_counts.items()
            if count <= threshold
        ]

        if not avoided:
            return None

        severity = min(1.0, 0.3 + 0.1 * len(avoided))
        return {
            "anomaly_type": "avoidance",
            "severity": round(severity, 3),
            "evidence": {
                "avoided_concepts": avoided,
                "max_practice_count": max_practice,
                "threshold": round(threshold, 1),
            },
        }

    def _detect_irregular_sessions(self, state: LearnerState) -> dict[str, Any] | None:
        """Detect highly variable session patterns using spacing history.

        Uses coefficient of variation across all concept spacing intervals.
        """
        all_intervals: list[float] = []
        for concept in state.concepts.values():
            all_intervals.extend(concept.spacing_history)

        if len(all_intervals) < 4:
            return None

        mean = sum(all_intervals) / len(all_intervals)
        if mean <= 0:
            return None

        variance = sum((x - mean) ** 2 for x in all_intervals) / len(all_intervals)
        std = math.sqrt(variance)
        cv = std / mean

        if cv < self.irregular_cv_threshold:
            return None

        severity = min(1.0, 0.3 + 0.3 * (cv - self.irregular_cv_threshold))
        return {
            "anomaly_type": "irregular_sessions",
            "severity": round(severity, 3),
            "evidence": {
                "coefficient_of_variation": round(cv, 3),
                "mean_interval_hours": round(mean, 1),
                "std_interval_hours": round(std, 1),
                "interval_count": len(all_intervals),
            },
        }

    @staticmethod
    def _detect_late_night(state: LearnerState) -> dict[str, Any] | None:
        """Detect late-night study pattern from last_active timestamp.

        Flags if last active between 00:00-05:00 UTC (configurable in future).
        """
        if state.last_active is None:
            return None

        hour = state.last_active.hour
        if hour >= 5:
            return None

        severity = 0.3 if hour >= 2 else 0.5
        return {
            "anomaly_type": "late_night_study",
            "severity": severity,
            "evidence": {
                "last_active_hour_utc": hour,
                "last_active": state.last_active.isoformat(),
            },
        }

    @staticmethod
    def _build_rationale(anomalies: list[dict[str, Any]]) -> str:
        if not anomalies:
            return "No behavioural anomalies detected. Learner patterns appear normal."

        types = [a["anomaly_type"] for a in anomalies]
        max_sev = max(a["severity"] for a in anomalies)
        return (
            f"Detected {len(anomalies)} anomal{'y' if len(anomalies) == 1 else 'ies'}: "
            f"{', '.join(types)}. Max severity: {max_sev:.2f}."
        )
