"""
DREAM CYCLE - Nightly Reflection and Learning
==============================================
While idle, the agent reflects on recent tasks,
consolidating learning, and optimizing for future sessions.

This is the closest thing to neural network training without actually
modifying weights. Pure symbolic learning through reflection.
"""

import time
import json
import logging
from pathlib import Path
from typing import Dict, List, Any, Optional
from datetime import datetime, timedelta

from core.paths import MEMORY_DIR, load_config

log = logging.getLogger("dream")


def _storage_base() -> Path:
    cfg = load_config()
    return Path(cfg.get("storage", {}).get("memory", str(MEMORY_DIR)))


class DreamCycle:
    """
    Nightly reflection and learning system.

    Runs during idle time to:
    - Review the day's tasks
    - Extract deep patterns
    - Identify improvements
    - Consolidate learnings
    - Plan optimizations
    """

    def __init__(self, experience_engine, self_evolution, storage_path: str = None):
        self.experience = experience_engine
        self.evolution = self_evolution

        if storage_path is None:
            storage_path = str(_storage_base() / "dreams")
        self.storage_path = Path(storage_path)
        self.storage_path.mkdir(parents=True, exist_ok=True)

        self.dreams_file = self.storage_path / "dream_log.json"
        self.insights_file = self.storage_path / "insights.json"

        self.dreams: List[Dict] = []
        self.insights: List[Dict] = []

        self._load()
        log.info("Dream Cycle: %s dreams, %s insights", len(self.dreams), len(self.insights))

    def run_dream_cycle(self, llm_caller) -> Dict[str, Any]:
        """
        Run a complete dream cycle.

        This is the agent's nightly reflection process.

        Args:
            llm_caller: Function to call LLM for reflection

        Returns:
            Dream summary
        """
        dream_id = "dream_%s" % int(time.time())

        log.info("=" * 60)
        log.info("DREAM CYCLE STARTING")
        log.info("=" * 60)

        stats = self.experience.get_statistics()

        start_time = time.time()

        # Phase 1: Review
        review = self._review_recent_tasks()

        # Phase 2: Extract insights
        insights = self._extract_insights(llm_caller, review)

        # Phase 3: Identify improvements
        improvements = self._identify_improvements(llm_caller, insights)

        # Phase 4: Plan tomorrow
        plan = self._plan_tomorrow(stats, insights)

        dream = {
            "dream_id": dream_id,
            "timestamp": start_time,
            "tasks_reviewed": len(review),
            "insights_gained": len(insights),
            "improvements_identified": len(improvements),
            "plan": plan,
            "duration": time.time() - start_time
        }

        self.dreams.append(dream)
        self.insights.extend(insights)

        self._save()

        log.info("Dream complete: %s insights, %s improvements", len(insights), len(improvements))
        log.info("=" * 60)

        return dream

    def _review_recent_tasks(self) -> List[Dict]:
        """Review tasks from the last 24 hours."""
        cutoff = time.time() - 24 * 3600

        recent = []
        for task in self.experience.task_history:
            if task["timestamp"] > cutoff:
                recent.append(task)

        log.info("Reviewing %s recent tasks", len(recent))
        return recent

    def _extract_insights(self, llm_caller, tasks: List[Dict]) -> List[Dict]:
        """
        Use LLM to extract deep insights from tasks.

        This is where symbolic learning happens.
        """
        if not tasks:
            return []

        task_summary = []
        for t in tasks[-10:]:
            task_summary.append({
                "description": t["description"],
                "success": t["success"],
                "duration": t["duration"]
            })

        prompt = """Reflect on these recent tasks and extract KEY INSIGHTS:

Tasks:
%s

What patterns do you see? What can be learned?

Respond with JSON array of insights:
[
    {
        "insight": "brief insight",
        "impact": "how this improves future performance",
        "confidence": 0.8
    }
]

ONLY output the JSON array, nothing else.""" % json.dumps(task_summary, indent=2)

        try:
            response = llm_caller(prompt)

            import re
            json_match = re.search(r'\[.*\]', response, re.DOTALL)
            if json_match:
                insights_raw = json.loads(json_match.group(0))

                insights = []
                for ins in insights_raw:
                    ins["timestamp"] = time.time()
                    ins["source"] = "dream_cycle"
                    insights.append(ins)

                return insights
        except Exception as e:
            log.error("Insight extraction failed: %s", e)

        return []

    def _identify_improvements(self, llm_caller, insights: List[Dict]) -> List[Dict]:
        """Identify concrete improvements based on insights."""
        if not insights:
            return []

        prompt = """Based on these insights, suggest ONE concrete improvement:

Insights:
%s

Respond with JSON:
{
    "improvement_type": "new_tool|optimization|refactor",
    "description": "what to improve",
    "priority": "high|medium|low"
}

ONLY output JSON.""" % json.dumps(insights, indent=2)

        try:
            response = llm_caller(prompt)

            import re
            json_match = re.search(r'\{[^}]+\}', response)
            if json_match:
                improvement = json.loads(json_match.group(0))
                improvement["timestamp"] = time.time()
                improvement["status"] = "identified"
                return [improvement]
        except:
            pass

        return []

    def _plan_tomorrow(self, stats: Dict, insights: List[Dict]) -> Dict[str, Any]:
        """Create a plan for the next session based on learnings."""
        plan = {
            "focus_areas": [],
            "improvements_to_test": [],
            "goals": []
        }

        if stats.get("recent_success_rate", 1.0) < 0.8:
            plan["focus_areas"].append("improve_reliability")
            plan["goals"].append("Increase success rate above 80%")

        pending = self.evolution.get_pending_improvements()
        if pending:
            plan["improvements_to_test"] = [p["description"] for p in pending[:3]]

        for insight in insights[-3:]:
            if insight.get("confidence", 0) > 0.7:
                plan["goals"].append(insight.get("impact", ""))

        return plan

    def get_latest_insights(self, count: int = 5) -> List[Dict]:
        """Get the most recent insights."""
        return sorted(self.insights, key=lambda x: x.get("timestamp", 0), reverse=True)[:count]

    def _load(self):
        """Load dream data."""
        if self.dreams_file.exists():
            try:
                with open(self.dreams_file, "r") as f:
                    self.dreams = json.load(f)
            except:
                pass

        if self.insights_file.exists():
            try:
                with open(self.insights_file, "r") as f:
                    self.insights = json.load(f)
            except:
                pass

    def _save(self):
        """Save dream data."""
        with open(self.dreams_file, "w") as f:
            json.dump(self.dreams[-100:], f, indent=2)

        with open(self.insights_file, "w") as f:
            json.dump(self.insights[-200:], f, indent=2)


# Singleton
_dream_cycle = None


def get_dream_cycle(experience_engine, self_evolution) -> DreamCycle:
    global _dream_cycle
    if _dream_cycle is None:
        _dream_cycle = DreamCycle(experience_engine, self_evolution)
    return _dream_cycle


# -----------------------------
# TOOL REGISTRATION
# -----------------------------
def register_tools(registry) -> None:
    registry.register("dream_run_cycle", lambda llm_caller: get_dream_cycle(None, None).run_dream_cycle(llm_caller))
    registry.register("dream_get_insights", lambda count=5: get_dream_cycle(None, None).get_latest_insights(count))
    registry.register("dream_get_improvements", lambda: get_dream_cycle(None, None)._identify_improvements(None, []))
