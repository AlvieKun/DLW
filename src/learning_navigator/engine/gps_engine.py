"""Learning GPS Engine — the main orchestrator.

Ingests ``LearnerEvent``s and produces ``NextBestAction`` recommendations
by routing through the agent ensemble:

    Event → Diagnoser → DriftDetector → Motivation → Planner →
    Evaluator (Maker-Checker) → HITL → NextBestAction

Each run is a single *tick* of the engine for one learner event.

Architecture highlights:
- Pipeline-based agent routing (v1, deterministic order).
- Maker-Checker loop between Planner and Evaluator.
- HITL hook for optional human override.
- Full telemetry via EventBus and structured logging.
- State is loaded/saved through MemoryStore.
"""

from __future__ import annotations

import contextlib
import uuid
from datetime import datetime, timezone
from typing import Any

import structlog

from learning_navigator.agents.behavior import BehaviorAgent
from learning_navigator.agents.diagnoser import DiagnoserAgent
from learning_navigator.agents.drift_detector import DriftDetectorAgent
from learning_navigator.agents.evaluator import EvaluatorAgent
from learning_navigator.agents.motivation import MotivationAgent
from learning_navigator.agents.planner import PlannerAgent
from learning_navigator.agents.reflection import ReflectionAgent
from learning_navigator.agents.skill_state import SkillStateAgent
from learning_navigator.agents.time_optimizer import TimeOptimizerAgent
from learning_navigator.contracts.events import (
    LearnerEvent,
    NextBestAction,
)
from learning_navigator.contracts.learner_state import LearnerState
from learning_navigator.contracts.messages import MessageEnvelope, MessageType
from learning_navigator.engine.event_bus import EventBus
from learning_navigator.engine.hitl import (
    DefaultHITLHook,
    HITLDecision,
    HITLHook,
    HITLRequest,
)
from learning_navigator.engine.maker_checker import (
    CheckVerdict,
    MakerChecker,
)
from learning_navigator.storage.interfaces import MemoryStore, PortfolioLogger

logger = structlog.get_logger(__name__)


