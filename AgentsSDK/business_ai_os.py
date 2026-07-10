"""
Business AI OS V2
business_ai_os.py

대표가 지시 한 줄만 입력하는 최종 실행 파일
"""

from datetime import datetime

from runtime import runtime


def make_project_id(instruction: str) -> str:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    cleaned = "_".join(instruction.strip().split()) or "project"
    cleaned = cleaned[:40]
    return f"{cleaned}_{timestamp}"


def make_project_title(instruction: str) -> str:
    cleaned = " ".join(instruction.strip().split())

    for ending in (
        "구축하고 출시하라.",
        "구축하고 출시하라",
        "만들어라.",
        "만들어라",
        "출시하라.",
        "출시하라",
        "진행하라.",
        "진행하라",
    ):
        if cleaned.endswith(ending):
            cleaned = cleaned[: -len(ending)].strip()
            break

    return cleaned or "신규 프로젝트"


def print_organization(result: dict) -> None:
    print("\n" + "=" * 60)
    print("AI CEO 접수 완료")
    print("Workflow :", result["workflow_id"])
    print("업무 유형 :", result["business_type"])
    print("지점장 :", result["manager"]["role"])

    latest_workflow = runtime.report(
        result["workflow_id"]
    )["workflow"]

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

    owner_instruction = input("대표 지시 : ").strip()

    if not owner_instruction:
        print("대표 지시는 비어 있을 수 없습니다.")
        return

    title = make_project_title(owner_instruction)
    objective = owner_instruction
    project_id = make_project_id(owner_instruction)

    print("\n자동 생성")
    print("프로젝트 제목 :", title)
    print("목표 :", objective)

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
                print(
                    "직원 :",
                    workflow.get("worker_agent_ids", []),
                )
                print(
                    "결과 요약 :",
                    workflow.get("result_summary") or "작성 중",
                )
                print(
                    "다음 업무 :",
                    workflow.get("next_action") or "결정 중",
                )
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
