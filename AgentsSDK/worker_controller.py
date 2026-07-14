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
from execution_tool_core import ExecutionToolCore, execution_tool_core
from tool_creation_manager import ToolCreationManager, tool_creation_manager
from tool_selection_engine import ToolSelectionEngine, tool_selection_engine


BASE_DIR = Path(__file__).resolve().parent
GENERATED_DIR = BASE_DIR / "generated_projects"


class WorkerControllerError(Exception):
    pass


class WorkerExecutionError(WorkerControllerError):
    pass


class ArtifactWriteError(WorkerControllerError):
    pass


class GeneratedFile(BaseModel):
    relative_path: str
    content: str
    purpose: str = ""


class PermissionRequest(BaseModel):
    service: str
    reason: str
    requested_scope: str = ""
    resume_action: str


class WorkerExecutionResult(BaseModel):
    status: str
    work_summary: str
    result_summary: str
    files: list[GeneratedFile] = Field(default_factory=list)
    permission_requests: list[PermissionRequest] = Field(default_factory=list)
    next_action: str = ""
    limitations: list[str] = Field(default_factory=list)


class WorkerController:
    """
    Business AI OS Worker Controller V2.8

    실행 원칙:
    1. 직원 업무 설명을 Tool Selection Engine에 전달한다.
    2. Tool Registry에서 가장 적합한 기존 Tool을 자동 선택한다.
    3. 선택된 Tool은 Execution Tool Core로 실행한다.
    4. 명시적으로 Tool이 필요한데 적합한 Tool이 없으면 생성 요청을 만든다.
    5. 일반 분석·문서 업무에서 적합한 Tool이 없으면 기존 Agent 방식으로 수행한다.
    6. WorkerController는 개별 Tool 이름에 의존하지 않는다.
    """

    def __init__(
        self,
        *,
        agent_registry: AgentRegistry | None = None,
        company_memory_instance: CompanyMemory | None = None,
        execution_core: ExecutionToolCore | None = None,
        creation_manager: ToolCreationManager | None = None,
        selection_engine: ToolSelectionEngine | None = None,
        generated_dir: Path = GENERATED_DIR,
    ) -> None:
        self.registry = agent_registry or registry
        self.company_memory = company_memory_instance or company_memory
        self.execution_core = execution_core or execution_tool_core
        self.creation_manager = creation_manager or tool_creation_manager
        self.selection_engine = selection_engine or tool_selection_engine
        self.generated_dir = Path(generated_dir)
        self.generated_dir.mkdir(parents=True, exist_ok=True)

    def execute_step(
        self,
        *,
        workflow: dict[str, Any],
        step: dict[str, Any],
    ) -> dict[str, Any]:
        workflow_id = str(workflow.get("workflow_id", "")).strip()
        worker_agent_id = str(step.get("assigned_agent_id", "")).strip()

        if not workflow_id:
            raise WorkerExecutionError("Workflow ID가 없습니다.")

        if not worker_agent_id:
            raise WorkerExecutionError("실행 단계에 배정된 직원이 없습니다.")

        return self.execute(
            workflow_id=workflow_id,
            worker_agent_id=worker_agent_id,
            workflow=workflow,
            step=step,
        )

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

            workflow = workflow_manager.require_workflow(workflow_id)

        worker_record = self.registry.get_agent_by_id(worker_agent_id)

        if worker_record is None:
            raise WorkerExecutionError(
                f"Registry에 직원이 없습니다: {worker_agent_id}"
            )

        if worker_record.get("status") != "active":
            raise WorkerExecutionError(
                f"비활성 직원은 실행할 수 없습니다: {worker_agent_id}"
            )

        tool_plan = self._select_tool_plan(
            workflow=workflow,
            step=step or {},
        )

        if tool_plan.get("selected_tool"):
            return self._execute_selected_tool(
                workflow=workflow,
                step=step or {},
                worker_record=worker_record,
                tool_plan=tool_plan,
            )

        if tool_plan.get("creation_required"):
            return self._create_tool_request(
                workflow=workflow,
                step=step or {},
                worker_record=worker_record,
                tool_plan=tool_plan,
            )

        return self._execute_with_agent(
            workflow=workflow,
            step=step or {},
            worker_record=worker_record,
        )

    def _select_tool_plan(
        self,
        *,
        workflow: dict[str, Any],
        step: dict[str, Any],
    ) -> dict[str, Any]:
        input_data = step.get("input_data") or {}
        metadata = workflow.get("metadata") or {}

        task = self._build_task_text(
            workflow=workflow,
            step=step,
        )

        explicit_requirement: dict[str, Any] = {}

        if isinstance(metadata, dict):
            value = metadata.get("tool_requirement")
            if isinstance(value, dict):
                explicit_requirement.update(value)

        if isinstance(input_data, dict):
            value = input_data.get("tool_requirement")
            if isinstance(value, dict):
                explicit_requirement.update(value)

            field_map = {
                "tool_id": "tool_id",
                "tool_name": "tool_name",
                "tool_category": "category",
                "tool_query": "query",
                "tool_description": "description",
                "tool_capability": "capability",
                "tool_creation_reason": "creation_reason",
                "tool_input_schema": "input_schema",
                "tool_output_schema": "output_schema",
                "tool_input": "input_data",
                "tool_required": "tool_required",
            }

            for source_key, target_key in field_map.items():
                if source_key in input_data:
                    explicit_requirement[target_key] = input_data[source_key]

        development_mode = bool(
            metadata.get("development_mode")
            if isinstance(metadata, dict)
            else False
        )

        preferred_tool_id = str(
            explicit_requirement.get("tool_id") or ""
        ).strip() or None

        category = str(
            explicit_requirement.get("category") or ""
        ).strip() or None

        required_capabilities = explicit_requirement.get(
            "required_capabilities"
        )

        if not isinstance(required_capabilities, list):
            required_capabilities = []

        selection = self.selection_engine.select_or_prepare_creation(
            task=(
                str(explicit_requirement.get("query") or "").strip()
                or task
            ),
            category=category,
            preferred_tool_id=preferred_tool_id,
            required_capabilities=[
                str(value)
                for value in required_capabilities
            ],
        )

        selected_tool = selection.get("selected_tool")

        if selected_tool:
            return {
                "selected_tool": selected_tool,
                "selection": selection,
                "input_data": dict(
                    explicit_requirement.get("input_data") or {
                        "workflow_id": workflow.get("workflow_id"),
                        "instruction": task,
                        "workflow": workflow,
                        "worker_agent_id": step.get("assigned_agent_id"),
                    }
                ),
                "creation_required": False,
            }

        explicit_tool_required = bool(
            explicit_requirement.get("tool_required")
            or preferred_tool_id
            or explicit_requirement.get("tool_name")
            or explicit_requirement.get("capability")
            or development_mode
        )

        if explicit_tool_required:
            creation_request = dict(
                selection.get("creation_request") or {}
            )

            creation_request.update(
                {
                    "requested_name": str(
                        explicit_requirement.get("tool_name")
                        or creation_request.get("requested_name")
                        or "New Execution Tool"
                    ),
                    "requested_category": str(
                        explicit_requirement.get("category")
                        or creation_request.get("requested_category")
                        or "general"
                    ),
                    "requested_description": str(
                        explicit_requirement.get("description")
                        or creation_request.get("requested_description")
                        or "직원 업무 수행에 필요한 실행 Tool"
                    ),
                    "requested_capability": str(
                        explicit_requirement.get("capability")
                        or creation_request.get("requested_capability")
                        or task
                    ),
                    "creation_reason": str(
                        explicit_requirement.get("creation_reason")
                        or creation_request.get("creation_reason")
                        or (
                            "Tool Registry 검색 결과 업무 적합도가 기준을 "
                            "충족하는 기존 Tool이 없어 신규 Tool이 필요함"
                        )
                    ),
                    "requested_input_schema": dict(
                        explicit_requirement.get("input_schema") or {}
                    ),
                    "requested_output_schema": dict(
                        explicit_requirement.get("output_schema") or {}
                    ),
                    "reuse_search_query": str(
                        explicit_requirement.get("query")
                        or task
                    ),
                    "input_data": dict(
                        explicit_requirement.get("input_data") or {}
                    ),
                }
            )

            return {
                "selected_tool": None,
                "selection": selection,
                "creation_required": True,
                "creation_request": creation_request,
            }

        return {
            "selected_tool": None,
            "selection": selection,
            "creation_required": False,
        }

    def _execute_selected_tool(
        self,
        *,
        workflow: dict[str, Any],
        step: dict[str, Any],
        worker_record: dict[str, Any],
        tool_plan: dict[str, Any],
    ) -> dict[str, Any]:
        workflow_id = str(workflow.get("workflow_id", ""))
        worker_agent_id = str(worker_record.get("agent_id", ""))
        worker_role = str(worker_record.get("role", "AI 직원"))
        manager_agent_id = str(workflow.get("manager_agent_id", ""))
        tool = dict(tool_plan["selected_tool"])

        execution_result = self.execution_core.execute_registered_tool(
            workflow_id=workflow_id,
            worker_agent_id=worker_agent_id,
            tool=tool,
            input_data=dict(tool_plan.get("input_data") or {}),
        )

        result_value = execution_result.get("result") or {}
        saved_files: list[str] = []

        if isinstance(result_value, dict):
            for key in ("report_file", "json_file", "output_file"):
                value = result_value.get(key)
                if value:
                    saved_files.append(str(value))

        selection = tool_plan.get("selection") or {}

        execution_record = {
            "workflow_id": workflow_id,
            "worker_agent_id": worker_agent_id,
            "worker_role": worker_role,
            "manager_agent_id": manager_agent_id,
            "status": "completed",
            "execution_mode": "tool_selection_engine",
            "tool_id": tool.get("tool_id"),
            "tool_name": tool.get("name"),
            "tool_version": tool.get("version"),
            "selection_score": tool.get("selection_score"),
            "selection_reason": selection.get("reason"),
            "work_summary": (
                f"Tool Selection Engine이 기존 Tool "
                f"'{tool.get('name')}'을 선택하여 실행했습니다."
            ),
            "result_summary": result_value,
            "saved_files": saved_files,
            "permission_requests": [],
            "tool_execution": execution_result,
            "next_action": "지점장 결과 검토",
            "limitations": [],
        }

        self._save_execution_record(
            workflow=workflow,
            worker_agent_id=worker_agent_id,
            execution_record=execution_record,
        )

        self._remember_execution(
            workflow=workflow,
            worker_agent_id=worker_agent_id,
            manager_agent_id=manager_agent_id,
            worker_role=worker_role,
            execution_record=execution_record,
        )

        return execution_record

    def _create_tool_request(
        self,
        *,
        workflow: dict[str, Any],
        step: dict[str, Any],
        worker_record: dict[str, Any],
        tool_plan: dict[str, Any],
    ) -> dict[str, Any]:
        workflow_id = str(workflow.get("workflow_id", ""))
        worker_agent_id = str(worker_record.get("agent_id", ""))
        worker_role = str(worker_record.get("role", "AI 직원"))
        manager_agent_id = str(workflow.get("manager_agent_id", ""))
        request_data = dict(tool_plan.get("creation_request") or {})

        request_result = self.creation_manager.search_or_request(
            workflow_id=workflow_id,
            worker_agent_id=worker_agent_id,
            requested_name=str(request_data["requested_name"]),
            requested_category=str(request_data["requested_category"]),
            requested_description=str(request_data["requested_description"]),
            requested_capability=str(request_data["requested_capability"]),
            creation_reason=str(request_data["creation_reason"]),
            requested_input_schema=dict(
                request_data.get("requested_input_schema") or {}
            ),
            requested_output_schema=dict(
                request_data.get("requested_output_schema") or {}
            ),
            reuse_search_query=str(
                request_data.get("reuse_search_query") or ""
            ),
            metadata={
                "workflow_title": workflow.get("title"),
                "workflow_objective": workflow.get("objective"),
                "step_id": step.get("step_id"),
                "resume_input_data": dict(
                    request_data.get("input_data") or {}
                ),
                "selection_result": tool_plan.get("selection"),
            },
        )

        request = request_result.get("request") or {}
        request_id = str(request.get("request_id", ""))

        permission_request = {
            "service": "Business AI OS Tool Creation",
            "reason": str(request.get("creation_reason") or ""),
            "requested_scope": (
                f"Tool 생성 승인: {request.get('requested_name', '')}"
            ),
            "resume_action": (
                "대표 승인 후 Tool 자동 생성 → 자동 테스트 → "
                "Tool Registry 등록 → 직원 업무 자동 재개"
            ),
        }

        execution_record = {
            "workflow_id": workflow_id,
            "worker_agent_id": worker_agent_id,
            "worker_role": worker_role,
            "manager_agent_id": manager_agent_id,
            "status": "waiting_permission",
            "execution_mode": "tool_creation_request",
            "work_summary": (
                "Tool Selection Engine 검색 결과 적합한 기존 Tool이 없어 "
                "신규 Tool 생성 승인 요청을 만들었습니다."
            ),
            "result_summary": (
                f"대표 승인 대기 중: {request.get('requested_name', '')}"
            ),
            "saved_files": [],
            "permission_requests": [permission_request],
            "tool_creation_request": request,
            "tool_creation_request_id": request_id,
            "next_action": (
                "대표 승인 후 Tool 자동 생성·테스트·등록 및 업무 재개"
            ),
            "limitations": [
                "대표 승인 전에는 신규 Tool을 생성하거나 실행할 수 없습니다."
            ],
        }

        self._save_execution_record(
            workflow=workflow,
            worker_agent_id=worker_agent_id,
            execution_record=execution_record,
        )

        self._remember_execution(
            workflow=workflow,
            worker_agent_id=worker_agent_id,
            manager_agent_id=manager_agent_id,
            worker_role=worker_role,
            execution_record=execution_record,
        )

        return execution_record

    def resume_tool_request(
        self,
        request_id: str,
        *,
        input_data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        request = self.creation_manager.require_request(request_id)

        if request.get("approval_status") != "approved":
            raise WorkerExecutionError(
                "대표 승인 완료 전에는 Tool 생성 업무를 재개할 수 없습니다."
            )

        creation_result = self.creation_manager.execute_approved_request(
            request_id
        )

        resume_input = dict(input_data or {})

        if not resume_input:
            metadata = request.get("metadata") or {}
            resume_input = dict(
                metadata.get("resume_input_data") or {}
            )

        execution_result = self.creation_manager.execute_created_tool(
            request_id,
            input_data=resume_input,
        )

        return {
            "status": "completed",
            "execution_mode": "created_tool",
            "request_id": request_id,
            "tool_creation": creation_result,
            "tool_execution": execution_result,
            "next_action": "지점장 결과 검토",
        }

    def _execute_with_agent(
        self,
        *,
        workflow: dict[str, Any],
        step: dict[str, Any],
        worker_record: dict[str, Any],
    ) -> dict[str, Any]:
        workflow_id = str(workflow.get("workflow_id", ""))
        worker_agent_id = str(worker_record.get("agent_id", ""))
        manager_agent_id = str(workflow.get("manager_agent_id", ""))
        worker_role = str(worker_record.get("role", "AI 직원"))
        worker_name = self._safe_agent_name(
            str(worker_record.get("name", "AI_Worker"))
        )
        worker_instructions = str(worker_record.get("instructions", ""))
        assignment = self._resolve_assignment(
            workflow=workflow,
            step=step,
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

기존 업무 지침:
{worker_instructions}

실행 원칙:
1. 가능한 범위에서 실제 결과물을 완성한다.
2. 문서·보고서 업무는 실제 파일 전체 내용을 생성한다.
3. 생성 파일은 상대 경로와 전체 content로 반환한다.
4. 외부 서비스 권한이 정말 필요한 경우에만 permission_requests를 작성한다.
5. Business AI OS 내부 Tool은 외부 권한으로 요청하지 않는다.
6. 실제로 하지 않은 일을 했다고 주장하지 않는다.
7. 결과는 지점장에게 보고한다.
""".strip(),
            output_type=WorkerExecutionResult,
        )

        prompt = f"""
[AI 직원 실제 업무 실행]

Workflow ID: {workflow_id}
프로젝트: {workflow.get('title')}
목표: {workflow.get('objective')}
대표 지시: {workflow.get('owner_instruction')}
담당 지점장: {manager_agent_id}
담당 직원: {worker_role}
직원 배정 업무: {assignment}

회사 Context:
{context}

업무를 실제로 수행하고 결과물을 구조화해 반환하라.
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
            result = WorkerExecutionResult.model_validate(final_output)

        normalized_status = result.status.strip().lower()

        if normalized_status not in {"completed", "waiting_permission"}:
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
            "execution_mode": "agent",
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

        self._save_execution_record(
            workflow=workflow,
            worker_agent_id=worker_agent_id,
            execution_record=execution_record,
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

        self._remember_execution(
            workflow=workflow,
            worker_agent_id=worker_agent_id,
            manager_agent_id=manager_agent_id,
            worker_role=worker_role,
            execution_record=execution_record,
        )

        return execution_record

    def _build_task_text(
        self,
        *,
        workflow: dict[str, Any],
        step: dict[str, Any],
    ) -> str:
        input_data = step.get("input_data") or {}

        values = [
            workflow.get("title"),
            workflow.get("objective"),
            workflow.get("owner_instruction"),
        ]

        if isinstance(input_data, dict):
            values.extend(
                input_data.get(key)
                for key in (
                    "assignment",
                    "instruction",
                    "task",
                    "description",
                )
            )

        return " ".join(
            str(value or "").strip()
            for value in values
            if str(value or "").strip()
        )

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
            assignments = metadata.get("worker_assignments", {})
            if isinstance(assignments, dict):
                value = assignments.get(worker_agent_id)
                if value:
                    return str(value)

        return (
            f"프로젝트 목표 '{workflow.get('objective')}'를 "
            f"직원 역할에 맞게 실제로 수행한다."
        )

    def _save_execution_record(
        self,
        *,
        workflow: dict[str, Any],
        worker_agent_id: str,
        execution_record: dict[str, Any],
    ) -> None:
        output_dir = self._workflow_output_dir(
            workflow_id=str(workflow.get("workflow_id", "")),
            title=str(workflow.get("title", "")),
        )

        self._write_json(
            output_dir / (
                f"execution_{self._safe_filename(worker_agent_id)}.json"
            ),
            execution_record,
        )

    def _remember_execution(
        self,
        *,
        workflow: dict[str, Any],
        worker_agent_id: str,
        manager_agent_id: str,
        worker_role: str,
        execution_record: dict[str, Any],
    ) -> None:
        result_summary = execution_record.get("result_summary")

        if not isinstance(result_summary, str):
            result_summary = json.dumps(
                result_summary,
                ensure_ascii=False,
                default=str,
            )

        self.company_memory.remember_agent_result(
            title=f"직원 실행 결과: {worker_role}",
            content=(
                f"상태: {execution_record.get('status')}\n"
                f"실행 방식: {execution_record.get('execution_mode')}\n"
                f"업무 요약: {execution_record.get('work_summary')}\n"
                f"결과 요약: {result_summary}\n"
                f"저장 파일: "
                f"{', '.join(execution_record.get('saved_files') or []) or '없음'}\n"
                f"권한 요청 수: "
                f"{len(execution_record.get('permission_requests') or [])}"
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
                str(workflow.get("workflow_id", "")),
                str(execution_record.get("execution_mode", "")),
            ],
        )

    def _workflow_output_dir(
        self,
        *,
        workflow_id: str,
        title: str,
    ) -> Path:
        safe_title = self._safe_filename(title)[:50]
        folder_name = (
            f"{self._safe_filename(workflow_id)}_"
            f"{safe_title or 'project'}"
        )
        output_dir = self.generated_dir / folder_name
        output_dir.mkdir(parents=True, exist_ok=True)
        return output_dir

    def _write_generated_files(
        self,
        *,
        output_dir: Path,
        files: list[GeneratedFile],
    ) -> list[str]:
        saved_files: list[str] = []
        output_root = output_dir.resolve()

        for generated_file in files:
            relative_path = self._safe_relative_path(
                generated_file.relative_path
            )
            destination = (output_dir / relative_path).resolve()

            if (
                destination != output_root
                and output_root not in destination.parents
            ):
                raise ArtifactWriteError(
                    f"허용되지 않는 파일 경로입니다: {relative_path}"
                )

            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(
                generated_file.content,
                encoding="utf-8",
            )
            saved_files.append(
                str(destination.relative_to(output_root))
            )

        return saved_files

    @staticmethod
    def _write_json(
        path: Path,
        data: dict[str, Any],
    ) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                data,
                ensure_ascii=False,
                indent=2,
                default=str,
            ),
            encoding="utf-8",
        )

    def build_context(
        self,
        workflow_id: str,
    ) -> str:
        from workflow_manager import workflow_manager

        workflow = workflow_manager.require_workflow(workflow_id)

        return self.company_memory.build_context_text(
            query=str(workflow.get("objective", "")),
            project_id=workflow.get("project_id"),
            limit=30,
        )

    @staticmethod
    def _safe_relative_path(value: str) -> Path:
        cleaned = str(value).strip().replace("\\", "/").lstrip("/")

        if not cleaned:
            raise ArtifactWriteError("생성 파일 경로가 비어 있습니다.")

        parts = [
            part
            for part in cleaned.split("/")
            if part not in {"", "."}
        ]

        if not parts or any(part == ".." for part in parts):
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
        cleaned = re.sub(r"\s+", "_", cleaned)
        cleaned = cleaned.strip("._ ")
        return cleaned or "output"


worker_controller = WorkerController()


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Worker Controller V2.8")
        raise SystemExit(1)
