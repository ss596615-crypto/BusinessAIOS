from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

from agents import Agent, Runner
from pydantic import BaseModel, Field

from agent_registry import AgentRegistry, registry
from company_memory import CompanyMemory, company_memory


# =========================================================
# 저장 위치
# =========================================================

BASE_DIR = Path(__file__).resolve().parent
GENERATED_DIR = BASE_DIR / "generated_projects"


# =========================================================
# 예외
# =========================================================

class WorkerControllerError(Exception):
    """AI 직원 공통 실행 중 발생하는 기본 예외."""


class WorkerExecutionError(WorkerControllerError):
    """AI 직원의 실제 업무 실행이 실패했을 때 발생한다."""


class ArtifactWriteError(WorkerControllerError):
    """결과물 파일 저장에 실패했을 때 발생한다."""


# =========================================================
# 구조화 출력
# =========================================================

class GeneratedFile(BaseModel):
    relative_path: str = Field(
        description=(
            "프로젝트 출력 폴더 기준 상대 경로. "
            "예: index.html, assets/style.css, reports/market_report.md"
        )
    )
    content: str = Field(
        description="파일에 저장할 전체 내용"
    )
    purpose: str = Field(
        default="",
        description="이 파일의 역할"
    )


class PermissionRequest(BaseModel):
    service: str = Field(
        description="권한이 필요한 서비스명. 예: Google Drive, Zapier, GitHub"
    )
    reason: str = Field(
        description="이 권한이 필요한 구체적인 이유"
    )
    requested_scope: str = Field(
        default="",
        description="필요한 권한 범위"
    )
    resume_action: str = Field(
        description="대표 승인 후 자동으로 이어서 수행할 작업"
    )


class WorkerExecutionResult(BaseModel):
    status: str = Field(
        description=(
            "completed 또는 waiting_permission 중 하나"
        )
    )
    work_summary: str = Field(
        description="실제로 수행한 업무 요약"
    )
    result_summary: str = Field(
        description="지점장에게 보고할 최종 결과 요약"
    )
    files: list[GeneratedFile] = Field(
        default_factory=list,
        description="생성해야 할 실제 결과물 파일 목록"
    )
    permission_requests: list[PermissionRequest] = Field(
        default_factory=list,
        description="사람 승인이 필요한 외부 도구 또는 계정 권한 요청"
    )
    next_action: str = Field(
        default="",
        description="다음으로 이어서 수행할 업무"
    )
    limitations: list[str] = Field(
        default_factory=list,
        description="실제로 완료하지 못한 사항 또는 제약"
    )


# =========================================================
# Worker Controller
# =========================================================

