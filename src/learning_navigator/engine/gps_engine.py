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

from learning_navigator.agents.base import BaseAgent
from learning_navigator.agents.behavior import BehaviorAgent
from learning_navigator.agents.debate_advocates import (
    BurnoutMinimizer,
    ExamStrategist,
    MasteryMaximizer,
)
from learning_navigator.agents.debate_arbitrator import DebateArbitrator
from learning_navigator.agents.decay import DecayAgent
from learning_navigator.agents.diagnoser import DiagnoserAgent
from learning_navigator.agents.drift_detector import DriftDetectorAgent
from learning_navigator.agents.evaluator import EvaluatorAgent
from learning_navigator.agents.generative_replay import GenerativeReplayAgent
from learning_navigator.agents.motivation import MotivationAgent
from learning_navigator.agents.planner import PlannerAgent
from learning_navigator.agents.rag_agent import RAGAgent
from learning_navigator.agents.reflection import ReflectionAgent
from learning_navigator.agents.skill_state import SkillStateAgent
from learning_navigator.agents.time_optimizer import TimeOptimizerAgent
from learning_navigator.contracts.events import (
    LearnerEvent,
    NextBestAction,
)
from learning_navigator.contracts.learner_state import LearnerState
from learning_navigator.contracts.messages import MessageEnvelope, MessageType
from learning_navigator.engine.adaptive_router import AdaptiveRouter
from learning_navigator.engine.confidence_calibrator import ConfidenceCalibrator
from learning_navigator.engine.debate import DebateEngine, DebateResult
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
from learning_navigator.storage.interfaces import (
    MemoryStore,
    PortfolioLogger,
    RetrievalIndex,
)

logger = structlog.get_logger(__name__)


