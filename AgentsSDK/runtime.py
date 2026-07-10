"""
Business AI OS V2
runtime.py

통합 Runtime
"""

import re

from ceo_controller import ceo_controller
from manager import manager_controller
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
        project_id: str | None = None,
    ):
        return ceo_controller.start(
            title=title,
            objective=objective,
            owner_instruction=owner_instruction,
            project_id=project_id,
        )

    def process_instruction(
        self,
        *,
        title: str,
        objective: str,
        owner_instruction: str,
        project_id: str | None = None,
    ):
        """기존 Workflow 명령은 신규 생성 없이 처리하고, 그 외만 새로 시작한다."""
        match = re.search(r"\b(wf_[0-9a-fA-F]{8,64})\b", owner_instruction)
        existing_words = (
            "조회", "검증", "재실행", "재개", "취소", "상태 확인",
            "산출물", "증거", "git diff", "테스트 결과", "계속 구현",
        )
        if match and any(word in owner_instruction.lower() for word in existing_words):
            return workflow_manager.handle_existing_workflow_request(
                match.group(1), owner_instruction
            )
        return self.start(
            title=title, objective=objective,
            owner_instruction=owner_instruction, project_id=project_id,
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
    print("Business AI Runtime 완성본 테스트 시작")

    result = runtime.start(
        title="I-um Bio 식물성 멜라토닌 출시",
        objective=(
            "식물성 멜라토닌 제품을 기획하고 "
            "OEM 제조 준비와 시장 검토를 진행한다."
        ),
        owner_instruction="식물성 멜라토닌 제품을 출시하라.",
        project_id="project_melatonin_launch_001",
    )

    wf = result["workflow_id"]

    print("Workflow:", wf)
    print("업무 유형:", result["business_type"])
    print("지점장:", result["manager"]["role"])
    print(
        "직원:",
        [worker["role"] for worker in result["workers"]],
    )
    print("상태:", result["status"])
    print("승인:", result["approval_status"])

    runtime.approve(wf)

    p = runtime.progress(wf)

    print("-" * 60)
    print("최종 상태:", p["status"])
    print("진행률:", p["progress_percent"], "%")
    print("완료 단계:", p["completed_steps"], "/", p["total_steps"])
    print("=" * 60)
