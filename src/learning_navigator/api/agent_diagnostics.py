"""Agent diagnostics: inspect agent modules to determine implementation status.

Scans agent source files for stub markers and builds a status report.
"""

from __future__ import annotations

import inspect
import importlib
import textwrap
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import structlog

logger = structlog.get_logger(__name__)

# (agent_name, module_path, class_name, friendly_name, description)
AGENT_MODULES = [
    ("Diagnoser", "learning_navigator.agents.diagnoser", "DiagnoserAgent", "Gap Finder", "Identifies what you need to work on"),
    ("Planner", "learning_navigator.agents.planner", "PlannerAgent", "Study Planner", "Builds your personalized study plan"),
    ("Evaluator", "learning_navigator.agents.evaluator", "EvaluatorAgent", "Progress Analyst", "Measures how well you're doing"),
    ("Motivation", "learning_navigator.agents.motivation", "MotivationAgent", "Motivation Coach", "Tracks your energy and engagement"),
    ("Drift Detector", "learning_navigator.agents.drift_detector", "DriftDetectorAgent", "Focus Monitor", "Notices when your learning drifts"),
    ("Decay", "learning_navigator.agents.decay", "DecayAgent", "Memory Guard", "Flags topics you might forget"),
    ("Generative Replay", "learning_navigator.agents.generative_replay", "GenerativeReplayAgent", "Practice Generator", "Creates review exercises"),
    ("Skill State", "learning_navigator.agents.skill_state", "SkillStateAgent", "Knowledge Tracker", "Tracks what you know"),
    ("Behavior", "learning_navigator.agents.behavior", "BehaviorAgent", "Habit Analyst", "Understands your study patterns"),
    ("Time Optimizer", "learning_navigator.agents.time_optimizer", "TimeOptimizerAgent", "Schedule Optimizer", "Makes the most of your study time"),
    ("Reflection", "learning_navigator.agents.reflection", "ReflectionAgent", "Learning Mirror", "Helps you reflect on progress"),
    ("Mastery Maximizer", "learning_navigator.agents.debate_advocates", "MasteryMaximizer", "Mastery Maximizer", "Advocates for deep understanding"),
    ("Exam Strategist", "learning_navigator.agents.debate_advocates", "ExamStrategist", "Exam Strategist", "Advocates for exam-ready preparation"),
    ("Burnout Minimizer", "learning_navigator.agents.debate_advocates", "BurnoutMinimizer", "Burnout Minimizer", "Advocates for sustainable learning"),
    ("Debate Arbitrator", "learning_navigator.agents.debate_arbitrator", "DebateArbitrator", "Decision Maker", "Picks the best strategy for you"),
    ("RAG Agent", "learning_navigator.agents.rag_agent", "RAGAgent", "Research Helper", "Finds relevant study materials"),
]

STUB_MARKERS = ["TODO", "NotImplementedError", "raise NotImplemented", "STUB", "PLACEHOLDER"]


def _check_source(source: str) -> tuple[str, str]:
    """Analyze source code for stub markers.
    
    Returns (status, evidence).
    Status is one of: implemented, partial, stub
    """
    lines = source.strip().splitlines()
    
    # Check for stub markers
    stub_lines = []
    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        for marker in STUB_MARKERS:
            if marker in stripped:
                stub_lines.append(f"L{i}: {stripped[:80]}")
    
    # Check if handle method is just `pass`
    has_pass_only = False
    in_handle = False
    handle_lines = []
    for line in lines:
        if "def handle(" in line or "async def handle(" in line:
            in_handle = True
            handle_lines = []
            continue
        if in_handle:
            stripped = line.strip()
            if stripped and not stripped.startswith("#") and not stripped.startswith('"""') and not stripped.startswith("'''"):
                handle_lines.append(stripped)
                if stripped.startswith("def ") or stripped.startswith("async def ") or stripped.startswith("class "):
                    break
    
    if handle_lines and all(l in ("pass", "...") for l in handle_lines[:2]):
        has_pass_only = True
    
    # Count meaningful lines (excluding comments, docstrings, blank)
    meaningful = 0
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and not stripped.startswith('"""') and not stripped.startswith("'''"):
            meaningful += 1
    
    if has_pass_only:
        return "stub", "handle() method is pass-only"
    elif stub_lines:
        if len(stub_lines) > meaningful * 0.3:
            return "stub", f"Multiple stub markers: {'; '.join(stub_lines[:3])}"
        else:
            return "partial", f"Some markers: {'; '.join(stub_lines[:3])}"
    elif meaningful < 10:
        return "stub", f"Only {meaningful} meaningful lines"
    else:
        return "implemented", f"{meaningful} lines of logic"