class WorkerController:
    """
    모든 AI 직원이 공통으로 사용하는 실제 업무 실행 엔진.

    역할:
    1. Workflow와 직원 정보를 읽는다.
    2. 직원의 역할·지침·배정 업무를 OpenAI Agent에 전달한다.
    3. 실제 결과물 내용을 생성한다.
    4. 결과물을 generated_projects/<workflow_id>/ 아래에 저장한다.
    5. 외부 서비스 권한이 필요하면 승인 요청을 반환한다.
    6. 결과를 Company Memory에 저장하고 지점장에게 보고한다.

    중요한 원칙:
    - 특정 업종이나 업무를 코드에 고정하지 않는다.
    - 홈페이지, 제품기획, 시장조사, 정부지원사업 등 모든 직원이 사용한다.
    - 외부 서비스 작업을 실제로 하지 않았으면 완료했다고 주장하지 않는다.
    - 생성 파일은 지정된 프로젝트 출력 폴더 밖으로 저장하지 않는다.
    """

    def __init__(
        self,
        *,
        agent_registry: AgentRegistry | None = None,
        company_memory_instance: CompanyMemory | None = None,
        generated_dir: Path = GENERATED_DIR,
    ) -> None:
        self.registry = agent_registry or registry
        self.company_memory = (
            company_memory_instance or company_memory
        )
        self.generated_dir = generated_dir
        self.generated_dir.mkdir(
            parents=True,
            exist_ok=True,
        )

    # =====================================================
    # Workflow 실행 단계 진입점
    # =====================================================

    def execute_step(
        self,
        *,
        workflow: dict[str, Any],
        step: dict[str, Any],
    ) -> dict[str, Any]:
        workflow_id = str(
            workflow.get("workflow_id", "")
        )
        worker_agent_id = str(
            step.get("assigned_agent_id", "")
        )

        if not workflow_id:
            raise WorkerExecutionError(
                "Workflow ID가 없습니다."
            )

        if not worker_agent_id:
            raise WorkerExecutionError(
                "실행 단계에 배정된 직원이 없습니다."
            )

        return self.execute(
            workflow_id=workflow_id,
            worker_agent_id=worker_agent_id,
            workflow=workflow,
            step=step,
        )

    # =====================================================
    # 실제 직원 업무 수행
    # =====================================================

    def execute(
        self,
        *,
        workflow_id: str,
        worker_agent_id: str,
        workflow: dict[str, Any] | None = None,
        step: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if workflow is None:
            from workflow_manager import workflow_manager

            workflow = workflow_manager.require_workflow(
                workflow_id
            )

        # 개발 업무는 일반 결과물 생성이 아니라 실제 저장소 수정 엔진으로 실행한다.
        from development_engine import development_engine
        if development_engine.is_development_workflow(workflow):
            return development_engine.execute(
                workflow=workflow,
                worker_agent_id=worker_agent_id,
            )

        worker_record = self.registry.get_agent_by_id(
            worker_agent_id
        )

        if worker_record is None:
            raise WorkerExecutionError(
                f"Registry에 직원이 없습니다: {worker_agent_id}"
            )

        if worker_record.get("status") != "active":
            raise WorkerExecutionError(
                f"비활성 직원은 실행할 수 없습니다: {worker_agent_id}"
            )

        manager_agent_id = str(
            workflow.get("manager_agent_id", "")
        )
        worker_role = str(
            worker_record.get("role", "AI 직원")
        )
        worker_name = self._safe_agent_name(
            str(worker_record.get("name", "AI_Worker"))
        )
        worker_instructions = str(
            worker_record.get("instructions", "")
        )
        assignment = self._resolve_assignment(
            workflow=workflow,
            step=step or {},
            worker_agent_id=worker_agent_id,
        )
        context = self.company_memory.build_context_text(
            query=str(workflow.get("objective", "")),
            project_id=workflow.get("project_id"),
            limit=20,
        )

        execution_agent = Agent(
            name=worker_name,
            instructions=f"""
너는 Business AI OS의 {worker_role}이다.

너의 기존 업무 지침:
{worker_instructions}

현재 배정받은 업무를 실제로 수행하라.

반드시 지켜야 할 실행 원칙:

1. 계획만 작성하지 말고 가능한 범위에서 실제 결과물을 완성한다.
2. 홈페이지·프로그램 업무라면 실행 가능한 전체 파일 내용을 생성한다.
3. 조사·기획·문서 업무라면 실제 보고서 파일 내용을 생성한다.
4. 생성 파일은 relative_path와 전체 content로 반환한다.
5. 파일 경로는 상대 경로만 사용하고 상위 경로(..)나 절대 경로를 사용하지 않는다.
6. 외부 서비스 연결 없이 수행할 수 있는 일은 즉시 완료한다.
7. Google Drive, Zapier, GitHub, 배포 계정 등 외부 권한이 실제로 필요하면
   완료했다고 주장하지 말고 permission_requests에 정확히 기록한다.
8. 권한 요청에는 서비스명, 이유, 필요한 범위, 승인 후 재개할 작업을 포함한다.
9. 실제로 하지 않은 일을 했다고 보고하지 않는다.
10. 결과는 지점장에게 보고하며 대표에게 직접 보고하지 않는다.
11. status는 결과물이 완성되면 completed,
    사람 권한 없이는 다음 단계가 불가능하면 waiting_permission으로 작성한다.
12. 코드 결과물은 가능한 한 즉시 로컬에서 열거나 실행할 수 있는 형태로 만든다.
13. 기존 회사 자료와 Context가 있으면 우선 활용한다.
""".strip(),
            output_type=WorkerExecutionResult,
        )

        prompt = f"""
[AI 직원 실제 업무 실행]

Workflow ID:
{workflow_id}

프로젝트:
{workflow.get('title')}

목표:
{workflow.get('objective')}

대표 지시:
{workflow.get('owner_instruction')}

담당 지점장:
{manager_agent_id}

담당 직원:
{worker_role}

직원 배정 업무:
{assignment}

회사 Context:
{context}

위 업무를 실제로 수행하고 저장할 결과물 전체를 구조화해 반환하라.
""".strip()

        try:
            run_result = Runner.run_sync(
                starting_agent=execution_agent,
                input=prompt,
            )
        except Exception as exc:
            raise WorkerExecutionError(
                f"AI 직원 실제 업무 실행에 실패했습니다: {exc}"
            ) from exc

        final_output = run_result.final_output

        if isinstance(final_output, WorkerExecutionResult):
            result = final_output
        else:
            try:
                result = WorkerExecutionResult.model_validate(
                    final_output
                )
            except Exception as exc:
                raise WorkerExecutionError(
                    "AI 직원 실행 결과 형식이 올바르지 않습니다."
                ) from exc

        normalized_status = result.status.strip().lower()

        if normalized_status not in {
            "completed",
            "waiting_permission",
        }:
            raise WorkerExecutionError(
                f"지원하지 않는 직원 실행 상태입니다: {result.status}"
            )

        output_dir = self._workflow_output_dir(
            workflow_id=workflow_id,
            title=str(workflow.get("title", "")),
        )

        saved_files = self._write_generated_files(
            output_dir=output_dir,
            files=result.files,
        )

        execution_record = {
            "workflow_id": workflow_id,
            "worker_agent_id": worker_agent_id,
            "worker_role": worker_role,
            "manager_agent_id": manager_agent_id,
            "status": normalized_status,
            "work_summary": result.work_summary,
            "result_summary": result.result_summary,
            "saved_files": saved_files,
            "permission_requests": [
                request.model_dump()
                for request in result.permission_requests
            ],
            "next_action": result.next_action,
            "limitations": result.limitations,
        }

        self._write_json(
            output_dir / (
                f"execution_{self._safe_filename(worker_agent_id)}.json"
            ),
            execution_record,
        )

        if result.permission_requests:
            self._write_json(
                output_dir / "permission_requests.json",
                {
                    "workflow_id": workflow_id,
                    "requests": [
                        request.model_dump()
                        for request in result.permission_requests
                    ],
                },
            )

        self.company_memory.remember_agent_result(
            title=f"직원 실행 결과: {worker_role}",
            content=(
                f"상태: {normalized_status}\n"
                f"업무 요약: {result.work_summary}\n"
                f"결과 요약: {result.result_summary}\n"
                f"저장 파일: {', '.join(saved_files) or '없음'}\n"
                f"권한 요청 수: {len(result.permission_requests)}"
            ),
            source_agent_id=worker_agent_id,
            project_id=workflow.get("project_id"),
            related_agent_ids=[
                agent_id
                for agent_id in [manager_agent_id]
                if agent_id
            ],
            importance=5,
            approved=False,
            tags=[
                "worker",
                "execution",
                workflow_id,
                normalized_status,
            ],
        )

        return execution_record

    # =====================================================
    # 업무 배정 내용 확인
    # =====================================================

    def _resolve_assignment(
        self,
        *,
        workflow: dict[str, Any],
        step: dict[str, Any],
        worker_agent_id: str,
    ) -> str:
        input_data = step.get("input_data") or {}

        if isinstance(input_data, dict):
            for key in (
                "assignment",
                "instruction",
                "task",
                "description",
            ):
                value = input_data.get(key)

                if value:
                    return str(value)

        metadata = workflow.get("metadata") or {}

        if isinstance(metadata, dict):
            assignments = metadata.get(
                "worker_assignments",
                {}
            )

            if isinstance(assignments, dict):
                value = assignments.get(worker_agent_id)

                if value:
                    return str(value)

        return (
            f"프로젝트 목표 '{workflow.get('objective')}'를 "
            f"직원 역할에 맞게 실제로 수행한다."
        )

    # =====================================================
    # 결과물 저장
    # =====================================================

    def _workflow_output_dir(
        self,
        *,
        workflow_id: str,
        title: str,
    ) -> Path:
        safe_title = self._safe_filename(title)[:50]
        folder_name = (
            f"{self._safe_filename(workflow_id)}"
            f"_{safe_title or 'project'}"
        )
        output_dir = self.generated_dir / folder_name
        output_dir.mkdir(
            parents=True,
            exist_ok=True,
        )
        return output_dir

    def _write_generated_files(
        self,
        *,
        output_dir: Path,
        files: list[GeneratedFile],
    ) -> list[str]:
        saved_files: list[str] = []

        for generated_file in files:
            relative_path = self._safe_relative_path(
                generated_file.relative_path
            )
            destination = (
                output_dir / relative_path
            ).resolve()

            output_root = output_dir.resolve()

            if (
                destination != output_root
                and output_root not in destination.parents
            ):
                raise ArtifactWriteError(
                    f"허용되지 않는 파일 경로입니다: {relative_path}"
                )

            destination.parent.mkdir(
                parents=True,
                exist_ok=True,
            )

            try:
                destination.write_text(
                    generated_file.content,
                    encoding="utf-8",
                )
            except OSError as exc:
                raise ArtifactWriteError(
                    f"결과물 저장에 실패했습니다: {destination}"
                ) from exc

            saved_files.append(
                str(destination.relative_to(output_root))
            )

        return saved_files

    @staticmethod
    def _write_json(
        path: Path,
        data: dict[str, Any],
    ) -> None:
        path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        try:
            path.write_text(
                json.dumps(
                    data,
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
        except OSError as exc:
            raise ArtifactWriteError(
                f"JSON 저장에 실패했습니다: {path}"
            ) from exc

    # =====================================================
    # Context 조회
    # =====================================================

    def build_context(
        self,
        workflow_id: str,
    ) -> str:
        from workflow_manager import workflow_manager

        workflow = workflow_manager.require_workflow(
            workflow_id
        )

        return self.company_memory.build_context_text(
            query=str(workflow.get("objective", "")),
            project_id=workflow.get("project_id"),
            limit=30,
        )

    # =====================================================
    # 문자열 및 경로 처리
    # =====================================================

    @staticmethod
    def _safe_relative_path(value: str) -> Path:
        cleaned = str(value).strip().replace("\\", "/")
        cleaned = cleaned.lstrip("/")

        if not cleaned:
            raise ArtifactWriteError(
                "생성 파일 경로가 비어 있습니다."
            )

        parts = [
            part
            for part in cleaned.split("/")
            if part not in {"", "."}
        ]

        if not parts or any(
            part == ".."
            for part in parts
        ):
            raise ArtifactWriteError(
                f"허용되지 않는 상대 경로입니다: {value}"
            )

        return Path(*parts)

    @staticmethod
    def _safe_agent_name(value: str) -> str:
        cleaned = re.sub(
            r"[^A-Za-z0-9_]+",
            "_",
            str(value).strip(),
        ).strip("_")

        if not cleaned:
            return "Business_AI_Worker"

        if cleaned[0].isdigit():
            cleaned = f"Worker_{cleaned}"

        return cleaned

    @staticmethod
    def _safe_filename(value: str) -> str:
        cleaned = re.sub(
            r'[<>:"/\\|?*\x00-\x1F]+',
            "_",
            str(value).strip(),
        )
        cleaned = re.sub(
            r"\s+",
            "_",
            cleaned,
        )
        cleaned = cleaned.strip("._ ")

        return cleaned or "output"


# =========================================================
# 공용 Controller
# =========================================================

worker_controller = WorkerController()


# =========================================================
# 단독 실행
# =========================================================

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("=" * 60)
        print("Worker Controller 공통 실행 엔진")
        print("사용법:")
        print(
            "py worker_controller.py "
            "<workflow_id> <worker_agent_id>"
        )
        print("=" * 60)
        raise SystemExit(0)

    workflow_id_arg = sys.argv[1]
    worker_agent_id_arg = sys.argv[2]

    execution_result = worker_controller.execute(
        workflow_id=workflow_id_arg,
        worker_agent_id=worker_agent_id_arg,
    )

    print("=" * 60)
    print("AI 직원 실제 업무 실행 완료")
    print("Workflow:", execution_result["workflow_id"])
    print("직원:", execution_result["worker_role"])
    print("상태:", execution_result["status"])
    print("저장 파일:", execution_result["saved_files"])
    print(
        "권한 요청 수:",
        len(execution_result["permission_requests"]),
    )
    print("=" * 60)
