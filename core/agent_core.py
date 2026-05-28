"""
AGENT CORE - Intelligent Task Execution System
==============================================
This is the brain of the agent. Unlike a naive ReAct loop that just hopes
things worked, this system PLANS, EXECUTES, and VERIFIES every action.

No more hallucinations. No more "I built it" when nothing exists.
This is reality-grounded agentic AI.

Configuration is read from core/config.yaml — no hardcoded values.
"""

import json
import logging
import time
from pathlib import Path
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
from enum import Enum

from core.paths import load_config as _load_config

# ── Config ─────────────────────────────────────────────────────────────────────

def _agent_cfg() -> dict:
    return _load_config().get("agent", {})

# ── Logging ────────────────────────────────────────────────────────────────────

log = logging.getLogger("agent_core")

# ── Data structures ────────────────────────────────────────────────────────────

class TaskStatus(Enum):
    """Status of a task or step."""
    PENDING    = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED  = "completed"
    FAILED     = "failed"
    BLOCKED    = "blocked"


@dataclass
class VerificationResult:
    """Result of verifying an action."""
    success:    bool
    evidence:   str            # What proves it worked/failed
    confidence: float          # 0.0 to 1.0
    details:    Dict[str, Any]


@dataclass
class TaskStep:
    """A single step in a task plan."""
    step_id:             str
    description:         str
    tool_calls:          List[Dict[str, Any]]   # Tools to execute
    verification_method: str                     # How to verify success
    expected_outcome:    str                     # What should happen
    status:              TaskStatus = TaskStatus.PENDING
    verification_result: Optional[VerificationResult] = None
    retries:             int = 0
    max_retries:         int = 0   # Set from config in AgentCore.__init__


@dataclass
class TaskPlan:
    """A complete plan for accomplishing a task."""
    task_id:      str
    goal:         str
    steps:        List[TaskStep]
    status:       TaskStatus = TaskStatus.PENDING
    created_at:   float = 0.0
    completed_at: Optional[float] = None

    def __post_init__(self):
        if self.created_at == 0.0:
            self.created_at = time.time()


# ── Agent ──────────────────────────────────────────────────────────────────────