def get_agents_status() -> list[dict[str, Any]]:
    """Scan all agent modules and return implementation status."""
    results = []
    
    for name, module_path, class_name, friendly_name, description in AGENT_MODULES:
        agent_id = name.lower().replace(" ", "_")
        entry: dict[str, Any] = {
            "agent_id": agent_id,
            "agent_name": name,
            "friendly_name": friendly_name,
            "description": description,
            "module": module_path,
            "class_name": class_name,
            "status": "unknown",
            "evidence": "",
            "file_path": "",
            "method_count": 0,
            "line_count": 0,
            "checked_at": datetime.now(timezone.utc).isoformat(),
        }
        
        try:
            mod = importlib.import_module(module_path)
            cls = getattr(mod, class_name, None)
            
            if cls is None:
                entry["status"] = "stub"
                entry["evidence"] = f"Class {class_name} not found in module"
                results.append(entry)
                continue
            
            # Get source file
            try:
                source_file = inspect.getfile(cls)
                entry["file_path"] = str(Path(source_file).relative_to(Path.cwd()))
            except (TypeError, ValueError):
                entry["file_path"] = module_path.replace(".", "/") + ".py"
            
            # Get source code
            try:
                source = inspect.getsource(cls)
                entry["line_count"] = len(source.splitlines())
            except OSError:
                entry["status"] = "unknown"
                entry["evidence"] = "Could not read source"
                results.append(entry)
                continue
            
            # Count methods
            methods = [m for m in dir(cls) if not m.startswith("_") and callable(getattr(cls, m, None))]
            entry["method_count"] = len(methods)
            
            # Analyze
            agent_status, evidence = _check_source(source)
            entry["status"] = agent_status
            entry["evidence"] = evidence
            
        except ImportError as e:
            entry["status"] = "error"
            entry["evidence"] = f"Import error: {e}"
        except Exception as e:
            entry["status"] = "error"
            entry["evidence"] = f"Error: {e}"
        
        results.append(entry)
    
    return results


def get_system_summary(agents: list[dict[str, Any]]) -> dict[str, Any]:
    """Compute a high-level system status summary."""
    total = len(agents)
    implemented = sum(1 for a in agents if a["status"] == "implemented")
    partial = sum(1 for a in agents if a["status"] == "partial")
    stubs = sum(1 for a in agents if a["status"] in ("stub", "error", "unknown"))
    health_pct = round((implemented + partial * 0.5) / total * 100, 1) if total else 0
    
    if implemented == total:
        level = "fully_active"
        label = "Fully Active"
        description = "All AI agents are fully implemented with real logic."
    elif implemented + partial >= total * 0.7:
        level = "mostly_active"
        label = "Mostly Active"
        description = f"{implemented} of {total} agents are fully implemented. {partial} are partially implemented."
    elif implemented > 0:
        level = "partially_active"
        label = "Partially Active"
        description = f"Only {implemented} of {total} agents are fully implemented."
    else:
        level = "limited"
        label = "Limited"
        description = "Most agents are stubs or placeholders."
    
    return {
        "total": total,
        "implemented": implemented,
        "partial": partial,
        "stub": stubs,
        "health_level": level,
        "health_pct": health_pct,
        "label": label,
        "description": description,
        "engine_type": "rule_based",
        "engine_note": "All agents use deterministic algorithms (BKT, Ebbinghaus decay, weighted scoring). No LLM calls.",
    }