class LearningGPSEngine:
    """Main orchestrator for the Learning Navigator."""

    def __init__(
        self,
        memory_store: MemoryStore,
        portfolio_logger: PortfolioLogger,
        event_bus: EventBus,
        hitl_hook: HITLHook | None = None,
        confidence_threshold: float = 0.6,
        maker_checker_rounds: int = 2,
    ) -> None:
        self.memory_store = memory_store
        self.portfolio_logger = portfolio_logger
        self.event_bus = event_bus
        self.hitl_hook = hitl_hook or DefaultHITLHook()
        self.confidence_threshold = confidence_threshold

        # Initialize agents
        self.diagnoser = DiagnoserAgent()
        self.drift_detector = DriftDetectorAgent()
        self.motivation_agent = MotivationAgent()
        self.planner = PlannerAgent()
        self.evaluator = EvaluatorAgent()
        self.skill_state = SkillStateAgent()
        self.behavior = BehaviorAgent()
        self.time_optimizer = TimeOptimizerAgent()
        self.reflection = ReflectionAgent()

        # Maker-Checker: Planner makes, Evaluator checks
        self.maker_checker = MakerChecker(
            maker=self.planner,
            checker=self.evaluator,
            max_rounds=maker_checker_rounds,
        )

    async def process_event(
        self, event: LearnerEvent
    ) -> NextBestAction:
        """Process a single learner event through the full pipeline.

        Returns a NextBestAction recommendation.
        """
        trace_id = str(uuid.uuid4())[:8]
        log = logger.bind(
            learner_id=event.learner_id,
            event_type=event.event_type.value,
            trace_id=trace_id,
        )
        log.info("engine.process_event.start")

        debug_trace: dict[str, Any] = {
            "trace_id": trace_id,
            "event_id": event.event_id,
            "pipeline_steps": [],
        }

        # 1. Load learner state
        state = await self.memory_store.get_learner_state(event.learner_id)
        if state is None:
            state = LearnerState(learner_id=event.learner_id)
            log.info("engine.new_learner_state")

        # 2. Diagnose
        diagnosis = await self._run_diagnoser(state, event)
        debug_trace["pipeline_steps"].append({
            "agent": "diagnoser",
            "confidence": diagnosis.get("confidence", 0),
        })

        # Update state from diagnosis (payload IS the diagnosis)
        state = self._apply_diagnosis(state, diagnosis)

        # 3. Detect drift
        drift_response = await self._run_drift_detector(state)
        debug_trace["pipeline_steps"].append({
            "agent": "drift_detector",
            "signals": len(drift_response.get("drift_signals", [])),
        })

        # Apply drift signals to state
        state = self._apply_drift(state, drift_response)

        # 4. Assess motivation
        motivation_response = await self._run_motivation(state, event)
        mot_state = motivation_response.get("motivation_state", {})
        debug_trace["pipeline_steps"].append({
            "agent": "motivation",
            "level": mot_state.get("level", "unknown"),
        })

        # Apply motivation update to state
        state = self._apply_motivation(state, motivation_response)

        # 4b. Skill State analysis
        skill_response = await self._run_skill_state(state)
        debug_trace["pipeline_steps"].append({
            "agent": "skill_state",
            "gaps": len(skill_response.get("prerequisite_gaps", [])),
        })

        # 4c. Behavior analysis
        behavior_response = await self._run_behavior(state, event)
        debug_trace["pipeline_steps"].append({
            "agent": "behavior",
            "anomalies": behavior_response.get("anomaly_count", 0),
        })
        state = self._apply_behavior(state, behavior_response)

        # 4d. Time Optimization
        time_response = await self._run_time_optimizer(state)
        debug_trace["pipeline_steps"].append({
            "agent": "time_optimizer",
            "allocations": len(time_response.get("allocations", [])),
        })

        # 5. Plan + Evaluate via Maker-Checker
        plan_message = self._build_plan_message(state, diagnosis, trace_id)
        mc_result = await self.maker_checker.run(
            maker_message=plan_message,
            learner_state_raw=state.model_dump(mode="json"),
        )
        debug_trace["pipeline_steps"].append({
            "agent": "maker_checker",
            "verdict": mc_result.verdict.value,
            "rounds": mc_result.rounds,
            "issues": len(mc_result.issues),
        })

        # 6. HITL check
        hitl_decision = await self._run_hitl(
            state, mc_result.maker_response, mc_result
        )
        debug_trace["hitl_decision"] = hitl_decision.value

        # 7. Save updated state
        state.updated_at = datetime.now(timezone.utc)
        await self.memory_store.save_learner_state(state)

        # 7b. Reflection narrative (post-pipeline)
        reflection_response = await self._run_reflection(
            state, diagnosis, drift_response, motivation_response,
            mc_result.maker_response, skill_response, behavior_response,
            time_response,
        )
        debug_trace["pipeline_steps"].append({
            "agent": "reflection",
            "sections": reflection_response.get("section_count", 0),
        })

        # 8. Publish event on bus
        await self._publish_result(event, mc_result, trace_id)

        # 9. Build and return NextBestAction
        nba = self._build_next_best_action(
            event, mc_result, debug_trace, hitl_decision
        )

        # 10. Log to portfolio
        from learning_navigator.storage.interfaces import PortfolioEntry

        await self.portfolio_logger.append(
            PortfolioEntry(
                entry_id=nba.action_id,
                learner_id=event.learner_id,
                entry_type="recommendation",
                timestamp=datetime.now(timezone.utc),
                source_agent_id="engine",
                data=nba.model_dump(mode="json"),
                correlation_id=trace_id,
            ),
        )

        log.info(
            "engine.process_event.complete",
            action=nba.recommended_action,
            confidence=nba.confidence,
        )
        return nba

    # ── Pipeline stage helpers ──────────────────────────────────────

    async def _run_diagnoser(
        self, state: LearnerState, event: LearnerEvent
    ) -> dict[str, Any]:
        """Run the diagnoser agent."""
        msg = MessageEnvelope(
            message_type=MessageType.DIAGNOSIS_REQUEST,
            source_agent_id="engine",
            target_agent_id="diagnoser",
            payload={
                "learner_state": state.model_dump(mode="json"),
                "event": event.model_dump(mode="json"),
            },
        )
        resp = await self.diagnoser.handle(msg)
        return resp.payload

    async def _run_drift_detector(
        self, state: LearnerState
    ) -> dict[str, Any]:
        """Run the drift detector agent."""
        msg = MessageEnvelope(
            message_type=MessageType.DRIFT_ALERT,
            source_agent_id="engine",
            target_agent_id="drift_detector",
            payload={
                "learner_state": state.model_dump(mode="json"),
            },
        )
        resp = await self.drift_detector.handle(msg)
        return resp.payload

    async def _run_motivation(
        self, state: LearnerState, event: LearnerEvent
    ) -> dict[str, Any]:
        """Run the motivation agent."""
        msg = MessageEnvelope(
            message_type=MessageType.MOTIVATION_UPDATE,
            source_agent_id="engine",
            target_agent_id="motivation",
            payload={
                "learner_state": state.model_dump(mode="json"),
                "event": event.model_dump(mode="json"),
            },
        )
        resp = await self.motivation_agent.handle(msg)
        return resp.payload

    async def _run_skill_state(
        self, state: LearnerState
    ) -> dict[str, Any]:
        """Run the skill state agent."""
        msg = MessageEnvelope(
            message_type=MessageType.SKILL_STATE_REQUEST,
            source_agent_id="engine",
            target_agent_id="skill-state",
            payload={
                "learner_state": state.model_dump(mode="json"),
            },
        )
        resp = await self.skill_state.handle(msg)
        return resp.payload

    async def _run_behavior(
        self, state: LearnerState, event: LearnerEvent
    ) -> dict[str, Any]:
        """Run the behavior agent."""
        msg = MessageEnvelope(
            message_type=MessageType.BEHAVIOR_REQUEST,
            source_agent_id="engine",
            target_agent_id="behavior",
            payload={
                "learner_state": state.model_dump(mode="json"),
                "event": event.model_dump(mode="json"),
            },
        )
        resp = await self.behavior.handle(msg)
        return resp.payload

    async def _run_time_optimizer(
        self, state: LearnerState
    ) -> dict[str, Any]:
        """Run the time optimizer agent."""
        msg = MessageEnvelope(
            message_type=MessageType.TIME_ALLOCATION_REQUEST,
            source_agent_id="engine",
            target_agent_id="time-optimizer",
            payload={
                "learner_state": state.model_dump(mode="json"),
            },
        )
        resp = await self.time_optimizer.handle(msg)
        return resp.payload

    async def _run_reflection(
        self,
        state: LearnerState,
        diagnosis: dict[str, Any],
        drift_response: dict[str, Any],
        motivation_response: dict[str, Any],
        plan_response: dict[str, Any],
        skill_state_response: dict[str, Any],
        behavior_response: dict[str, Any],
        time_response: dict[str, Any],
    ) -> dict[str, Any]:
        """Run the reflection agent with full pipeline context."""
        msg = MessageEnvelope(
            message_type=MessageType.REFLECTION_REQUEST,
            source_agent_id="engine",
            target_agent_id="reflection",
            payload={
                "learner_state": state.model_dump(mode="json"),
                "diagnosis": diagnosis,
                "drift_response": drift_response,
                "motivation_response": motivation_response,
                "plan_response": plan_response,
                "skill_state_response": skill_state_response,
                "behavior_response": behavior_response,
                "time_response": time_response,
            },
        )
        resp = await self.reflection.handle(msg)
        return resp.payload

    def _build_plan_message(
        self,
        state: LearnerState,
        diagnosis: dict[str, Any],
        trace_id: str,
    ) -> MessageEnvelope:
        """Build the message for the Planner."""
        return MessageEnvelope(
            message_type=MessageType.PLAN_READY,
            source_agent_id="engine",
            target_agent_id="planner",
            payload={
                "learner_state": state.model_dump(mode="json"),
                "diagnosis": diagnosis,
            },
            correlation_id=trace_id,
        )

    async def _run_hitl(
        self,
        state: LearnerState,
        plan: dict[str, Any],
        mc_result: Any,
    ) -> HITLDecision:
        """Run HITL review if needed."""
        quality_score = mc_result.checker_response.get("quality_score", 0.0)
        issues = mc_result.issues

        needs_review = await self.hitl_hook.should_require_review(
            quality_score, issues
        )

        if not needs_review:
            return HITLDecision.AUTO_APPROVED

        request = HITLRequest(
            request_id=str(uuid.uuid4())[:8],
            learner_id=state.learner_id,
            recommendation=plan,
            agent_rationale=mc_result.rationale,
            quality_score=quality_score,
            issues=issues,
        )
        response = await self.hitl_hook.request_review(request)
        return response.decision

    async def _publish_result(
        self,
        event: LearnerEvent,
        mc_result: Any,
        trace_id: str,
    ) -> None:
        """Publish the pipeline result to the EventBus."""
        msg = MessageEnvelope(
            message_type=MessageType.ACTION_RECOMMENDED,
            source_agent_id="engine",
            payload={
                "learner_id": event.learner_id,
                "verdict": mc_result.verdict.value,
                "trace_id": trace_id,
            },
            correlation_id=trace_id,
        )
        await self.event_bus.publish(msg)

    def _build_next_best_action(
        self,
        event: LearnerEvent,
        mc_result: Any,
        debug_trace: dict[str, Any],
        hitl_decision: HITLDecision,
    ) -> NextBestAction:
        """Build the final NextBestAction from pipeline results."""
        recommendations = mc_result.maker_response.get("recommendations", [])

        if hitl_decision == HITLDecision.REJECT:
            return NextBestAction(
                action_id=str(uuid.uuid4())[:8],
                learner_id=event.learner_id,
                recommended_action="hold",
                rationale="Recommendation rejected by reviewer",
                confidence=0.0,
                expected_learning_gain=0.0,
                risk_assessment={"rejected": 1.0},
                debug_trace=debug_trace,
            )

        if not recommendations:
            return NextBestAction(
                action_id=str(uuid.uuid4())[:8],
                learner_id=event.learner_id,
                recommended_action="general_review",
                rationale="No specific recommendations generated",
                confidence=0.3,
                expected_learning_gain=0.1,
                debug_trace=debug_trace,
            )

        top = recommendations[0]
        risk_assessment: dict[str, float] = {}

        # Build risk from checker issues
        for issue in mc_result.issues:
            issue_type = issue.get("type", "unknown")
            risk_assessment[issue_type] = risk_assessment.get(issue_type, 0.0) + 0.2

        confidence = mc_result.final_confidence
        if mc_result.verdict == CheckVerdict.NEEDS_REVISION:
            confidence = min(confidence, 0.4)

        return NextBestAction(
            action_id=str(uuid.uuid4())[:8],
            learner_id=event.learner_id,
            recommended_action=f"{top.get('action', 'study')}:{top.get('concept_id', 'unknown')}",
            rationale=mc_result.rationale,
            confidence=max(0.0, min(1.0, confidence)),
            expected_learning_gain=min(1.0, top.get("priority_score", 0.5) * 0.15),
            risk_assessment=risk_assessment,
            debug_trace=debug_trace,
        )

    # ── State mutation helpers ──────────────────────────────────────

    @staticmethod
    def _apply_diagnosis(
        state: LearnerState, diagnosis: dict[str, Any]
    ) -> LearnerState:
        """Apply diagnostic updates to learner state."""
        from learning_navigator.contracts.learner_state import BKTParams, ConceptState

        updates = diagnosis.get("updates", [])
        for update in updates:
            concept_id = update.get("concept_id")
            new_mastery = update.get("new_mastery")
            if concept_id and new_mastery is not None:
                concept = state.get_concept(concept_id)
                if concept:
                    concept.bkt.p_know = new_mastery
                else:
                    # Create new concept from diagnostic update
                    state.upsert_concept(
                        ConceptState(
                            concept_id=concept_id,
                            bkt=BKTParams(p_know=new_mastery),
                        )
                    )
        return state

    @staticmethod
    def _apply_drift(
        state: LearnerState, drift_response: dict[str, Any]
    ) -> LearnerState:
        """Apply drift signals to learner state."""
        from learning_navigator.contracts.learner_state import DriftSignal

        signals = drift_response.get("drift_signals", [])
        for sig in signals:
            state.active_drift_signals.append(
                DriftSignal(
                    drift_type=sig.get("drift_type", "unknown"),
                    severity=sig.get("severity", 0.5),
                )
            )
        return state

    @staticmethod
    def _apply_motivation(
        state: LearnerState, motivation_response: dict[str, Any]
    ) -> LearnerState:
        """Apply motivation assessment to learner state."""
        from learning_navigator.contracts.learner_state import MotivationLevel

        # The MotivationAgent returns {motivation_state: {level, score, trend, ...}, ...}
        mot_state = motivation_response.get("motivation_state", {})
        level_str = mot_state.get("level")
        score = mot_state.get("score")
        trend = mot_state.get("trend")

        if level_str:
            with contextlib.suppress(ValueError):
                state.motivation.level = MotivationLevel(level_str)
        if score is not None:
            state.motivation.score = score
        if trend is not None:
            state.motivation.trend = trend

        return state

    @staticmethod
    def _apply_behavior(
        state: LearnerState, behavior_response: dict[str, Any]
    ) -> LearnerState:
        """Apply behavioural anomalies to learner state."""
        from learning_navigator.contracts.learner_state import BehavioralAnomaly

        anomalies = behavior_response.get("anomalies", [])
        for anomaly in anomalies:
            state.behavioral_anomalies.append(
                BehavioralAnomaly(
                    anomaly_type=anomaly.get("anomaly_type", "unknown"),
                    severity=anomaly.get("severity", 0.5),
                    evidence=anomaly.get("evidence", {}),
                )
            )
        return state
