
"""
Business AI OS V2
runtime.py

통합 Runtime
"""

from ceo_controller import ceo_controller
from manager_controller import manager_controller
from worker_controller import worker_controller
from workflow_manager import workflow_manager


class BusinessAIRuntime:
    """
    Runtime 역할

    1. 시스템 초기화
    2. CEO 실행
    3. Workflow 실행
    4. 승인 처리
    5. 상태 조회
    """

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
        return ceo_controller.start(
            title=title,
            objective=objective,
            owner_instruction=owner_instruction,
            manager_agent_id=manager_agent_id,
            worker_agent_ids=worker_agent_ids,
            project_id=project_id,
        )

    def approve(self, workflow_id: str):
        return ceo_controller.approve(workflow_id)

    def reject(self, workflow_id: str, reason: str):
        return ceo_controller.reject(workflow_id, reason)

    def report(self, workflow_id: str):
        return ceo_controller.report(workflow_id)

    def progress(self, workflow_id: str):
        return workflow_manager.get_workflow_progress(workflow_id)

    def assign_workers(self, workflow_id: str, worker_ids: list[str]):
        return manager_controller.assign_workers(
            workflow_id=workflow_id,
            worker_agent_ids=worker_ids,
        )

    def worker_context(self, workflow_id: str):
        return worker_controller.build_context(workflow_id)


runtime = BusinessAIRuntime()


if __name__ == "__main__":
    print("=" * 60)
    print("Business AI Runtime 테스트 시작")

    result = runtime.start(
        title="식물성 멜라토닌 OEM 조사",
        objective="OEM 견적 조사",
        owner_instruction="제품관리 지점장이 OEM 직원에게 업무를 위임한다.",
        manager_agent_id="manager_product_001",
        worker_agent_ids=["oem_staff_001"],
        project_id="project_melatonin_001",
    )

    wf = result["workflow_id"]

    print("Workflow:", wf)
    print("상태:", result["status"])
    print("승인:", result["approval_status"])

    runtime.approve(wf)

    p = runtime.progress(wf)

    print("-" * 60)
    print("최종 상태:", p["status"])
    print("진행률:", p["progress_percent"], "%")
    print("완료 단계:", p["completed_steps"], "/", p["total_steps"])
    print("=" * 60)