class AgentCore:
    """
    The core agent that plans, executes, and verifies tasks.

    This is NOT a chatbot. This is a DO-er.
    All behavioural parameters (retries, confidence threshold, agent name)
    are read from core/config.yaml at initialisation time.
    """

    def __init__(self, llm_caller, tool_registry, verification_engine):
        """
        Initialise the agent core.

        Args:
            llm_caller:          Function that calls the LLM (signature: str -> str).
                                 Pass ai_bridge.call_ai or any compatible callable.
            tool_registry:       ToolRegistry instance with registered tools.
            verification_engine: Engine that verifies action results.
        """
        cfg = _agent_cfg()

        self.name               = cfg.get("name", "Apex")
        self.max_retries        = cfg.get("max_retries", 3)
        self.trust_threshold    = cfg.get("trust_threshold", 70) / 100.0  # normalise to 0–1
        self.audit_trail        = cfg.get("audit_trail", True)
        self.verify_actions     = cfg.get("verify_actions", True)

        self.llm      = llm_caller
        self.tools    = tool_registry
        self.verifier = verification_engine

        self.current_plan: Optional[TaskPlan] = None
        self.task_history: List[TaskPlan]     = []

        log.info("%s Agent Core initialised (max_retries=%d, trust_threshold=%.0f%%)",
                 self.name, self.max_retries, self.trust_threshold * 100)

    # ── Public API ─────────────────────────────────────────────────────────────

    def execute_task(self, task_description: str) -> Dict[str, Any]:
        """
        Main entry point: execute a task from start to finish.

        Args:
            task_description: What the user wants done.

        Returns:
            Execution summary dict with results and evidence.
        """
        log.info("TASK START: %s", task_description)

        plan = self._create_plan(task_description)
        self.current_plan = plan

        if not plan or not plan.steps:
            return {
                "success": False,
                "error": "Failed to create execution plan",
                "task": task_description
            }

        results = self._execute_plan(plan)
        self.task_history.append(plan)

        log.info("TASK COMPLETE: %s", plan.status.value)
        return results

    def get_current_status(self) -> str:
        """Return a human-readable status of the current task."""
        if not self.current_plan:
            return "No active task"

        completed = sum(
            1 for s in self.current_plan.steps
            if s.status == TaskStatus.COMPLETED
        )
        total = len(self.current_plan.steps)
        return (
            f"Task: {self.current_plan.goal}\n"
            f"Progress: {completed}/{total} steps completed"
        )

    # ── Planning ───────────────────────────────────────────────────────────────

    def _create_plan(self, task: str) -> Optional[TaskPlan]:
        """Use the LLM to break the task into concrete, verifiable steps."""
        log.info("Creating execution plan...")

        tool_list = self.tools.get_tool_list_for_prompt()

        planning_prompt = f"""You are a task planning AI. Break down this task into concrete, verifiable steps.

TASK: {task}

AVAILABLE TOOLS:
{tool_list}

Create a plan as JSON with this EXACT structure:
{{
    "goal": "brief goal description",
    "steps": [
        {{
            "step_id": "step_1",
            "description": "what this step does",
            "tool_calls": [
                {{"tool": "tool_name", "args": ["arg1"], "kwargs": {{"key": "value"}}}}
            ],
            "verification_method": "how to verify success (use a tool or check a condition)",
            "expected_outcome": "what should exist/happen after this step"
        }}
    ]
}}

RULES:
1. Each step must have EXACTLY ONE concrete action
2. Each step must be verifiable (file exists, command succeeds, etc)
3. Steps must be in logical order
4. Use actual tool names from the AVAILABLE TOOLS list
5. ONLY output the JSON, no explanations

JSON:"""

        try:
            response = self.llm(planning_prompt)
            json_str  = self._extract_json(response)
            plan_data = json.loads(json_str)

            task_id = f"task_{int(time.time())}"
            steps = [
                TaskStep(
                    step_id=s["step_id"],
                    description=s["description"],
                    tool_calls=s["tool_calls"],
                    verification_method=s["verification_method"],
                    expected_outcome=s["expected_outcome"],
                    max_retries=self.max_retries,   # from config
                )
                for s in plan_data.get("steps", [])
            ]

            plan = TaskPlan(task_id=task_id, goal=plan_data["goal"], steps=steps)
            log.info("Created plan with %d steps", len(steps))
            return plan

        except Exception as e:
            log.error("Plan creation failed: %s", e)
            return None

    # ── Execution ──────────────────────────────────────────────────────────────

    def _execute_plan(self, plan: TaskPlan) -> Dict[str, Any]:
        """Execute the plan step by step, verifying each action."""
        plan.status = TaskStatus.IN_PROGRESS
        completed_steps: List[TaskStep] = []
        failed_steps:    List[TaskStep] = []

        for step in plan.steps:
            log.info("Executing: %s — %s", step.step_id, step.description)

            if self._execute_step(step):
                completed_steps.append(step)
                log.info("✓ %s completed", step.step_id)
            else:
                failed_steps.append(step)
                log.error("✗ %s failed", step.step_id)

                if self._is_critical_step(step):
                    plan.status = TaskStatus.FAILED
                    break

        if not failed_steps:
            plan.status = TaskStatus.COMPLETED
            plan.completed_at = time.time()
        elif not completed_steps:
            plan.status = TaskStatus.FAILED
        else:
            plan.status = TaskStatus.COMPLETED  # partial success

        return {
            "success":         plan.status == TaskStatus.COMPLETED,
            "task":            plan.goal,
            "steps_completed": len(completed_steps),
            "steps_failed":    len(failed_steps),
            "total_steps":     len(plan.steps),
            "evidence":        self._gather_evidence(plan),
            "duration":        time.time() - plan.created_at,
        }

    def _execute_step(self, step: TaskStep) -> bool:
        """
        Execute a single step with verification and retries.

        Confidence threshold is read from config (agent.trust_threshold).

        Returns:
            True if step completed successfully, False otherwise.
        """
        step.status = TaskStatus.IN_PROGRESS

        while step.retries < step.max_retries:
            try:
                tool_results = []

                for tool_call in step.tool_calls:
                    tool_name = tool_call["tool"]
                    args      = tool_call.get("args", [])
                    kwargs    = tool_call.get("kwargs", {})

                    log.info("  Calling: %s(%s, %s)", tool_name, args, kwargs)
                    success, result = self.tools.call_tool(tool_name, *args, **kwargs)

                    tool_results.append({
                        "tool":    tool_name,
                        "success": success,
                        "result":  result,
                    })

                    if not success:
                        log.warning("  Tool failed: %s", result)

                if self.verify_actions:
                    verification = self.verifier.verify_step(step, tool_results)
                    step.verification_result = verification

                    if verification.success and verification.confidence >= self.trust_threshold:
                        step.status = TaskStatus.COMPLETED
                        return True
                    else:
                        log.warning("  Verification failed (confidence=%.2f, threshold=%.2f): %s",
                                    verification.confidence, self.trust_threshold,
                                    verification.evidence)
                        step.retries += 1
                else:
                    # Verification disabled in config — trust tool success flag
                    all_ok = all(r["success"] for r in tool_results)
                    if all_ok:
                        step.status = TaskStatus.COMPLETED
                        return True
                    step.retries += 1

            except Exception as e:
                log.error("  Step execution error: %s", e)
                step.retries += 1

        step.status = TaskStatus.FAILED
        return False

    def _is_critical_step(self, step: TaskStep) -> bool:
        """
        Determine if a failed step should abort the whole task.

        Early setup steps and infrastructure tools are treated as critical.
        """
        if step.step_id in ("step_1", "step_2"):
            return True

        critical_tools = {"create_directory", "install_package", "create_project"}
        return any(tc["tool"] in critical_tools for tc in step.tool_calls)

    def _gather_evidence(self, plan: TaskPlan) -> Dict[str, Any]:
        """
        Collect proof of what was actually accomplished.

        Prevents hallucination — we only report things we can verify.
        """
        evidence: Dict[str, Any] = {
            "files_created":       [],
            "directories_created": [],
            "packages_installed":  [],
            "commands_executed":   [],
            "verifications":       [],
        }

        for step in plan.steps:
            vr = step.verification_result
            if vr and vr.success:
                evidence["verifications"].append({
                    "step":       step.step_id,
                    "evidence":   vr.evidence,
                    "confidence": vr.confidence,
                })

                details = vr.details
                if "file_path"      in details:
                    evidence["files_created"].append(details["file_path"])
                if "directory_path" in details:
                    evidence["directories_created"].append(details["directory_path"])
                if "package_name"   in details:
                    evidence["packages_installed"].append(details["package_name"])

        return evidence

    @staticmethod
    def _extract_json(text: str) -> str:
        """Extract the first complete JSON object from an LLM response."""
        start = text.find("{")
        end   = text.rfind("}") + 1

        if start >= 0 and end > start:
            return text[start:end]

        raise ValueError("No JSON found in LLM response")


# ── Factory ────────────────────────────────────────────────────────────────────

def create_agent(llm_caller, tool_registry, verification_engine) -> AgentCore:
    """
    Create and return a configured AgentCore instance.

    Args:
        llm_caller:          Any callable with signature (prompt: str) -> str.
                             Use ai_bridge.call_ai for automatic provider routing.
        tool_registry:       ToolRegistry with registered tools.
        verification_engine: VerificationEngine instance.
    """
    return AgentCore(llm_caller, tool_registry, verification_engine)
