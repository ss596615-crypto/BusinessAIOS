
"""
Business AI OS V2
manager_controller.py
"""

from workflow_manager import workflow_manager
from company_memory import company_memory
from handoff_manager import handoff_manager


class ManagerController:
    """
    제품관리 지점장 Controller

    역할
    1. CEO 업무 수신
    2. 기존 직원 확인
    3. 직원 배정
    4. 업무 위임
    5. 결과 검토
    6. CEO 보고
    """

    def assign_workers(self, workflow_id: str, worker_agent_ids: list[str]):
        return workflow_manager.assign_workers(
            workflow_id=workflow_id,
            worker_agent_ids=worker_agent_ids,
        )

    def review(self, workflow_id: str):
        workflow = workflow_manager.require_workflow(workflow_id)

        report = {
            "workflow_id": workflow_id,
            "title": workflow["title"],
            "manager": workflow["manager_agent_id"],
            "workers": workflow["worker_agent_ids"],
            "status": workflow["status"],
            "progress": workflow_manager.get_workflow_progress(workflow_id),
        }

        company_memory.remember_agent_result(
            title=f"지점장 검토 : {workflow['title']}",
            content="지점장이 업무 결과를 검토하고 CEO에게 보고하였다.",
            source_agent_id=workflow["manager_agent_id"],
            project_id=workflow.get("project_id"),
            related_agent_ids=workflow["worker_agent_ids"],
            importance=4,
            tags=["manager", "review"],
        )

        return report

    def handoff_to_worker(
        self,
        manager_agent_id: str,
        worker_agent_id: str,
        description: str,
    ):
        handoff = handoff_manager.get_handoff(
            source_agent_id=manager_agent_id,
            target_agent_id=worker_agent_id,
        )

        if handoff is None:
            return handoff_manager.register_handoff(
                source_agent_id=manager_agent_id,
                target_agent_id=worker_agent_id,
                description=description,
                created_reason="Manager Controller",
            )

        return {
            "created": False,
            "reason": "handoff_exists",
            "handoff": handoff,
        }


manager_controller = ManagerController()


if __name__ == "__main__":
    print("=" * 60)
    print("Manager Controller 테스트")
    print("이 모듈은 Workflow Manager와 연동됩니다.")
    print("주요 기능")
    print("1. 직원 배정")
    print("2. Handoff 생성")
    print("3. 결과 검토")
    print("4. CEO 보고")
    print("=" * 60)