class LearningGPSEngine:
    """Main orchestrator for the Learning Navigator."""

    def __init__(
        self,
        memory_store: MemoryStore,
        portfolio_logger: PortfolioLogger,
        event_bus: EventBus,
        hitl_hook: HITLHook | None = None,
        retrieval_index: RetrievalIndex | None = None,
        confidence_threshold: float = 0.6,
        maker_checker_rounds: int = 2,
        debate_enabled: bool = True,
        max_debate_rounds: int = 2,
        adaptive_routing_enabled: bool = False,
        cost_budget_per_turn: float = 10.0,
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
        self.decay = DecayAgent()
        self.generative_replay = GenerativeReplayAgent()
        self.reflection = ReflectionAgent()

        # RAG retrieval (optional — disabled when no index provided)
        self._retrieval_index = retrieval_index
        self.rag_agent: RAGAgent | None = (
            RAGAgent(retrieval_index) if retrieval_index else None
        )

        # Debate advocates + arbitrator
        self.mastery_maximizer = MasteryMaximizer()
        self.exam_strategist = ExamStrategist()
        self.burnout_minimizer = BurnoutMinimizer()
        self.debate_arbitrator = DebateArbitrator()

        # Maker-Checker: Planner makes, Evaluator checks
        self.maker_checker = MakerChecker(
            maker=self.planner,
            checker=self.evaluator,
            max_rounds=maker_checker_rounds,
        )

        # Strategic debate engine (post Maker-Checker)
        self.debate_engine = DebateEngine(
            advocates=[
                self.mastery_maximizer,
                self.exam_strategist,
                self.burnout_minimizer,
            ],
            arbitrator=self.debate_arbitrator,
            max_rounds=max_debate_rounds,
            enabled=debate_enabled,
        )

        # Build the agent registry for adaptive routing
        self._agent_registry: dict[str, BaseAgent] = {
            self.diagnoser.agent_id: self.diagnoser,
            self.drift_detector.agent_id: self.drift_detector,
            self.motivation_agent.agent_id: self.motivation_agent,
            self.skill_state.agent_id: self.skill_state,
            self.behavior.agent_id: self.behavior,
            self.decay.agent_id: self.decay,
            self.generative_replay.agent_id: self.generative_replay,
            self.time_optimizer.agent_id: self.time_optimizer,
            self.planner.agent_id: self.planner,
            self.evaluator.agent_id: self.evaluator,
            self.reflection.agent_id: self.reflection,
        }
        if self.rag_agent is not None:
            self._agent_registry[self.rag_agent.agent_id] = self.rag_agent

        # Adaptive routing (Phase 8)
        self.adaptive_router = AdaptiveRouter(
            agents=self._agent_registry,
            budget=cost_budget_per_turn,
            enabled=adaptive_routing_enabled,
        )

        # Confidence calibrator (Phase 8)
        self.confidence_calibrator = ConfidenceCalibrator()

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

        # 1b. Adaptive routing — decide which agents to run
        routing = self.adaptive_router.route(
            state,
            recent_drift_count=len(state.active_drift_signals),
            recent_anomaly_count=len(state.behavioral_anomalies),
            has_decay_risk=any(
                c.forgetting_score > 0.5 for c in state.concepts.values()
            ),
        )
        debug_trace["routing"] = {
            "selected": routing.selected_agents,
            "skipped": routing.skipped_agents,
            "full_pipeline": routing.full_pipeline,
            "budget": routing.budget,
            "total_cost": routing.total_cost,
            "uncertainty": routing.uncertainty_score,
        }

        def _should_run(agent_id: str) -> bool:
            return agent_id in routing.selected_agents

        # 2. Diagnose
        diagnosis = await self._run_diagnoser(state, event)
        debug_trace["pipeline_steps"].append({
            "agent": "diagnoser",
            "confidence": diagnosis.get("confidence", 0),
        })

        # Update state from diagnosis (payload IS the diagnosis)
        state = self._apply_diagnosis(state, diagnosis)

        # 3. Detect drift
        if _should_run("drift-detector"):
            drift_response = await self._run_drift_detector(state)
            debug_trace["pipeline_steps"].append({
                "agent": "drift_detector",
                "signals": len(drift_response.get("drift_signals", [])),
            })
            state = self._apply_drift(state, drift_response)
        else:
            drift_response: dict[str, Any] = {"drift_signals": []}
            debug_trace["pipeline_steps"].append(
                {"agent": "drift_detector", "skipped": True}
            )

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
        if _should_run("skill-state"):
            skill_response = await self._run_skill_state(state)
            debug_trace["pipeline_steps"].append({
                "agent": "skill_state",
                "gaps": len(skill_response.get("prerequisite_gaps", [])),
            })
        else:
            skill_response: dict[str, Any] = {"prerequisite_gaps": []}
            debug_trace["pipeline_steps"].append(
                {"agent": "skill_state", "skipped": True}
            )

        # 4c. Behavior analysis
        if _should_run("behavior"):
            behavior_response = await self._run_behavior(state, event)
            debug_trace["pipeline_steps"].append({
                "agent": "behavior",
                "anomalies": behavior_response.get("anomaly_count", 0),
            })
            state = self._apply_behavior(state, behavior_response)
        else:
            behavior_response: dict[str, Any] = {"anomaly_count": 0}
            debug_trace["pipeline_steps"].append(
                {"agent": "behavior", "skipped": True}
            )

        # 4d. Decay analysis (forgetting curves)
        if _should_run("decay"):
            decay_response = await self._run_decay(state)
            debug_trace["pipeline_steps"].append({
                "agent": "decay",
                "at_risk": decay_response.get("at_risk_count", 0),
            })
            state = self._apply_decay(state, decay_response)
        else:
            decay_response: dict[str, Any] = {"at_risk_count": 0}
            debug_trace["pipeline_steps"].append(
                {"agent": "decay", "skipped": True}
            )

        # 4e. Generative Replay (synthetic exercises)
        if _should_run("generative-replay"):
            replay_response = await self._run_generative_replay(
                state, decay_response
            )
            debug_trace["pipeline_steps"].append({
                "agent": "generative_replay",
                "exercises": replay_response.get("total_exercises", 0),
            })
        else:
            replay_response: dict[str, Any] = {"total_exercises": 0}
            debug_trace["pipeline_steps"].append(
                {"agent": "generative_replay", "skipped": True}
            )

        # 4f. Time Optimization
        if _should_run("time-optimizer"):
            time_response = await self._run_time_optimizer(state)
            debug_trace["pipeline_steps"].append({
                "agent": "time_optimizer",
                "allocations": len(time_response.get("allocations", [])),
            })
        else:
            time_response: dict[str, Any] = {"allocations": []}
            debug_trace["pipeline_steps"].append(
                {"agent": "time_optimizer", "skipped": True}
            )

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

        # 5b. Strategic Debate (post Maker-Checker)
        debate_result = await self.debate_engine.run(
            plan=mc_result.maker_response,
            learner_state_raw=state.model_dump(mode="json"),
            correlation_id=trace_id,
        )
        debug_trace["pipeline_steps"].append({
            "agent": "debate",
            "outcome": debate_result.outcome.value,
            "rounds": debate_result.rounds_used,
            "amendments": len(debate_result.accepted_amendments),
            "alignment": debate_result.overall_alignment,
        })

        # 5c. RAG retrieval — ground plan recommendations with citations
        rag_response: dict[str, Any] = {}
        if self.rag_agent is not None and _should_run("rag-agent"):
            rag_response = await self._run_rag(
                state, mc_result.maker_response, diagnosis
            )
            debug_trace["pipeline_steps"].append({
                "agent": "rag",
                "citations": rag_response.get("citation_count", 0),
                "queries": rag_response.get("query_count", 0),
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
        if _should_run("reflection"):
            reflection_response = await self._run_reflection(
                state, diagnosis, drift_response, motivation_response,
                mc_result.maker_response, skill_response, behavior_response,
                time_response, decay_response, replay_response,
                debate_result=debate_result,
                rag_response=rag_response,
            )
            debug_trace["pipeline_steps"].append({
                "agent": "reflection",
                "sections": reflection_response.get("section_count", 0),
            })
        else:
            debug_trace["pipeline_steps"].append(
                {"agent": "reflection", "skipped": True}
            )

        # 8. Publish event on bus
        await self._publish_result(event, mc_result, trace_id)

        # 9. Build and return NextBestAction
        nba = self._build_next_best_action(
            event, mc_result, debug_trace, hitl_decision,
            rag_response=rag_response,
            state=state,
            diagnosis=diagnosis,
            drift_response=drift_response,
            motivation_response=motivation_response,
            decay_response=decay_response,
            time_response=time_response,
            debate_result=debate_result,
        )

        # 9b. Apply confidence calibration
        nba.confidence = self.confidence_calibrator.calibrate(
            "engine", nba.confidence,
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

    async def _run_decay(
        self, state: LearnerState
    ) -> dict[str, Any]:
        """Run the decay agent (forgetting-curve analysis)."""
        msg = MessageEnvelope(
            message_type=MessageType.DECAY_REQUEST,
            source_agent_id="engine",
            target_agent_id="decay",
            payload={
                "learner_state": state.model_dump(mode="json"),
            },
        )
        resp = await self.decay.handle(msg)
        return resp.payload

    async def _run_generative_replay(
        self, state: LearnerState, decay_report: dict[str, Any]
    ) -> dict[str, Any]:
        """Run the generative replay agent."""
        msg = MessageEnvelope(
            message_type=MessageType.REPLAY_REQUEST,
            source_agent_id="engine",
            target_agent_id="generative-replay",
            payload={
                "learner_state": state.model_dump(mode="json"),
                "decay_report": decay_report,
            },
        )
        resp = await self.generative_replay.handle(msg)
        return resp.payload

    async def _run_rag(
        self,
        state: LearnerState,
        plan: dict[str, Any],
        diagnosis: dict[str, Any],
    ) -> dict[str, Any]:
        """Run the RAG agent to retrieve grounded citations."""
        assert self.rag_agent is not None
        msg = MessageEnvelope(
            message_type=MessageType.RAG_QUERY,
            source_agent_id="engine",
            target_agent_id="rag-agent",
            payload={
                "learner_state": state.model_dump(mode="json"),
                "plan": plan,
                "diagnosis": diagnosis,
            },
        )
        resp = await self.rag_agent.handle(msg)
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
        decay_response: dict[str, Any] | None = None,
        replay_response: dict[str, Any] | None = None,
        debate_result: DebateResult | None = None,
        rag_response: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Run the reflection agent with full pipeline context."""
        debate_payload: dict[str, Any] = {}
        if debate_result is not None:
            debate_payload = {
                "outcome": debate_result.outcome.value,
                "rounds_used": debate_result.rounds_used,
                "overall_alignment": debate_result.overall_alignment,
                "accepted_amendments": debate_result.accepted_amendments,
                "perspective_weights": debate_result.perspective_weights,
            }

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
                "decay_response": decay_response or {},
                "replay_response": replay_response or {},
                "debate_response": debate_payload,
                "rag_response": rag_response or {},
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
        rag_response: dict[str, Any] | None = None,
        state: LearnerState | None = None,
        diagnosis: dict[str, Any] | None = None,
        drift_response: dict[str, Any] | None = None,
        motivation_response: dict[str, Any] | None = None,
        decay_response: dict[str, Any] | None = None,
        time_response: dict[str, Any] | None = None,
        debate_result: DebateResult | None = None,
    ) -> NextBestAction:
        """Build the final NextBestAction from pipeline results."""
        from learning_navigator.contracts.events import (
            Explainability,
            ExplainabilityFactor,
            DecisionTrace,
            ExpectedImpact,
        )

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

        # Extract citation keys from RAG response
        citations: list[str] = []
        if rag_response:
            for cite in rag_response.get("citations", []):
                doc_id = cite.get("doc_id", "")
                if doc_id:
                    citations.append(doc_id)

        # ── Build explainability from real pipeline signals ──────────
        top_factors: list[ExplainabilityFactor] = []

        # Factor from Diagnoser: mastery gaps
        if diagnosis:
            gap_updates = diagnosis.get("updates", [])
            if gap_updates:
                weakest = min(gap_updates, key=lambda u: u.get("new_mastery", 1.0))
                top_factors.append(ExplainabilityFactor(
                    agent_id="diagnoser",
                    agent_name="Diagnoser",
                    signal="mastery_gap_detected",
                    evidence=f"Found mastery gap on '{weakest.get('concept_id', 'unknown')}' "
                             f"(mastery: {weakest.get('new_mastery', 0):.0%})",
                    confidence=diagnosis.get("confidence", None),
                ))

        # Factor from Decay: forgetting risk
        if decay_response and decay_response.get("at_risk_count", 0) > 0:
            risk_count = decay_response["at_risk_count"]
            concept_reports = decay_response.get("concept_reports", {})
            worst_concept = ""
            worst_score = 0.0
            for cid, report in concept_reports.items():
                score = report.get("forgetting_score", 0)
                if score > worst_score:
                    worst_score = score
                    worst_concept = cid
            evidence = f"Memory Guard flagged {risk_count} topic{'s' if risk_count > 1 else ''} at high review urgency"
            if worst_concept:
                evidence += f" (highest: '{worst_concept}' at {worst_score:.0%})"
            top_factors.append(ExplainabilityFactor(
                agent_id="decay",
                agent_name="Decay",
                signal="high_forgetting_risk",
                evidence=evidence,
            ))

        # Factor from Drift Detector
        if drift_response and drift_response.get("drift_signals"):
            signals = drift_response["drift_signals"]
            top_factors.append(ExplainabilityFactor(
                agent_id="drift-detector",
                agent_name="Drift Detector",
                signal="drift_detected",
                evidence=f"Focus Monitor detected {len(signals)} learning drift signal{'s' if len(signals) > 1 else ''}",
            ))

        # Factor from Motivation
        if motivation_response:
            mot_state = motivation_response.get("motivation_state", {})
            level = mot_state.get("level", "")
            if level in ("LOW", "CRITICAL"):
                top_factors.append(ExplainabilityFactor(
                    agent_id="motivation",
                    agent_name="Motivation",
                    signal="low_motivation",
                    evidence=f"Motivation Coach detected {level.lower()} motivation — recommendation adjusted for engagement",
                    confidence=mot_state.get("confidence", None),
                ))

        # Factor from Time Optimizer
        if time_response and time_response.get("allocations"):
            allocs = time_response["allocations"]
            top_factors.append(ExplainabilityFactor(
                agent_id="time-optimizer",
                agent_name="Time Optimizer",
                signal="time_allocation",
                evidence=f"Time Optimizer allocated study time across {len(allocs)} topic{'s' if len(allocs) > 1 else ''}",
            ))

        # Factor from Debate (if it changed the plan)
        if debate_result and debate_result.accepted_amendments:
            top_factors.append(ExplainabilityFactor(
                agent_id="debate-arbitrator",
                agent_name="Debate Arbitrator",
                signal="debate_amendment",
                evidence=f"Strategic debate refined the plan with {len(debate_result.accepted_amendments)} amendment{'s' if len(debate_result.accepted_amendments) > 1 else ''} "
                         f"(alignment: {debate_result.overall_alignment:.0%})",
            ))

        # Limit to 6 factors max
        top_factors = top_factors[:6]

        # Build decision trace from routing info
        routing_info = debug_trace.get("routing", {})
        ran_agents = routing_info.get("selected", [])
        skipped_agents = routing_info.get("skipped", [])

        debate_outcome_trace: dict[str, Any] | None = None
        if debate_result:
            debate_outcome_trace = {
                "outcome": debate_result.outcome.value,
                "rounds_used": debate_result.rounds_used,
                "alignment": debate_result.overall_alignment,
            }

        mc_trace: dict[str, Any] | None = None
        if mc_result:
            mc_trace = {
                "verdict": mc_result.verdict.value,
                "rounds": mc_result.rounds,
                "issues": len(mc_result.issues),
            }

        explainability = Explainability(
            top_factors=top_factors,
            decision_trace=DecisionTrace(
                ran_agents=ran_agents,
                skipped_agents=skipped_agents,
                debate_outcome=debate_outcome_trace,
                maker_checker=mc_trace,
            ),
        )

        # ── Build expected_impact from real signals ──────────────────
        target_concept = top.get("concept_id", "")
        mastery_gain: float | None = None
        risk_reduction: dict[str, float] = {}
        assumptions: list[str] = []

        if state and target_concept:
            concept = state.get_concept(target_concept)
            if concept:
                current_mastery = concept.bkt.p_know
                # Conservative estimate: one practice session typically moves mastery
                # by 5-15% depending on current level (diminishing returns)
                gap = 1.0 - current_mastery
                mastery_gain = round(min(0.15, gap * 0.2), 3)
                assumptions.append(
                    f"Based on current mastery of {current_mastery:.0%} for '{target_concept}'"
                )

                # Forgetting risk reduction
                if concept.forgetting_score > 0.3:
                    reduction = round(concept.forgetting_score * 0.4, 3)
                    risk_reduction["forgetting"] = reduction
                    assumptions.append("Spaced review reduces forgetting risk")
            else:
                assumptions.append("Insufficient history for numeric estimate")
        else:
            assumptions.append("Insufficient history for numeric estimate")

        # Burnout risk reduction if motivation is low
        if motivation_response:
            mot_state = motivation_response.get("motivation_state", {})
            if mot_state.get("level") in ("LOW", "CRITICAL"):
                assumptions.append("Recommendation accounts for low motivation")

        expected_impact = ExpectedImpact(
            mastery_gain_estimate=mastery_gain,
            risk_reduction=risk_reduction if risk_reduction else {},
            time_horizon_days=7,
            assumptions=assumptions if assumptions else ["Insufficient history for numeric estimate"],
        )

        return NextBestAction(
            action_id=str(uuid.uuid4())[:8],
            learner_id=event.learner_id,
            recommended_action=f"{top.get('action', 'study')}:{top.get('concept_id', 'unknown')}",
            rationale=mc_result.rationale,
            confidence=max(0.0, min(1.0, confidence)),
            expected_learning_gain=min(1.0, top.get("priority_score", 0.5) * 0.15),
            risk_assessment=risk_assessment,
            citations=citations,
            debug_trace=debug_trace,
            explainability=explainability,
            expected_impact=expected_impact,
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

    @staticmethod
    def _apply_decay(
        state: LearnerState, decay_response: dict[str, Any]
    ) -> LearnerState:
        """Apply decay analysis -- update forgetting scores on concept states."""
        concept_reports = decay_response.get("concept_reports", {})
        for cid, report in concept_reports.items():
            concept = state.get_concept(cid)
            if concept is not None:
                new_score = report.get("forgetting_score", concept.forgetting_score)
                state.upsert_concept(
                    concept.model_copy(update={"forgetting_score": new_score})
                )
        return state
