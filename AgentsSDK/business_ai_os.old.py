
"""
Business AI OS V2
business_ai_os.py

최종 진입점
"""

from runtime import runtime


def main():
    print("=" * 60)
    print("Business AI OS V2")
    print("=" * 60)

    title = input("프로젝트 제목 : ").strip()
    objective = input("목표 : ").strip()
    instruction = input("대표 지시 : ").strip()

    if not title:
        title = "신규 프로젝트"

    if not objective:
        objective = title

    if not instruction:
        instruction = objective

    result = runtime.start(
        title=title,
        objective=objective,
        owner_instruction=instruction,
        manager_agent_id="manager_product_001",
        worker_agent_ids=["oem_staff_001"],
        project_id="default_project",
    )

    workflow_id = result["workflow_id"]

    print("\n" + "=" * 60)
    print("AI CEO 접수 완료")
    print("Workflow :", workflow_id)
    print("상태 :", result["status"])
    print("승인 :", result["approval_status"])

    while True:
        answer = input("\n대표 승인 (approve / reject / status / exit) : ").strip().lower()

        if answer == "approve":
            runtime.approve(workflow_id)
            progress = runtime.progress(workflow_id)
            print("\n승인 완료")
            print("최종 상태 :", progress["status"])
            print("진행률 :", progress["progress_percent"], "%")
            print("완료 단계 :", progress["completed_steps"], "/", progress["total_steps"])
            break

        elif answer == "reject":
            reason = input("반려 사유 : ").strip()
            runtime.reject(workflow_id, reason or "대표 반려")
            print("Workflow 반려 완료")
            break

        elif answer == "status":
            progress = runtime.progress(workflow_id)
            print(progress)

        elif answer == "exit":
            print("종료합니다.")
            break

        else:
            print("approve / reject / status / exit 중 하나를 입력하세요.")

    print("=" * 60)
    print("Business AI OS 종료")
    print("=" * 60)


if __name__ == "__main__":
    main()
