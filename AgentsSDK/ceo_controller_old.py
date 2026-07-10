
"""
Business AI OS V2
ceo_controller.py

Top-level CEO controller.

Responsibilities
- Receive owner goal
- Load company memory
- Validate company assets
- Build workflow
- Delegate to managers
- Request approval
- Resume after approval
- Report results
"""

from workflow_manager import workflow_manager
from company_memory import company_memory


class CEOController:
    """Top-level orchestration layer for the AI CEO."""

    def start(
        self,
        *,
        title: str,
        objective: str,
        owner_instruction: str,
        manager_agent_id: str,
        worker_agent_ids: list[str],
        project_id: str | None = None,
    ):
        workflow = workflow_manager.create_workflow(
            title=title,
            objective=objective,
            owner_instruction=owner_instruction,
            ceo_agent_id="ceo_001",
            manager_agent_id=manager_agent_id,
            worker_agent_ids=worker_agent_ids,
            project_id=project_id,
            requires_approval=True,
        )

        workflow_id = workflow["workflow"]["workflow_id"]

        execution = workflow_manager.run_workflow(workflow_id)

        return {
            "workflow_id": workflow_id,
            "status": execution["workflow"]["status"],
            "approval_status": execution["workflow"]["approval_status"],
        }

    def approve(self, workflow_id: str):
        return workflow_manager.approve_workflow(
            workflow_id,
            approval_note="대표 승인",
            approved_by="owner",
            auto_resume=True,
        )

    def reject(self, workflow_id: str, reason: str):
        return workflow_manager.reject_workflow(
            workflow_id,
            rejection_reason=reason,
            rejected_by="owner",
        )

    def report(self, workflow_id: str):
        workflow = workflow_manager.require_workflow(workflow_id)
        progress = workflow_manager.get_workflow_progress(workflow_id)

        return {
            "workflow": workflow,
            "progress": progress,
            "context": company_memory.build_context_text(
                project_id=workflow.get("project_id"),
                limit=20,
            ),
        }


ceo_controller = CEOController()


if __name__ == "__main__":
    result = ceo_controller.start(
        title="식물성 멜라토닌 OEM 조사",
        objective="OEM 조사 후 대표 승인",
        owner_instruction="제품 관리 지점장에게 위임하고 OEM 직원이 조사한다.",
        manager_agent_id="manager_product_001",
        worker_agent_ids=["oem_staff_001"],
        project_id="project_melatonin_001",
    )

    print("=" * 60)
    print("CEO Controller 테스트")
    print(result)

    approved = ceo_controller.approve(result["workflow_id"])
    print("최종 상태:", approved["workflow"]["status"])
    print("=" * 60)
