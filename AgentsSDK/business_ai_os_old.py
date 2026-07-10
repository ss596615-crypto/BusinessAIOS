"""
Business AI OS V2
business_ai_os.py

대표가 사용하는 최종 실행 파일
"""

from datetime import datetime

from runtime import runtime


def make_project_id(title: str) -> str:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    cleaned = "_".join(title.strip().split()) or "project"
    return f"{cleaned}_{timestamp}"


def print_organization(result: dict) -> None:
    print("\n" + "=" * 60)
    print("AI CEO 접수 완료")
    print("Workflow :", result["workflow_id"])
    print("업무 유형 :", result["business_type"])
    print("지점장 :", result["manager"]["role"])
    latest_workflow = runtime.report(result["workflow_id"])["workflow"]

worker_ids = latest_workflow.get(
    "worker_agent_ids",
    [],
)

print("직원 :", worker_ids)
    print("상태 :", result["status"])
    print("승인 :", result["approval_status"])


def print_progress(workflow_id: str) -> None:
    progress = runtime.progress(workflow_id)

    print("\n현재 상태")
    print("상태 :", progress["status"])
    print("승인 상태 :", progress["approval_status"])
    print("진행률 :", progress["progress_percent"], "%")
    print(
        "완료 단계 :",
        progress["completed_steps"],
        "/",
        progress["total_steps"],
    )


def main() -> None:
    print("=" * 60)
    print("Business AI OS V2")
    print("=" * 60)

    title = input("프로젝트 제목 : ").strip()
    objective = input("목표 : ").strip()
    owner_instruction = input("대표 지시 : ").strip()

    if not title:
        title = "신규 제품 출시"

    if not objective:
        objective = title

    if not owner_instruction:
        owner_instruction = objective

    project_id = make_project_id(title)

    try:
        result = runtime.start(
            title=title,
            objective=objective,
            owner_instruction=owner_instruction,
            project_id=project_id,
        )
    except Exception as error:
        print("\nBusiness AI OS 실행 오류")
        print(type(error).__name__, ":", error)
        return

    workflow_id = result["workflow_id"]
    print_organization(result)

    while True:
        command = input(
            "\n대표 명령 "
            "(approve / reject / status / report / exit) : "
        ).strip().lower()

        if command == "approve":
            try:
                approved = runtime.approve(workflow_id)
                workflow = approved["workflow"]

                print("\n승인 완료")
                print("최종 상태 :", workflow["status"])
                print_progress(workflow_id)
            except Exception as error:
                print("승인 처리 오류 :", error)

            break

        if command == "reject":
            reason = input("반려 사유 : ").strip()

            try:
                runtime.reject(
                    workflow_id,
                    reason or "대표 반려",
                )
                print("\nWorkflow 반려 완료")
                print_progress(workflow_id)
            except Exception as error:
                print("반려 처리 오류 :", error)

            break

        if command == "status":
            print_progress(workflow_id)
            continue

        if command == "report":
            try:
                report = runtime.report(workflow_id)
                workflow = report["workflow"]
                progress = report["progress"]

                print("\n" + "=" * 60)
                print("AI CEO 운영보고")
                print("프로젝트 :", workflow["title"])
                print("목표 :", workflow["objective"])
                print("상태 :", progress["status"])
                print("진행률 :", progress["progress_percent"], "%")
                print("결과 요약 :", workflow.get("result_summary") or "작성 중")
                print("다음 업무 :", workflow.get("next_action") or "결정 중")
                print("=" * 60)
            except Exception as error:
                print("보고서 조회 오류 :", error)

            continue

        if command == "exit":
            print("\nBusiness AI OS를 종료합니다.")
            break

        print(
            "approve / reject / status / report / exit 중 하나를 입력하세요."
        )

    print("=" * 60)
    print("Business AI OS 종료")
    print("=" * 60)


if __name__ == "__main__":
    main()
