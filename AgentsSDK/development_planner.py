"""
development_planner.py
Business AI OS V2.6
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from workflow_manager import workflow_manager


@dataclass
class DevelopmentPlan:
    current_workflow_id: str
    next_title: str
    next_objective: str
    next_instruction: str
    priority: int = 1


class DevelopmentPlanner:
    """Development 완료 후 다음 개발 업무를 자동 생성한다."""

    def analyze(
        self,
        workflow_id: str,
        development_result: dict[str, Any] | None = None,
    ) -> DevelopmentPlan:

        result = development_result or {}

        title = str(
            result.get("next_title")
            or "다음 개발 업무"
        )

        objective = str(
            result.get("next_objective")
            or "Business AI OS를 다음 단계로 개발한다."
        )

        instruction = str(
            result.get("next_instruction")
            or "AI CEO가 개발 결과를 분석하여 다음 개발을 계속 수행한다."
        )

        return DevelopmentPlan(
            current_workflow_id=workflow_id,
            next_title=title,
            next_objective=objective,
            next_instruction=instruction,
        )

    def create_next_workflow(
        self,
        plan: DevelopmentPlan,
    ) -> dict[str, Any]:

        return workflow_manager.create_workflow(
            title=plan.next_title,
            objective=plan.next_objective,
            owner_instruction=plan.next_instruction,
            requested_by="ai_ceo",
            requires_approval=True,
            metadata={
                "created_by": "development_planner",
                "previous_workflow": plan.current_workflow_id,
                "development_mode": True,
                "execution_engine": "development_engine_v2",
            },
        )

    def build_ceo_report(
        self,
        plan: DevelopmentPlan,
        workflow_result: dict[str, Any],
    ) -> dict[str, Any]:

        workflow = workflow_result.get("workflow", {})

        return {
            "created_at": self._now(),
            "previous_workflow": plan.current_workflow_id,
            "next_workflow": workflow.get("workflow_id"),
            "status": workflow.get("status"),
            "approval_status": workflow.get("approval_status"),
            "title": plan.next_title,
            "objective": plan.next_objective,
            "next_action": "대표 승인 대기",
        }

    def register_workflow(
        self,
        workflow_id: str,
        development_result: dict[str, Any] | None = None,
    ) -> dict[str, Any]:

        plan = self.analyze(
            workflow_id,
            development_result,
        )

        created = self.create_next_workflow(plan)

        report = self.build_ceo_report(
            plan,
            created,
        )

        return {
            "success": True,
            "plan": plan.__dict__,
            "workflow": created,
            "ceo_report": report,
        }

    @staticmethod
    def _now() -> str:
        return datetime.now(
            timezone.utc
        ).isoformat()


development_planner = DevelopmentPlanner()
