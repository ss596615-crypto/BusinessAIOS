from __future__ import annotations

import json
import subprocess
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from agent_factory import AgentFactory, factory
from agent_registry import AgentRegistry, registry
from company_memory import CompanyMemory, company_memory
from handoff_manager import HandoffManager, handoff_manager


# =========================================================
# 저장 위치
# =========================================================

BASE_DIR = Path(__file__).resolve().parent
ASSETS_DIR = BASE_DIR / "company_assets"
WORKFLOW_FILE = ASSETS_DIR / "workflows.json"


# =========================================================
# 예외
# =========================================================

class WorkflowManagerError(Exception):
    """Workflow Manager 처리 중 발생하는 기본 예외."""


class WorkflowValidationError(WorkflowManagerError):
    """Workflow 요청값이 올바르지 않을 때 발생한다."""


class WorkflowNotFoundError(WorkflowManagerError):
    """요청한 Workflow를 찾지 못했을 때 발생한다."""


class WorkflowStateError(WorkflowManagerError):
    """허용되지 않는 Workflow 상태 전환 시 발생한다."""


class WorkflowExecutionError(WorkflowManagerError):
    """Workflow 단계 실행 중 발생한다."""


# =========================================================
# Workflow 자산 구조
# =========================================================

@dataclass
class WorkflowStep:
    step_id: str
    name: str
    step_type: str
    assigned_agent_id: str | None
    status: str = "pending"
    input_data: dict[str, Any] = field(default_factory=dict)
    output_data: dict[str, Any] = field(default_factory=dict)
    error_message: str = ""
    retry_count: int = 0
    max_retries: int = 2
    started_at: str = ""
    completed_at: str = ""
    updated_at: str = ""


@dataclass
class WorkflowRecord:
    workflow_id: str
    title: str
    objective: str
    owner_instruction: str
    project_id: str | None
    requested_by: str
    ceo_agent_id: str
    manager_agent_id: str | None
    worker_agent_ids: list[str]
    status: str
    current_step_index: int
    requires_approval: bool
    approval_status: str
    approval_requested_at: str
    approved_at: str
    rejected_at: str
    rejection_reason: str
    result_summary: str
    next_action: str
    failure_reason: str
    steps: list[dict[str, Any]]
    metadata: dict[str, Any]
    created_at: str
    updated_at: str
    completed_at: str


# =========================================================
# Workflow Manager
# =========================================================

class WorkflowManager:
    """
    Business AI OS의 업무 실행 흐름을 관리한다.

    기본 흐름:
    대표 지시
    → AI CEO 분석
    → 지점장 배정
    → 직원 배정
    → 실무 실행
    → 결과 검토
    → 대표 승인 요청
    → 승인 또는 반려
    → 다음 업무
    → Company Memory 업데이트

    핵심 기능:
    1. Workflow 생성
    2. 단계별 상태 관리
    3. Agent 배정
    4. Handoff 구조 검증
    5. 단계 실행 및 결과 저장
    6. 승인 요청, 승인, 반려
    7. 실패 기록 및 재시도
    8. 중단 Workflow 재개
    9. Company Memory 자동 업데이트
    10. Workflow 영구 저장
    """

    ALLOWED_WORKFLOW_STATUSES = {
        "draft",
        "ready",
        "running",
        "waiting_approval",
        "approved",
        "rejected",
        "paused",
        "blocked",
        "failed",
        "completed",
        "cancelled",
    }

    ALLOWED_STEP_STATUSES = {
        "pending",
        "running",
        "waiting",
        "completed",
        "failed",
        "skipped",
        "cancelled",
    }

    ALLOWED_APPROVAL_STATUSES = {
        "not_required",
        "pending",
        "approved",
        "rejected",
    }

    ALLOWED_STEP_TYPES = {
        "owner_intake",
        "ceo_analysis",
        "manager_assignment",
        "worker_assignment",
        "execution",
        "development_execution",
        "manager_review",
        "ceo_review",
        "approval_request",
        "memory_update",
        "next_action",
        "custom",
    }

    TERMINAL_WORKFLOW_STATUSES = {
        "completed",
        "cancelled",
    }

    def __init__(
        self,
        *,
        workflow_file: Path = WORKFLOW_FILE,
        agent_factory: AgentFactory | None = None,
        agent_registry: AgentRegistry | None = None,
        handoff_manager_instance: HandoffManager | None = None,
        company_memory_instance: CompanyMemory | None = None,
    ) -> None:
        self.workflow_file = workflow_file
        self.factory = agent_factory or factory
        self.registry = agent_registry or registry
        self.handoff_manager = (
            handoff_manager_instance or handoff_manager
        )
        self.company_memory = (
            company_memory_instance or company_memory
        )
        self._step_handlers: dict[
            str,
            Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]],
        ] = {}
        self._ensure_workflow_file()
        self._register_default_handlers()

    # =====================================================
    # 파일 관리
    # =====================================================

    def _ensure_workflow_file(self) -> None:
        self.workflow_file.parent.mkdir(parents=True, exist_ok=True)

        if not self.workflow_file.exists():
            self._write_data(
                {
                    "version": "2.0",
                    "workflows": [],
                }
            )

    def _read_data(self) -> dict[str, Any]:
        try:
            with self.workflow_file.open("r", encoding="utf-8") as file:
                data = json.load(file)

            if not isinstance(data, dict):
                return {
                    "version": "2.0",
                    "workflows": [],
                }

            if not isinstance(data.get("workflows"), list):
                data["workflows"] = []

            if not isinstance(data.get("version"), str):
                data["version"] = "2.0"

            return data

        except (json.JSONDecodeError, OSError):
            return {
                "version": "2.0",
                "workflows": [],
            }

    def _write_data(self, data: dict[str, Any]) -> None:
        try:
            with self.workflow_file.open("w", encoding="utf-8") as file:
                json.dump(
                    data,
                    file,
                    ensure_ascii=False,
                    indent=2,
                )
        except OSError as exc:
            raise WorkflowManagerError(
                f"Workflow 저장에 실패했습니다: {self.workflow_file}"
            ) from exc

    # =====================================================
    # Workflow 생성
    # =====================================================

    def create_workflow(
        self,
        *,
        title: str,
        objective: str,
        owner_instruction: str,
        ceo_agent_id: str = "ceo_001",
        manager_agent_id: str | None = None,
        worker_agent_ids: list[str] | None = None,
        project_id: str | None = None,
        requested_by: str = "owner",
        requires_approval: bool = True,
        steps: list[dict[str, Any]] | None = None,
        metadata: dict[str, Any] | None = None,
        remember_instruction: bool = True,
    ) -> dict[str, Any]:
        """
        새로운 Workflow를 생성한다.
        """

        cleaned_title = self._clean_text(title)
        cleaned_objective = self._clean_multiline(objective)
        cleaned_instruction = self._clean_multiline(owner_instruction)
        cleaned_requested_by = self._clean_text(requested_by)
        cleaned_project_id = self._clean_optional_text(project_id)
        cleaned_manager_id = self._clean_optional_text(manager_agent_id)
        cleaned_worker_ids = self._clean_string_list(
            worker_agent_ids or []
        )

        self._validate_workflow_input(
            title=cleaned_title,
            objective=cleaned_objective,
            owner_instruction=cleaned_instruction,
            requested_by=cleaned_requested_by,
            ceo_agent_id=ceo_agent_id,
            manager_agent_id=cleaned_manager_id,
            worker_agent_ids=cleaned_worker_ids,
        )

        self._validate_agent_exists(ceo_agent_id)

        if cleaned_manager_id:
            self._validate_agent_exists(cleaned_manager_id)

        for worker_agent_id in cleaned_worker_ids:
            self._validate_agent_exists(worker_agent_id)

        development_mode = self._is_development_instruction(
            cleaned_instruction,
            metadata=metadata,
        )

        workflow_steps = (
            self._prepare_custom_steps(steps)
            if steps is not None
            else (
                self._build_development_steps(
                    ceo_agent_id=ceo_agent_id,
                    requires_approval=requires_approval,
                )
                if development_mode
                else self._build_default_steps(
                    ceo_agent_id=ceo_agent_id,
                    manager_agent_id=cleaned_manager_id,
                    worker_agent_ids=cleaned_worker_ids,
                    requires_approval=requires_approval,
                )
            )
        )

        now = self._utc_now()
        workflow_id = self._generate_workflow_id()

        record = WorkflowRecord(
            workflow_id=workflow_id,
            title=cleaned_title,
            objective=cleaned_objective,
            owner_instruction=cleaned_instruction,
            project_id=cleaned_project_id,
            requested_by=cleaned_requested_by,
            ceo_agent_id=ceo_agent_id,
            manager_agent_id=cleaned_manager_id,
            worker_agent_ids=cleaned_worker_ids,
            status="ready",
            current_step_index=0,
            requires_approval=requires_approval,
            approval_status=(
                "pending"
                if requires_approval
                else "not_required"
            ),
            approval_requested_at="",
            approved_at="",
            rejected_at="",
            rejection_reason="",
            result_summary="",
            next_action="",
            failure_reason="",
            steps=[
                asdict(step)
                for step in workflow_steps
            ],
            metadata={
                **dict(metadata or {}),
                "execution_engine": (
                    "development_engine" if development_mode else "standard_worker"
                ),
                "development_mode": development_mode,
                "evidence_required": bool(
                    dict(metadata or {}).get("evidence_required")
                    or any(token in cleaned_instruction.lower() for token in (
                        "python", "코드", "dashboard", "workflow", "시스템 수정",
                        "오류 수정", "기능을 추가", "기능 추가", "검증", "git", "테스트"
                    ))
                ),
            },
            created_at=now,
            updated_at=now,
            completed_at="",
        )

        data = self._read_data()
        workflow_data = asdict(record)
        data["workflows"].append(workflow_data)
        self._write_data(data)

        if remember_instruction:
            self.company_memory.remember_owner_instruction(
                title=f"Workflow 지시: {cleaned_title}",
                content=cleaned_instruction,
                project_id=cleaned_project_id,
                importance=5,
                tags=[
                    "workflow",
                    workflow_id,
                    cleaned_title,
                ],
            )

        return {
            "created": True,
            "reason": "workflow_created",
            "workflow": workflow_data,
        }

    def _build_default_steps(
        self,
        *,
        ceo_agent_id: str,
        manager_agent_id: str | None,
        worker_agent_ids: list[str],
        requires_approval: bool,
    ) -> list[WorkflowStep]:
        now = self._utc_now()
        steps: list[WorkflowStep] = [
            self._make_step(
                name="대표 지시 접수",
                step_type="owner_intake",
                assigned_agent_id=ceo_agent_id,
                now=now,
            ),
            self._make_step(
                name="AI CEO 목표 분석",
                step_type="ceo_analysis",
                assigned_agent_id=ceo_agent_id,
                now=now,
            ),
        ]

        if manager_agent_id:
            steps.append(
                self._make_step(
                    name="지점장 업무 배정",
                    step_type="manager_assignment",
                    assigned_agent_id=manager_agent_id,
                    now=now,
                )
            )

        if worker_agent_ids:
            steps.append(
                self._make_step(
                    name="AI 직원 업무 배정",
                    step_type="worker_assignment",
                    assigned_agent_id=manager_agent_id,
                    now=now,
                    input_data={
                        "worker_agent_ids": worker_agent_ids,
                    },
                )
            )

            for worker_agent_id in worker_agent_ids:
                steps.append(
                    self._make_step(
                        name=f"{worker_agent_id} 업무 실행",
                        step_type="execution",
                        assigned_agent_id=worker_agent_id,
                        now=now,
                    )
                )

        if manager_agent_id:
            steps.append(
                self._make_step(
                    name="지점장 결과 검토",
                    step_type="manager_review",
                    assigned_agent_id=manager_agent_id,
                    now=now,
                )
            )

        steps.append(
            self._make_step(
                name="AI CEO 최종 검토",
                step_type="ceo_review",
                assigned_agent_id=ceo_agent_id,
                now=now,
            )
        )

        if requires_approval:
            steps.append(
                self._make_step(
                    name="대표 승인 요청",
                    step_type="approval_request",
                    assigned_agent_id=ceo_agent_id,
                    now=now,
                )
            )

        steps.extend(
            [
                self._make_step(
                    name="회사 Memory 업데이트",
                    step_type="memory_update",
                    assigned_agent_id=ceo_agent_id,
                    now=now,
                ),
                self._make_step(
                    name="다음 업무 결정",
                    step_type="next_action",
                    assigned_agent_id=ceo_agent_id,
                    now=now,
                ),
            ]
        )

        return steps

    def _build_development_steps(
        self,
        *,
        ceo_agent_id: str,
        requires_approval: bool,
    ) -> list[WorkflowStep]:
        """개발 지시 전용 실행 흐름. 일반 지점장/Worker 실행을 우회한다."""
        now = self._utc_now()
        steps = [
            self._make_step(
                name="대표 개발 지시 접수",
                step_type="owner_intake",
                assigned_agent_id=ceo_agent_id,
                now=now,
            ),
            self._make_step(
                name="AI CEO 개발 업무 판정",
                step_type="ceo_analysis",
                assigned_agent_id=ceo_agent_id,
                now=now,
            ),
            self._make_step(
                name="Development Engine 실제 실행",
                step_type="development_execution",
                assigned_agent_id="development_engine",
                now=now,
                input_data={"execution_engine": "development_engine"},
            ),
            self._make_step(
                name="AI CEO 개발 결과 검토",
                step_type="ceo_review",
                assigned_agent_id=ceo_agent_id,
                now=now,
            ),
        ]
        if requires_approval:
            steps.append(
                self._make_step(
                    name="대표 Git Push 승인 요청",
                    step_type="approval_request",
                    assigned_agent_id=ceo_agent_id,
                    now=now,
                )
            )
        steps.extend([
            self._make_step(
                name="회사 Memory 업데이트",
                step_type="memory_update",
                assigned_agent_id=ceo_agent_id,
                now=now,
            ),
            self._make_step(
                name="다음 업무 결정",
                step_type="next_action",
                assigned_agent_id=ceo_agent_id,
                now=now,
            ),
        ])
        return steps

    @staticmethod
    def _is_development_instruction(
        instruction: str,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> bool:
        meta = dict(metadata or {})
        if meta.get("development_mode") is True:
            return True
        business_type = str(meta.get("business_type") or "").lower()
        if any(token in business_type for token in (
            "develop", "devops", "code", "admin_system", "admin_dashboard"
        )):
            return True
        text = str(instruction or "").lower()
        keywords = (
            "오류 수정", "버그 수정", "코드 수정", "기능 추가", "기능 수정",
            "새 기능", "python", "git commit", "git push", "development engine",
            "dashboard", "workflow", "실제 파일", "함수", "클래스",
        )
        return any(keyword in text for keyword in keywords)

    def _prepare_custom_steps(
        self,
        steps: list[dict[str, Any]],
    ) -> list[WorkflowStep]:
        if not isinstance(steps, list) or not steps:
            raise WorkflowValidationError(
                "steps에는 한 개 이상의 단계가 필요합니다."
            )

        prepared: list[WorkflowStep] = []
        now = self._utc_now()

        for index, step in enumerate(steps):
            if not isinstance(step, dict):
                raise WorkflowValidationError(
                    f"steps[{index}]는 dict 형식이어야 합니다."
                )

            name = self._clean_text(step.get("name"))
            step_type = self._clean_text(
                step.get("step_type")
            ).lower()
            assigned_agent_id = self._clean_optional_text(
                step.get("assigned_agent_id")
            )

            if not name:
                raise WorkflowValidationError(
                    f"steps[{index}].name이 비어 있습니다."
                )

            if step_type not in self.ALLOWED_STEP_TYPES:
                raise WorkflowValidationError(
                    f"지원하지 않는 step_type입니다: {step_type}"
                )

            if assigned_agent_id:
                self._validate_agent_exists(assigned_agent_id)

            prepared.append(
                WorkflowStep(
                    step_id=str(
                        step.get("step_id")
                        or self._generate_step_id()
                    ),
                    name=name,
                    step_type=step_type,
                    assigned_agent_id=assigned_agent_id,
                    status="pending",
                    input_data=dict(
                        step.get("input_data") or {}
                    ),
                    output_data={},
                    error_message="",
                    retry_count=0,
                    max_retries=int(
                        step.get("max_retries", 2)
                    ),
                    started_at="",
                    completed_at="",
                    updated_at=now,
                )
            )

        return prepared

    # =====================================================
    # 조회
    # =====================================================

    def get_workflow(
        self,
        workflow_id: str,
    ) -> dict[str, Any] | None:
        for workflow in self._read_data()["workflows"]:
            if workflow.get("workflow_id") == workflow_id:
                return workflow

        return None

    def require_workflow(
        self,
        workflow_id: str,
    ) -> dict[str, Any]:
        workflow = self.get_workflow(workflow_id)

        if workflow is None:
            raise WorkflowNotFoundError(
                f"Workflow를 찾을 수 없습니다: {workflow_id}"
            )

        return workflow

    def list_workflows(
        self,
        *,
        status: str | None = None,
        project_id: str | None = None,
        manager_agent_id: str | None = None,
        requested_by: str | None = None,
        limit: int | None = None,
        newest_first: bool = True,
    ) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []

        for workflow in self._read_data()["workflows"]:
            if (
                status is not None
                and workflow.get("status") != status
            ):
                continue

            if (
                project_id is not None
                and workflow.get("project_id") != project_id
            ):
                continue

            if (
                manager_agent_id is not None
                and workflow.get("manager_agent_id")
                != manager_agent_id
            ):
                continue

            if (
                requested_by is not None
                and workflow.get("requested_by")
                != requested_by
            ):
                continue

            results.append(workflow)

        results.sort(
            key=lambda item: str(
                item.get("updated_at", "")
            ),
            reverse=newest_first,
        )

        if limit is not None:
            return results[:max(limit, 0)]

        return results

    def get_current_step(
        self,
        workflow_id: str,
    ) -> dict[str, Any] | None:
        workflow = self.require_workflow(workflow_id)
        steps = workflow.get("steps", [])
        current_index = int(
            workflow.get("current_step_index", 0)
        )

        if current_index < 0 or current_index >= len(steps):
            return None

        return steps[current_index]

    def get_workflow_progress(
        self,
        workflow_id: str,
    ) -> dict[str, Any]:
        workflow = self.require_workflow(workflow_id)
        steps = workflow.get("steps", [])
        total = len(steps)
        completed = sum(
            1
            for step in steps
            if step.get("status") in {
                "completed",
                "skipped",
            }
        )
        failed = sum(
            1
            for step in steps
            if step.get("status") == "failed"
        )
        pending = sum(
            1
            for step in steps
            if step.get("status") in {
                "pending",
                "waiting",
            }
        )

        progress_percent = (
            round((completed / total) * 100, 2)
            if total
            else 0.0
        )

        return {
            "workflow_id": workflow_id,
            "status": workflow.get("status"),
            "total_steps": total,
            "completed_steps": completed,
            "failed_steps": failed,
            "pending_steps": pending,
            "current_step_index": workflow.get(
                "current_step_index"
            ),
            "progress_percent": progress_percent,
            "approval_status": workflow.get(
                "approval_status"
            ),
        }

    # =====================================================
    # 실행
    # =====================================================

    def run_workflow(
        self,
        workflow_id: str,
        *,
        stop_before_approval: bool = False,
        max_steps: int | None = None,
    ) -> dict[str, Any]:
        """
        현재 단계부터 Workflow를 순차 실행한다.

        기본 Handler는 상태 관리와 자산 기록 중심으로 동작한다.
        실제 OpenAI Runner 실행은 이후 controller 계층에서 연결할 수 있다.
        """

        workflow = self.require_workflow(workflow_id)

        if workflow.get("status") in self.TERMINAL_WORKFLOW_STATUSES:
            return {
                "executed": False,
                "reason": "workflow_already_terminal",
                "workflow": workflow,
            }

        if workflow.get("status") == "rejected":
            raise WorkflowStateError(
                "반려된 Workflow는 수정 후 재개해야 합니다."
            )

        if workflow.get("status") == "waiting_approval":
            return {
                "executed": False,
                "reason": "waiting_for_approval",
                "workflow": workflow,
            }

        self._set_workflow_status(
            workflow_id,
            "running",
        )

        executed_steps = 0

        while True:
            workflow = self.require_workflow(workflow_id)
            current_step = self.get_current_step(workflow_id)

            if current_step is None:
                return self._complete_workflow(workflow_id)

            if (
                max_steps is not None
                and executed_steps >= max_steps
            ):
                return {
                    "executed": True,
                    "reason": "max_steps_reached",
                    "workflow": self.require_workflow(
                        workflow_id
                    ),
                }

            if (
                stop_before_approval
                and current_step.get("step_type")
                == "approval_request"
            ):
                self._set_workflow_status(
                    workflow_id,
                    "paused",
                )
                return {
                    "executed": True,
                    "reason": "stopped_before_approval",
                    "workflow": self.require_workflow(
                        workflow_id
                    ),
                }

            step_result = self.execute_current_step(
                workflow_id
            )
            executed_steps += 1

            if step_result.get("waiting_approval"):
                return {
                    "executed": True,
                    "reason": "waiting_for_approval",
                    "workflow": self.require_workflow(
                        workflow_id
                    ),
                }

            if step_result.get("failed"):
                return {
                    "executed": False,
                    "reason": "step_failed",
                    "workflow": self.require_workflow(
                        workflow_id
                    ),
                    "step_result": step_result,
                }

    def execute_current_step(
        self,
        workflow_id: str,
    ) -> dict[str, Any]:
        workflow = self.require_workflow(workflow_id)
        current_step = self.get_current_step(workflow_id)

        if current_step is None:
            return {
                "completed": True,
                "reason": "no_remaining_steps",
            }

        step_type = str(
            current_step.get("step_type", "")
        )

        handler = self._step_handlers.get(step_type)

        if handler is None:
            raise WorkflowExecutionError(
                f"등록된 Step Handler가 없습니다: {step_type}"
            )

        self._start_step(
            workflow_id,
            str(current_step["step_id"]),
        )

        workflow = self.require_workflow(workflow_id)
        current_step = self.get_current_step(workflow_id)

        try:
            output = handler(
                workflow,
                current_step or {},
            )

            if step_type == "approval_request":
                self._complete_step(
                    workflow_id,
                    str(current_step["step_id"]),
                    output,
                )
                self._request_approval(workflow_id)

                return {
                    "completed": True,
                    "waiting_approval": True,
                    "output": output,
                }

            self._complete_step(
                workflow_id,
                str(current_step["step_id"]),
                output,
            )
            self._move_to_next_step(workflow_id)

            return {
                "completed": True,
                "waiting_approval": False,
                "output": output,
            }

        except Exception as exc:
            failure = self._fail_step(
                workflow_id,
                str(current_step["step_id"]),
                str(exc),
            )

            return {
                "completed": False,
                "failed": True,
                "error": str(exc),
                "failure": failure,
            }

    def resume_workflow(
        self,
        workflow_id: str,
        *,
        max_steps: int | None = None,
    ) -> dict[str, Any]:
        workflow = self.require_workflow(workflow_id)
        status = workflow.get("status")

        if status == "waiting_approval":
            raise WorkflowStateError(
                "승인 대기 중인 Workflow는 승인 또는 반려 처리가 필요합니다."
            )

        if status == "rejected":
            raise WorkflowStateError(
                "반려된 Workflow는 revise_rejected_workflow() 후 재개해야 합니다."
            )

        if status == "failed":
            self.retry_current_step(workflow_id)

        self._set_workflow_status(
            workflow_id,
            "running",
        )

        return self.run_workflow(
            workflow_id,
            max_steps=max_steps,
        )

    def retry_current_step(
        self,
        workflow_id: str,
    ) -> dict[str, Any]:
        workflow = self.require_workflow(workflow_id)
        current_step = self.get_current_step(workflow_id)

        if current_step is None:
            raise WorkflowStateError(
                "재시도할 현재 단계가 없습니다."
            )

        if current_step.get("status") != "failed":
            raise WorkflowStateError(
                "실패한 단계만 재시도할 수 있습니다."
            )

        retry_count = int(
            current_step.get("retry_count", 0)
        )
        max_retries = int(
            current_step.get("max_retries", 2)
        )

        if retry_count >= max_retries:
            raise WorkflowStateError(
                "최대 재시도 횟수를 초과했습니다."
            )

        self._update_step(
            workflow_id,
            str(current_step["step_id"]),
            {
                "status": "pending",
                "error_message": "",
                "retry_count": retry_count + 1,
                "started_at": "",
                "completed_at": "",
                "updated_at": self._utc_now(),
            },
        )
        self._set_workflow_fields(
            workflow_id,
            {
                "status": "ready",
                "failure_reason": "",
            },
        )

        return {
            "retry_ready": True,
            "workflow": self.require_workflow(
                workflow_id
            ),
        }

    # =====================================================
    # 기존 Workflow 조회·검증·재실행 / Evidence Engine
    # =====================================================

    def collect_workflow_evidence(self, workflow_id: str) -> dict[str, Any]:
        """Workflow 산출물, Worker 결과, Git 및 테스트 증거를 수집한다."""
        workflow = self.require_workflow(workflow_id)
        generated_root = BASE_DIR / "generated_projects"
        project_dirs = []
        if generated_root.exists():
            project_dirs = [
                path for path in generated_root.iterdir()
                if path.is_dir() and path.name.startswith(workflow_id)
            ]

        artifact_files: list[str] = []
        worker_result_files: list[str] = []
        test_files: list[str] = []
        test_passed = False
        test_output = ""

        ignored_names = {"permission_requests.json"}
        for project_dir in project_dirs:
            for path in project_dir.rglob("*"):
                if not path.is_file():
                    continue
                rel = str(path.relative_to(BASE_DIR.parent))
                lower = path.name.lower()
                if lower.startswith("execution_worker_") and lower.endswith(".json"):
                    worker_result_files.append(rel)
                    try:
                        payload = json.loads(path.read_text(encoding="utf-8"))
                        text = json.dumps(payload, ensure_ascii=False).lower()
                        if any(token in text for token in ("test passed", "tests passed", "pytest", "unittest", "테스트 성공")):
                            test_passed = not any(token in text for token in ("failed", "error", "테스트 실패"))
                            test_output = text[-2000:]
                    except (OSError, json.JSONDecodeError):
                        pass
                    continue
                if path.name in ignored_names:
                    continue
                artifact_files.append(rel)
                if lower.startswith("test_") or lower.endswith(("_test.py", ".test.js", ".spec.js")):
                    test_files.append(rel)

        git_status = ""
        git_diff = ""
        repo_root = BASE_DIR.parent
        try:
            git_status = subprocess.run(
                ["git", "status", "--short"], cwd=repo_root,
                capture_output=True, text=True, timeout=15, check=False,
            ).stdout.strip()
            git_diff = subprocess.run(
                ["git", "diff", "--", "."], cwd=repo_root,
                capture_output=True, text=True, timeout=15, check=False,
            ).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            pass

        metadata = dict(workflow.get("metadata") or {})
        recorded = dict(metadata.get("evidence") or {})
        if recorded.get("test_passed") is True:
            test_passed = True
        if recorded.get("test_output"):
            test_output = str(recorded["test_output"])

        evidence = {
            "workflow_id": workflow_id,
            "project_directories": [str(p) for p in project_dirs],
            "artifact_files": sorted(set(artifact_files)),
            "worker_result_files": sorted(set(worker_result_files)),
            "test_files": sorted(set(test_files)),
            "test_passed": bool(test_passed),
            "test_output": test_output,
            "git_status": git_status,
            "git_diff": git_diff,
            "collected_at": self._utc_now(),
        }
        metadata["evidence"] = evidence
        self._set_workflow_fields(workflow_id, {"metadata": metadata, "updated_at": self._utc_now()})
        return evidence

    def evaluate_completion_evidence(self, workflow_id: str) -> dict[str, Any]:
        """증거 기반 완료 가능 여부를 판정한다."""
        workflow = self.require_workflow(workflow_id)
        evidence = self.collect_workflow_evidence(workflow_id)
        metadata = dict(workflow.get("metadata") or {})
        required = bool(metadata.get("evidence_required"))
        if not required:
            return {"passed": True, "required": False, "missing": [], "evidence": evidence}

        missing: list[str] = []
        if not evidence["artifact_files"]:
            missing.append("actual_artifact_or_modified_file")
        if not evidence["worker_result_files"]:
            missing.append("worker_execution_result")
        if not evidence["test_passed"]:
            missing.append("successful_test_result")

        return {
            "passed": not missing,
            "required": True,
            "missing": missing,
            "evidence": evidence,
        }

    def reopen_workflow(self, workflow_id: str, *, reason: str = "증거 검증을 위한 재개") -> dict[str, Any]:
        """완료/실패 Workflow를 동일 ID로 다시 실행 가능한 상태로 되돌린다."""
        workflow = self.require_workflow(workflow_id)
        steps = workflow.get("steps", [])
        start_index = 0
        for index, step in enumerate(steps):
            if step.get("step_type") in {"execution", "manager_review", "ceo_review", "memory_update", "next_action"}:
                start_index = index
                break
        self._reset_steps_from_index(workflow_id, start_index)
        self._set_workflow_fields(workflow_id, {
            "status": "ready",
            "current_step_index": start_index,
            "failure_reason": "",
            "completed_at": "",
            "next_action": reason,
            "updated_at": self._utc_now(),
        })
        return {"reopened": True, "workflow": self.require_workflow(workflow_id)}

    def verify_workflow(self, workflow_id: str) -> dict[str, Any]:
        """기존 Workflow를 검증하고 증거가 부족하면 completed를 취소한다."""
        evaluation = self.evaluate_completion_evidence(workflow_id)
        if evaluation["passed"]:
            self._set_workflow_fields(workflow_id, {
                "status": "completed",
                "failure_reason": "",
                "completed_at": self._utc_now(),
                "updated_at": self._utc_now(),
            })
        else:
            self._set_workflow_fields(workflow_id, {
                "status": "failed",
                "failure_reason": "완료 증거 부족: " + ", ".join(evaluation["missing"]),
                "completed_at": "",
                "next_action": "동일 Workflow ID로 구현 및 테스트를 재실행해야 합니다.",
                "updated_at": self._utc_now(),
            })
        return {"verified": True, "evaluation": evaluation, "workflow": self.require_workflow(workflow_id)}

    def handle_existing_workflow_request(self, workflow_id: str, instruction: str) -> dict[str, Any]:
        """신규 Workflow를 만들지 않고 기존 Workflow 명령을 처리한다."""
        text = self._clean_multiline(instruction).lower()
        if any(word in text for word in ("취소", "cancel")):
            result = self.cancel_workflow(workflow_id, reason=instruction)
            action = "cancelled"
        elif any(word in text for word in ("재실행", "재개", "retry", "resume", "계속 구현")):
            workflow = self.require_workflow(workflow_id)
            if workflow.get("status") in {"completed", "failed", "blocked", "cancelled"}:
                self.reopen_workflow(workflow_id, reason=instruction)
            result = self.resume_workflow(workflow_id)
            action = "resumed"
        elif any(word in text for word in ("검증", "산출물", "증거", "git diff", "테스트 결과")):
            result = self.verify_workflow(workflow_id)
            action = "verified"
        else:
            result = {
                "workflow": self.require_workflow(workflow_id),
                "progress": self.get_workflow_progress(workflow_id),
                "evidence": self.collect_workflow_evidence(workflow_id),
            }
            action = "reported"
        result["existing_workflow_action"] = action
        result["workflow_id"] = workflow_id
        result["created_new_workflow"] = False
        return result

    # =====================================================
    # 승인 및 반려
    # =====================================================

    def approve_workflow(
        self,
        workflow_id: str,
        *,
        approval_note: str = "",
        approved_by: str = "owner",
        auto_resume: bool = True,
    ) -> dict[str, Any]:
        workflow = self.require_workflow(workflow_id)

        if not workflow.get("requires_approval"):
            raise WorkflowStateError(
                "이 Workflow는 승인이 필요하지 않습니다."
            )

        if workflow.get("status") != "waiting_approval":
            raise WorkflowStateError(
                "승인 대기 상태에서만 승인할 수 있습니다."
            )

        now = self._utc_now()
        self._set_workflow_fields(
            workflow_id,
            {
                "status": "approved",
                "approval_status": "approved",
                "approved_at": now,
                "rejected_at": "",
                "rejection_reason": "",
                "updated_at": now,
            },
        )

        workflow = self.require_workflow(workflow_id)

        self.company_memory.remember_approval(
            title=f"Workflow 승인: {workflow['title']}",
            content=(
                approval_note
                or f"{approved_by}가 Workflow를 승인했다."
            ),
            project_id=workflow.get("project_id"),
            source_agent_id=workflow.get(
                "ceo_agent_id"
            ),
            approved=True,
            importance=5,
            tags=[
                "workflow",
                workflow_id,
                "승인",
            ],
        )

        self._move_to_next_step(workflow_id)

        # 개발 Workflow는 대표 승인 후에만 ai-ceo-dev 브랜치로 push한다.
        push_result = None
        try:
            from development_engine import development_engine
            push_result = development_engine.push_after_approval(workflow_id)
        except Exception as exc:
            self._set_workflow_fields(
                workflow_id,
                {
                    "status": "failed",
                    "failure_reason": f"대표 승인 후 Git push 실패: {exc}",
                    "next_action": "GitHub 인증과 ai-ceo-dev 브랜치를 확인한 뒤 재실행하십시오.",
                    "updated_at": self._utc_now(),
                },
            )
            return {
                "approved": True,
                "push_result": {"pushed": False, "error": str(exc)},
                "workflow": self.require_workflow(workflow_id),
            }

        if auto_resume:
            resumed = self.run_workflow(workflow_id)
            return {
                "approved": True,
                "push_result": push_result,
                "workflow": resumed["workflow"],
            }

        self._set_workflow_status(
            workflow_id,
            "ready",
        )

        return {
            "approved": True,
            "workflow": self.require_workflow(
                workflow_id
            ),
        }

    def reject_workflow(
        self,
        workflow_id: str,
        *,
        rejection_reason: str,
        rejected_by: str = "owner",
    ) -> dict[str, Any]:
        workflow = self.require_workflow(workflow_id)
        cleaned_reason = self._clean_multiline(
            rejection_reason
        )

        if not cleaned_reason:
            raise WorkflowValidationError(
                "반려 사유는 비어 있을 수 없습니다."
            )

        if workflow.get("status") != "waiting_approval":
            raise WorkflowStateError(
                "승인 대기 상태에서만 반려할 수 있습니다."
            )

        now = self._utc_now()
        self._set_workflow_fields(
            workflow_id,
            {
                "status": "rejected",
                "approval_status": "rejected",
                "rejected_at": now,
                "rejection_reason": cleaned_reason,
                "updated_at": now,
            },
        )

        self.company_memory.remember_approval(
            title=f"Workflow 반려: {workflow['title']}",
            content=(
                f"{rejected_by} 반려 사유: "
                f"{cleaned_reason}"
            ),
            project_id=workflow.get("project_id"),
            source_agent_id=workflow.get(
                "ceo_agent_id"
            ),
            approved=False,
            importance=5,
            tags=[
                "workflow",
                workflow_id,
                "반려",
            ],
        )

        return {
            "rejected": True,
            "workflow": self.require_workflow(
                workflow_id
            ),
        }

    def revise_rejected_workflow(
        self,
        workflow_id: str,
        *,
        revised_objective: str | None = None,
        revised_instruction: str | None = None,
        revision_note: str = "",
        reset_from_step_type: str = "ceo_analysis",
    ) -> dict[str, Any]:
        workflow = self.require_workflow(workflow_id)

        if workflow.get("status") != "rejected":
            raise WorkflowStateError(
                "반려된 Workflow만 수정할 수 있습니다."
            )

        updates: dict[str, Any] = {
            "status": "ready",
            "approval_status": "pending",
            "approval_requested_at": "",
            "approved_at": "",
            "rejected_at": "",
            "rejection_reason": "",
            "failure_reason": "",
            "updated_at": self._utc_now(),
        }

        if revised_objective is not None:
            cleaned = self._clean_multiline(
                revised_objective
            )

            if not cleaned:
                raise WorkflowValidationError(
                    "revised_objective는 비어 있을 수 없습니다."
                )

            updates["objective"] = cleaned

        if revised_instruction is not None:
            cleaned = self._clean_multiline(
                revised_instruction
            )

            if not cleaned:
                raise WorkflowValidationError(
                    "revised_instruction은 비어 있을 수 없습니다."
                )

            updates["owner_instruction"] = cleaned

        step_index = self._find_step_index_by_type(
            workflow,
            reset_from_step_type,
        )
        updates["current_step_index"] = step_index

        self._set_workflow_fields(
            workflow_id,
            updates,
        )
        self._reset_steps_from_index(
            workflow_id,
            step_index,
        )

        if revision_note:
            self.company_memory.remember_decision(
                title=f"Workflow 수정: {workflow['title']}",
                content=revision_note,
                source="owner",
                source_agent_id=workflow.get(
                    "ceo_agent_id"
                ),
                project_id=workflow.get(
                    "project_id"
                ),
                importance=5,
                tags=[
                    "workflow",
                    workflow_id,
                    "수정",
                ],
            )

        return {
            "revised": True,
            "workflow": self.require_workflow(
                workflow_id
            ),
        }

    # =====================================================
    # 관리 기능
    # =====================================================

    def pause_workflow(
        self,
        workflow_id: str,
    ) -> dict[str, Any]:
        workflow = self.require_workflow(workflow_id)

        if workflow.get("status") in self.TERMINAL_WORKFLOW_STATUSES:
            raise WorkflowStateError(
                "종료된 Workflow는 일시중지할 수 없습니다."
            )

        self._set_workflow_status(
            workflow_id,
            "paused",
        )

        return {
            "paused": True,
            "workflow": self.require_workflow(
                workflow_id
            ),
        }

    def cancel_workflow(
        self,
        workflow_id: str,
        *,
        reason: str = "",
    ) -> dict[str, Any]:
        workflow = self.require_workflow(workflow_id)

        if workflow.get("status") == "completed":
            raise WorkflowStateError(
                "완료된 Workflow는 취소할 수 없습니다."
            )

        now = self._utc_now()
        updates = {
            "status": "cancelled",
            "failure_reason": self._clean_multiline(
                reason
            ),
            "updated_at": now,
            "completed_at": now,
        }
        self._set_workflow_fields(
            workflow_id,
            updates,
        )
        self._cancel_remaining_steps(workflow_id)

        return {
            "cancelled": True,
            "workflow": self.require_workflow(
                workflow_id
            ),
        }

    def set_result_summary(
        self,
        workflow_id: str,
        *,
        result_summary: str,
        next_action: str = "",
    ) -> dict[str, Any]:
        cleaned_summary = self._clean_multiline(
            result_summary
        )

        if not cleaned_summary:
            raise WorkflowValidationError(
                "result_summary는 비어 있을 수 없습니다."
            )

        self._set_workflow_fields(
            workflow_id,
            {
                "result_summary": cleaned_summary,
                "next_action": self._clean_multiline(
                    next_action
                ),
                "updated_at": self._utc_now(),
            },
        )

        return {
            "updated": True,
            "workflow": self.require_workflow(
                workflow_id
            ),
        }

    def assign_manager(
        self,
        workflow_id: str,
        manager_agent_id: str,
    ) -> dict[str, Any]:
        self._validate_agent_exists(manager_agent_id)
        workflow = self.require_workflow(workflow_id)

        if workflow.get("status") in self.TERMINAL_WORKFLOW_STATUSES:
            raise WorkflowStateError(
                "종료된 Workflow는 지점장을 변경할 수 없습니다."
            )

        ceo_agent_id = str(
            workflow.get("ceo_agent_id")
        )

        handoff = self.handoff_manager.get_handoff(
            source_agent_id=ceo_agent_id,
            target_agent_id=manager_agent_id,
        )

        if handoff is None:
            self.handoff_manager.register_handoff(
                source_agent_id=ceo_agent_id,
                target_agent_id=manager_agent_id,
                description=(
                    f"Workflow {workflow_id} 지점장 위임"
                ),
                created_reason="Workflow Manager 자동 연결",
            )

        self._set_workflow_fields(
            workflow_id,
            {
                "manager_agent_id": manager_agent_id,
                "updated_at": self._utc_now(),
            },
        )

        return {
            "assigned": True,
            "workflow": self.require_workflow(
                workflow_id
            ),
        }

    def assign_workers(
        self,
        workflow_id: str,
        worker_agent_ids: list[str],
    ) -> dict[str, Any]:
        cleaned_worker_ids = self._clean_string_list(
            worker_agent_ids
        )

        if not cleaned_worker_ids:
            raise WorkflowValidationError(
                "worker_agent_ids에는 한 명 이상의 Agent가 필요합니다."
            )

        workflow = self.require_workflow(workflow_id)
        manager_agent_id = workflow.get(
            "manager_agent_id"
        )

        if not manager_agent_id:
            raise WorkflowStateError(
                "AI 직원을 배정하기 전에 지점장이 필요합니다."
            )

        for worker_agent_id in cleaned_worker_ids:
            self._validate_agent_exists(worker_agent_id)

            handoff = self.handoff_manager.get_handoff(
                source_agent_id=str(manager_agent_id),
                target_agent_id=worker_agent_id,
            )

            if handoff is None:
                self.handoff_manager.register_handoff(
                    source_agent_id=str(
                        manager_agent_id
                    ),
                    target_agent_id=worker_agent_id,
                    description=(
                        f"Workflow {workflow_id} 직원 위임"
                    ),
                    created_reason="Workflow Manager 자동 연결",
                )

        self._set_workflow_fields(
            workflow_id,
            {
                "worker_agent_ids": cleaned_worker_ids,
                "updated_at": self._utc_now(),
            },
        )

        return {
            "assigned": True,
            "workflow": self.require_workflow(
                workflow_id
            ),
        }

    # =====================================================
    # Step Handler
    # =====================================================

    def register_step_handler(
        self,
        step_type: str,
        handler: Callable[
            [dict[str, Any], dict[str, Any]],
            dict[str, Any],
        ],
    ) -> None:
        cleaned_step_type = self._clean_text(
            step_type
        ).lower()

        if cleaned_step_type not in self.ALLOWED_STEP_TYPES:
            raise WorkflowValidationError(
                f"지원하지 않는 step_type입니다: {cleaned_step_type}"
            )

        if not callable(handler):
            raise WorkflowValidationError(
                "handler는 호출 가능한 함수여야 합니다."
            )

        self._step_handlers[cleaned_step_type] = handler

    def _register_default_handlers(self) -> None:
        self.register_step_handler(
            "owner_intake",
            self._handle_owner_intake,
        )
        self.register_step_handler(
            "ceo_analysis",
            self._handle_ceo_analysis,
        )
        self.register_step_handler(
            "manager_assignment",
            self._handle_manager_assignment,
        )
        self.register_step_handler(
            "worker_assignment",
            self._handle_worker_assignment,
        )
        self.register_step_handler(
            "execution",
            self._handle_execution,
        )
        self.register_step_handler(
            "development_execution",
            self._handle_development_execution,
        )
        self.register_step_handler(
            "manager_review",
            self._handle_manager_review,
        )
        self.register_step_handler(
            "ceo_review",
            self._handle_ceo_review,
        )
        self.register_step_handler(
            "approval_request",
            self._handle_approval_request,
        )
        self.register_step_handler(
            "memory_update",
            self._handle_memory_update,
        )
        self.register_step_handler(
            "next_action",
            self._handle_next_action,
        )
        self.register_step_handler(
            "custom",
            self._handle_custom,
        )

    def _handle_owner_intake(
        self,
        workflow: dict[str, Any],
        step: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "accepted": True,
            "requested_by": workflow.get(
                "requested_by"
            ),
            "owner_instruction": workflow.get(
                "owner_instruction"
            ),
        }

    def _handle_ceo_analysis(
        self,
        workflow: dict[str, Any],
        step: dict[str, Any],
    ) -> dict[str, Any]:
        ceo_agent_id = str(
            workflow.get("ceo_agent_id")
        )
        self._validate_agent_exists(ceo_agent_id)

        context = self.company_memory.build_context_text(
            query=workflow.get("objective", ""),
            project_id=workflow.get("project_id"),
            limit=10,
        )

        return {
            "analysis_ready": True,
            "ceo_agent_id": ceo_agent_id,
            "objective": workflow.get("objective"),
            "company_context": context,
            "execution_policy": (
                "AI CEO는 직접 실무를 수행하지 않고 "
                "지점장에게 업무를 위임한다."
            ),
        }

    def _handle_manager_assignment(
        self,
        workflow: dict[str, Any],
        step: dict[str, Any],
    ) -> dict[str, Any]:
        """
        CEO가 임명한 지점장이 업무를 분석하고 필요한 직원을
        자동으로 검색·채용·배정한 뒤 실행 단계를 Workflow에 추가한다.
        """

        manager_agent_id = workflow.get("manager_agent_id")

        if not manager_agent_id:
            raise WorkflowExecutionError(
                "배정된 지점장이 없습니다."
            )

        ceo_agent_id = str(
            workflow.get("ceo_agent_id")
        )
        workflow_id = str(
            workflow.get("workflow_id")
        )

        handoff = self.handoff_manager.get_handoff(
            source_agent_id=ceo_agent_id,
            target_agent_id=str(manager_agent_id),
        )

        if handoff is None:
            self.handoff_manager.register_handoff(
                source_agent_id=ceo_agent_id,
                target_agent_id=str(manager_agent_id),
                description=(
                    f"{workflow['title']} 업무를 지점장에게 위임한다."
                ),
                created_reason="Workflow 실행",
            )

        # 순환 import 방지를 위해 실행 시점에 불러온다.
        from manager import manager_controller

        staffing_result = manager_controller.organize_workers(
            workflow_id
        )

        worker_agent_ids = self._clean_string_list(
            staffing_result.get(
                "worker_agent_ids",
                [],
            )
        )

        if not worker_agent_ids:
            raise WorkflowExecutionError(
                "지점장이 업무 수행에 필요한 직원을 구성하지 못했습니다."
            )

        # 지점장이 만든 직원들의 배정·실행 단계를 현재 단계 뒤에 추가한다.
        data = self._read_data()

        for saved_workflow in data["workflows"]:
            if saved_workflow.get("workflow_id") != workflow_id:
                continue

            steps = saved_workflow.get("steps", [])

            existing_execution_agents = {
                saved_step.get("assigned_agent_id")
                for saved_step in steps
                if saved_step.get("step_type") == "execution"
            }

            current_step_index = next(
                (
                    index
                    for index, saved_step in enumerate(steps)
                    if saved_step.get("step_id")
                    == step.get("step_id")
                ),
                int(
                    saved_workflow.get(
                        "current_step_index",
                        0,
                    )
                ),
            )

            new_steps: list[dict[str, Any]] = []
            now = self._utc_now()

            has_worker_assignment = any(
                saved_step.get("step_type")
                == "worker_assignment"
                for saved_step in steps
            )

            if not has_worker_assignment:
                new_steps.append(
                    asdict(
                        self._make_step(
                            name="지점장 직원 자동 구성",
                            step_type="worker_assignment",
                            assigned_agent_id=str(
                                manager_agent_id
                            ),
                            now=now,
                            input_data={
                                "worker_agent_ids": worker_agent_ids,
                                "automatic": True,
                            },
                        )
                    )
                )

            for worker_agent_id in worker_agent_ids:
                if (
                    worker_agent_id
                    in existing_execution_agents
                ):
                    continue

                new_steps.append(
                    asdict(
                        self._make_step(
                            name=(
                                f"{worker_agent_id} 업무 실행"
                            ),
                            step_type="execution",
                            assigned_agent_id=worker_agent_id,
                            now=now,
                            input_data={
                                "automatic_assignment": True,
                            },
                        )
                    )
                )

            if new_steps:
                insert_position = current_step_index + 1
                saved_workflow["steps"][
                    insert_position:insert_position
                ] = new_steps
                saved_workflow["updated_at"] = now
                self._write_data(data)

            break
        else:
            raise WorkflowNotFoundError(
                f"Workflow를 찾을 수 없습니다: {workflow_id}"
            )

        return {
            "assigned": True,
            "manager_agent_id": manager_agent_id,
            "manager_role": staffing_result.get(
                "manager_role"
            ),
            "analysis_summary": staffing_result.get(
                "analysis_summary"
            ),
            "worker_agent_ids": worker_agent_ids,
            "workers": staffing_result.get(
                "workers",
                [],
            ),
            "automatic_staffing": True,
        }

    def _handle_worker_assignment(
        self,
        workflow: dict[str, Any],
        step: dict[str, Any],
    ) -> dict[str, Any]:
        manager_agent_id = workflow.get(
            "manager_agent_id"
        )
        worker_agent_ids = workflow.get(
            "worker_agent_ids",
            [],
        )

        if not manager_agent_id:
            raise WorkflowExecutionError(
                "AI 직원을 관리할 지점장이 없습니다."
            )

        if not worker_agent_ids:
            return {
                "assigned": False,
                "reason": "no_workers_required",
                "worker_agent_ids": [],
            }

        for worker_agent_id in worker_agent_ids:
            handoff = self.handoff_manager.get_handoff(
                source_agent_id=str(manager_agent_id),
                target_agent_id=str(worker_agent_id),
            )

            if handoff is None:
                self.handoff_manager.register_handoff(
                    source_agent_id=str(
                        manager_agent_id
                    ),
                    target_agent_id=str(
                        worker_agent_id
                    ),
                    description=(
                        f"{workflow['title']} 실무를 위임한다."
                    ),
                    created_reason="Workflow 실행",
                )

        return {
            "assigned": True,
            "manager_agent_id": manager_agent_id,
            "worker_agent_ids": worker_agent_ids,
        }

    def _handle_execution(
        self,
        workflow: dict[str, Any],
        step: dict[str, Any],
    ) -> dict[str, Any]:
        """
        배정된 AI 직원을 실제 OpenAI Agent로 실행하고,
        생성 결과물을 로컬 프로젝트 폴더에 저장한다.
        """

        assigned_agent_id = step.get(
            "assigned_agent_id"
        )

        if not assigned_agent_id:
            raise WorkflowExecutionError(
                "실행 단계에 배정된 Agent가 없습니다."
            )

        self._validate_agent_exists(
            str(assigned_agent_id)
        )

        # 순환 import 방지를 위해 실행 시점에 불러온다.
        from worker_controller import worker_controller

        execution_result = worker_controller.execute_step(
            workflow=workflow,
            step=step,
        )

        execution_status = str(execution_result.get("status") or "").strip()
        if execution_status not in {"completed", "waiting_permission"}:
            raise WorkflowExecutionError(
                execution_result.get("error")
                or execution_result.get("failure_reason")
                or f"Worker 실제 실행 실패: {execution_status or 'unknown'}"
            )

        development_evidence = execution_result.get("development_evidence") or {}
        if development_evidence:
            metadata = dict(workflow.get("metadata") or {})
            metadata["development_evidence"] = development_evidence
            metadata["evidence_required"] = True
            self._set_workflow_fields(
                str(workflow["workflow_id"]),
                {"metadata": metadata, "updated_at": self._utc_now()},
            )

        return {
            "execution_completed": (
                execution_status == "completed"
            ),
            "execution_status": execution_result.get("status"),
            "assigned_agent_id": assigned_agent_id,
            "worker_role": execution_result.get("worker_role"),
            "work_summary": execution_result.get("work_summary"),
            "result_summary": execution_result.get("result_summary"),
            "saved_files": execution_result.get("saved_files", []),
            "permission_requests": execution_result.get(
                "permission_requests",
                [],
            ),
            "next_action": execution_result.get("next_action", ""),
            "limitations": execution_result.get("limitations", []),
            "development_evidence": development_evidence,
        }

    def _handle_development_execution(
        self,
        workflow: dict[str, Any],
        step: dict[str, Any],
    ) -> dict[str, Any]:
        """개발 Workflow를 일반 Worker가 아닌 Development Engine으로 직접 실행한다."""
        from development_engine import development_engine

        workflow_id = str(workflow.get("workflow_id") or "")
        result = development_engine.execute(
            workflow=workflow,
            worker_agent_id="development_engine",
        )
        evidence = dict(result.get("development_evidence") or {})
        metadata = dict(workflow.get("metadata") or {})
        metadata["development_evidence"] = evidence
        metadata["evidence"] = {
            "artifact_files": list(result.get("saved_files") or []),
            "worker_result_files": [
                str(development_engine.state_file_for(workflow_id))
            ],
            "test_passed": bool((evidence.get("tests") or {}).get("passed")),
            "test_output": str((evidence.get("tests") or {}).get("output") or ""),
            "git_diff": str(evidence.get("git_diff") or ""),
            "git_commit": str(evidence.get("git_commit") or ""),
        }
        self._set_workflow_fields(
            workflow_id,
            {
                "worker_agent_ids": ["development_engine"],
                "result_summary": str(result.get("result_summary") or result.get("work_summary") or ""),
                "next_action": str(result.get("next_action") or "대표 승인 후 Git push"),
                "metadata": metadata,
                "updated_at": self._utc_now(),
            },
        )
        return {
            "execution_completed": result.get("status") == "completed",
            "execution_status": result.get("status"),
            "assigned_agent_id": "development_engine",
            "work_summary": result.get("work_summary"),
            "result_summary": result.get("result_summary"),
            "saved_files": result.get("saved_files", []),
            "permission_requests": result.get("permission_requests", []),
            "next_action": result.get("next_action", ""),
            "limitations": result.get("limitations", []),
            "development_evidence": evidence,
        }

    def _handle_manager_review(
        self,
        workflow: dict[str, Any],
        step: dict[str, Any],
    ) -> dict[str, Any]:
        manager_agent_id = workflow.get(
            "manager_agent_id"
        )

        if not manager_agent_id:
            return {
                "reviewed": False,
                "reason": "manager_not_assigned",
            }

        return {
            "reviewed": True,
            "manager_agent_id": manager_agent_id,
            "review_standard": [
                "목표 충족 여부",
                "누락 업무 여부",
                "대표 승인 필요 여부",
                "다음 업무 준비 여부",
            ],
        }

    def _handle_ceo_review(
        self,
        workflow: dict[str, Any],
        step: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "reviewed": True,
            "ceo_agent_id": workflow.get(
                "ceo_agent_id"
            ),
            "requires_approval": workflow.get(
                "requires_approval"
            ),
            "review_result": (
                "Workflow 단계와 Agent 배정 구조를 검토했다."
            ),
        }

    def _handle_approval_request(
        self,
        workflow: dict[str, Any],
        step: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "approval_requested": True,
            "workflow_id": workflow.get(
                "workflow_id"
            ),
            "title": workflow.get("title"),
            "objective": workflow.get("objective"),
            "requested_to": "owner",
        }

    def _handle_memory_update(
        self,
        workflow: dict[str, Any],
        step: dict[str, Any],
    ) -> dict[str, Any]:
        result_summary = (
            workflow.get("result_summary")
            or self._build_workflow_summary(workflow)
        )

        memory_result = (
            self.company_memory.remember_agent_result(
                title=f"Workflow 결과: {workflow['title']}",
                content=result_summary,
                source_agent_id=str(
                    workflow.get("ceo_agent_id")
                ),
                project_id=workflow.get(
                    "project_id"
                ),
                related_agent_ids=[
                    agent_id
                    for agent_id in [
                        workflow.get("manager_agent_id"),
                        *workflow.get(
                            "worker_agent_ids",
                            [],
                        ),
                    ]
                    if agent_id
                ],
                importance=4,
                approved=True,
                tags=[
                    "workflow",
                    str(workflow.get("workflow_id")),
                    "업무결과",
                ],
            )
        )

        return {
            "memory_updated": True,
            "memory_result": memory_result,
        }

    def _handle_next_action(
        self,
        workflow: dict[str, Any],
        step: dict[str, Any],
    ) -> dict[str, Any]:
        next_action = (
            workflow.get("next_action")
            or "대표의 다음 지시 또는 후속 Workflow 생성을 대기한다."
        )

        memory_result = (
            self.company_memory.remember_next_action(
                title=f"다음 업무: {workflow['title']}",
                content=next_action,
                source_agent_id=str(
                    workflow.get("ceo_agent_id")
                ),
                project_id=workflow.get(
                    "project_id"
                ),
                importance=4,
                tags=[
                    "workflow",
                    str(workflow.get("workflow_id")),
                    "다음업무",
                ],
            )
        )

        return {
            "next_action": next_action,
            "memory_result": memory_result,
        }

    def _handle_custom(
        self,
        workflow: dict[str, Any],
        step: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "custom_step_completed": True,
            "input_data": step.get(
                "input_data",
                {},
            ),
        }

    # =====================================================
    # 내부 상태 관리
    # =====================================================

    def _request_approval(
        self,
        workflow_id: str,
    ) -> None:
        now = self._utc_now()
        self._set_workflow_fields(
            workflow_id,
            {
                "status": "waiting_approval",
                "approval_status": "pending",
                "approval_requested_at": now,
                "updated_at": now,
            },
        )

    def _complete_workflow(
        self,
        workflow_id: str,
    ) -> dict[str, Any]:
        workflow = self.require_workflow(workflow_id)
        now = self._utc_now()
        summary = (
            workflow.get("result_summary")
            or self._build_workflow_summary(workflow)
        )
        evaluation = self.evaluate_completion_evidence(workflow_id)
        if not evaluation["passed"]:
            missing = ", ".join(evaluation["missing"])
            self._set_workflow_fields(
                workflow_id,
                {
                    "status": "failed",
                    "result_summary": summary,
                    "failure_reason": f"완료 증거 부족: {missing}",
                    "next_action": "실제 파일 생성·수정과 성공한 테스트 증거를 확보한 뒤 동일 Workflow를 재실행하십시오.",
                    "completed_at": "",
                    "updated_at": now,
                },
            )
            return {
                "executed": False,
                "reason": "completion_evidence_missing",
                "missing_evidence": evaluation["missing"],
                "evidence": evaluation["evidence"],
                "workflow": self.require_workflow(workflow_id),
            }

        self._set_workflow_fields(
            workflow_id,
            {
                "status": "completed",
                "result_summary": summary,
                "failure_reason": "",
                "completed_at": now,
                "updated_at": now,
            },
        )

        return {
            "executed": True,
            "reason": "workflow_completed",
            "workflow": self.require_workflow(
                workflow_id
            ),
        }

    def _start_step(
        self,
        workflow_id: str,
        step_id: str,
    ) -> None:
        now = self._utc_now()
        self._update_step(
            workflow_id,
            step_id,
            {
                "status": "running",
                "started_at": now,
                "updated_at": now,
                "error_message": "",
            },
        )

    def _complete_step(
        self,
        workflow_id: str,
        step_id: str,
        output_data: dict[str, Any],
    ) -> None:
        now = self._utc_now()
        self._update_step(
            workflow_id,
            step_id,
            {
                "status": "completed",
                "output_data": dict(
                    output_data or {}
                ),
                "completed_at": now,
                "updated_at": now,
                "error_message": "",
            },
        )

    def _fail_step(
        self,
        workflow_id: str,
        step_id: str,
        error_message: str,
    ) -> dict[str, Any]:
        now = self._utc_now()
        self._update_step(
            workflow_id,
            step_id,
            {
                "status": "failed",
                "error_message": error_message,
                "completed_at": now,
                "updated_at": now,
            },
        )
        self._set_workflow_fields(
            workflow_id,
            {
                "status": "failed",
                "failure_reason": error_message,
                "updated_at": now,
            },
        )

        return {
            "failed": True,
            "error_message": error_message,
        }

    def _move_to_next_step(
        self,
        workflow_id: str,
    ) -> None:
        workflow = self.require_workflow(workflow_id)
        next_index = int(
            workflow.get("current_step_index", 0)
        ) + 1

        self._set_workflow_fields(
            workflow_id,
            {
                "current_step_index": next_index,
                "status": "running",
                "updated_at": self._utc_now(),
            },
        )

    def _update_step(
        self,
        workflow_id: str,
        step_id: str,
        updates: dict[str, Any],
    ) -> None:
        data = self._read_data()

        for workflow in data["workflows"]:
            if workflow.get("workflow_id") != workflow_id:
                continue

            for step in workflow.get("steps", []):
                if step.get("step_id") == step_id:
                    step.update(updates)
                    workflow["updated_at"] = self._utc_now()
                    self._write_data(data)
                    return

            raise WorkflowNotFoundError(
                f"Workflow Step을 찾을 수 없습니다: {step_id}"
            )

        raise WorkflowNotFoundError(
            f"Workflow를 찾을 수 없습니다: {workflow_id}"
        )

    def _set_workflow_status(
        self,
        workflow_id: str,
        status: str,
    ) -> None:
        if status not in self.ALLOWED_WORKFLOW_STATUSES:
            raise WorkflowValidationError(
                f"지원하지 않는 Workflow status입니다: {status}"
            )

        self._set_workflow_fields(
            workflow_id,
            {
                "status": status,
                "updated_at": self._utc_now(),
            },
        )

    def _set_workflow_fields(
        self,
        workflow_id: str,
        updates: dict[str, Any],
    ) -> None:
        data = self._read_data()

        for workflow in data["workflows"]:
            if workflow.get("workflow_id") == workflow_id:
                workflow.update(updates)
                self._write_data(data)
                return

        raise WorkflowNotFoundError(
            f"Workflow를 찾을 수 없습니다: {workflow_id}"
        )

    def _reset_steps_from_index(
        self,
        workflow_id: str,
        start_index: int,
    ) -> None:
        data = self._read_data()

        for workflow in data["workflows"]:
            if workflow.get("workflow_id") != workflow_id:
                continue

            for index, step in enumerate(
                workflow.get("steps", [])
            ):
                if index < start_index:
                    continue

                step.update(
                    {
                        "status": "pending",
                        "output_data": {},
                        "error_message": "",
                        "started_at": "",
                        "completed_at": "",
                        "updated_at": self._utc_now(),
                    }
                )

            workflow["updated_at"] = self._utc_now()
            self._write_data(data)
            return

        raise WorkflowNotFoundError(
            f"Workflow를 찾을 수 없습니다: {workflow_id}"
        )

    def _cancel_remaining_steps(
        self,
        workflow_id: str,
    ) -> None:
        data = self._read_data()

        for workflow in data["workflows"]:
            if workflow.get("workflow_id") != workflow_id:
                continue

            for step in workflow.get("steps", []):
                if step.get("status") in {
                    "pending",
                    "waiting",
                    "running",
                    "failed",
                }:
                    step["status"] = "cancelled"
                    step["updated_at"] = self._utc_now()

            self._write_data(data)
            return

    # =====================================================
    # 검증 및 통계
    # =====================================================

    def validate_workflow_store(self) -> dict[str, Any]:
        errors: list[dict[str, Any]] = []
        workflow_ids: set[str] = set()

        for workflow_index, workflow in enumerate(
            self._read_data()["workflows"]
        ):
            workflow_id = str(
                workflow.get("workflow_id", "")
            )

            if not workflow_id:
                errors.append(
                    {
                        "workflow_index": workflow_index,
                        "type": "missing_workflow_id",
                    }
                )
            elif workflow_id in workflow_ids:
                errors.append(
                    {
                        "workflow_index": workflow_index,
                        "type": "duplicate_workflow_id",
                        "workflow_id": workflow_id,
                    }
                )
            else:
                workflow_ids.add(workflow_id)

            status = str(
                workflow.get("status", "")
            )

            if status not in self.ALLOWED_WORKFLOW_STATUSES:
                errors.append(
                    {
                        "workflow_id": workflow_id,
                        "type": "invalid_workflow_status",
                        "value": status,
                    }
                )

            approval_status = str(
                workflow.get(
                    "approval_status",
                    "",
                )
            )

            if (
                approval_status
                not in self.ALLOWED_APPROVAL_STATUSES
            ):
                errors.append(
                    {
                        "workflow_id": workflow_id,
                        "type": "invalid_approval_status",
                        "value": approval_status,
                    }
                )

            step_ids: set[str] = set()

            for step_index, step in enumerate(
                workflow.get("steps", [])
            ):
                step_id = str(
                    step.get("step_id", "")
                )

                if not step_id:
                    errors.append(
                        {
                            "workflow_id": workflow_id,
                            "step_index": step_index,
                            "type": "missing_step_id",
                        }
                    )
                elif step_id in step_ids:
                    errors.append(
                        {
                            "workflow_id": workflow_id,
                            "step_index": step_index,
                            "type": "duplicate_step_id",
                            "step_id": step_id,
                        }
                    )
                else:
                    step_ids.add(step_id)

                step_status = str(
                    step.get("status", "")
                )

                if (
                    step_status
                    not in self.ALLOWED_STEP_STATUSES
                ):
                    errors.append(
                        {
                            "workflow_id": workflow_id,
                            "step_id": step_id,
                            "type": "invalid_step_status",
                            "value": step_status,
                        }
                    )

                step_type = str(
                    step.get("step_type", "")
                )

                if (
                    step_type
                    not in self.ALLOWED_STEP_TYPES
                ):
                    errors.append(
                        {
                            "workflow_id": workflow_id,
                            "step_id": step_id,
                            "type": "invalid_step_type",
                            "value": step_type,
                        }
                    )

        return {
            "valid": len(errors) == 0,
            "workflow_count": len(workflow_ids),
            "errors": errors,
        }

    def get_statistics(self) -> dict[str, Any]:
        workflows = self._read_data()["workflows"]
        by_status: dict[str, int] = {}
        by_project: dict[str, int] = {}
        approval_pending = 0
        completed_steps = 0
        failed_steps = 0

        for workflow in workflows:
            status = str(
                workflow.get("status", "")
            )
            by_status[status] = (
                by_status.get(status, 0) + 1
            )

            project_id = workflow.get(
                "project_id"
            )

            if project_id:
                project_key = str(project_id)
                by_project[project_key] = (
                    by_project.get(project_key, 0)
                    + 1
                )

            if (
                workflow.get("approval_status")
                == "pending"
                and workflow.get("status")
                == "waiting_approval"
            ):
                approval_pending += 1

            for step in workflow.get("steps", []):
                if step.get("status") == "completed":
                    completed_steps += 1
                elif step.get("status") == "failed":
                    failed_steps += 1

        return {
            "total_workflows": len(workflows),
            "by_status": by_status,
            "by_project": by_project,
            "approval_pending": approval_pending,
            "completed_steps": completed_steps,
            "failed_steps": failed_steps,
        }

    # =====================================================
    # 내부 유틸리티
    # =====================================================

    def _validate_workflow_input(
        self,
        *,
        title: str,
        objective: str,
        owner_instruction: str,
        requested_by: str,
        ceo_agent_id: str,
        manager_agent_id: str | None,
        worker_agent_ids: list[str],
    ) -> None:
        required = {
            "title": title,
            "objective": objective,
            "owner_instruction": owner_instruction,
            "requested_by": requested_by,
            "ceo_agent_id": ceo_agent_id,
        }

        for field_name, value in required.items():
            if not isinstance(value, str) or not value.strip():
                raise WorkflowValidationError(
                    f"{field_name}은 비어 있을 수 없습니다."
                )

        if (
            manager_agent_id is None
            and worker_agent_ids
        ):
            raise WorkflowValidationError(
                "AI 직원을 배정하려면 manager_agent_id가 필요합니다."
            )

    def _validate_agent_exists(
        self,
        agent_id: str,
    ) -> dict[str, Any]:
        record = self.registry.get_agent_by_id(
            agent_id
        )

        if record is None:
            raise WorkflowValidationError(
                f"Registry에 Agent가 없습니다: {agent_id}"
            )

        if record.get("status") != "active":
            raise WorkflowValidationError(
                f"비활성 Agent는 Workflow에 사용할 수 없습니다: {agent_id}"
            )

        return record

    def _find_step_index_by_type(
        self,
        workflow: dict[str, Any],
        step_type: str,
    ) -> int:
        for index, step in enumerate(
            workflow.get("steps", [])
        ):
            if step.get("step_type") == step_type:
                return index

        raise WorkflowValidationError(
            f"Workflow에 step_type이 없습니다: {step_type}"
        )

    def _build_workflow_summary(
        self,
        workflow: dict[str, Any],
    ) -> str:
        completed_steps = [
            str(step.get("name"))
            for step in workflow.get("steps", [])
            if step.get("status") == "completed"
        ]

        return (
            f"Workflow '{workflow.get('title')}'의 "
            f"{len(completed_steps)}개 단계가 완료되었다. "
            f"목표: {workflow.get('objective')}"
        )

    @staticmethod
    def _make_step(
        *,
        name: str,
        step_type: str,
        assigned_agent_id: str | None,
        now: str,
        input_data: dict[str, Any] | None = None,
    ) -> WorkflowStep:
        return WorkflowStep(
            step_id=WorkflowManager._generate_step_id(),
            name=name,
            step_type=step_type,
            assigned_agent_id=assigned_agent_id,
            status="pending",
            input_data=dict(input_data or {}),
            output_data={},
            error_message="",
            retry_count=0,
            max_retries=2,
            started_at="",
            completed_at="",
            updated_at=now,
        )

    @staticmethod
    def _clean_text(value: Any) -> str:
        if value is None:
            return ""

        return " ".join(
            str(value).strip().split()
        )

    @staticmethod
    def _clean_multiline(value: Any) -> str:
        if value is None:
            return ""

        return "\n".join(
            line.rstrip()
            for line in str(value).strip().splitlines()
        ).strip()

    @staticmethod
    def _clean_optional_text(
        value: Any,
    ) -> str | None:
        cleaned = WorkflowManager._clean_text(
            value
        )
        return cleaned or None

    @staticmethod
    def _clean_string_list(
        values: Any,
    ) -> list[str]:
        if values is None:
            return []

        if isinstance(values, str):
            values = [values]

        if not isinstance(values, list):
            raise WorkflowValidationError(
                "목록 필드는 list 또는 문자열이어야 합니다."
            )

        cleaned_values: list[str] = []

        for value in values:
            cleaned = WorkflowManager._clean_text(
                value
            )

            if cleaned and cleaned not in cleaned_values:
                cleaned_values.append(cleaned)

        return cleaned_values

    @staticmethod
    def _generate_workflow_id() -> str:
        return f"wf_{uuid4().hex[:16]}"

    @staticmethod
    def _generate_step_id() -> str:
        return f"step_{uuid4().hex[:12]}"

    @staticmethod
    def _utc_now() -> str:
        return datetime.now(timezone.utc).isoformat()


# =========================================================
# 공용 Workflow Manager 인스턴스
# =========================================================

workflow_manager = WorkflowManager()


# =========================================================
# 단독 실행 테스트
# =========================================================

if __name__ == "__main__":
    created = workflow_manager.create_workflow(
        title="식물성 멜라토닌 OEM 견적 조사",
        objective=(
            "식물성 멜라토닌 제품 생산이 가능한 "
            "OEM 제조사의 견적, MOQ, 제조일정을 조사한다."
        ),
        owner_instruction=(
            "제품 관리 지점장에게 제품 출시 업무를 맡기고, "
            "OEM 직원이 제조사 견적과 조건을 조사하게 하라."
        ),
        ceo_agent_id="ceo_001",
        manager_agent_id="manager_product_001",
        worker_agent_ids=[
            "oem_staff_001",
        ],
        project_id="project_melatonin_001",
        requested_by="owner",
        requires_approval=True,
        metadata={
            "business": "I-um Bio",
            "product": "식물성 멜라토닌",
        },
    )

    workflow_id = created["workflow"]["workflow_id"]

    execution = workflow_manager.run_workflow(
        workflow_id
    )

    waiting_workflow = execution["workflow"]

    print("=" * 60)
    print("Workflow Manager 1차 실행")
    print("Workflow ID:", workflow_id)
    print("상태:", waiting_workflow["status"])
    print(
        "승인 상태:",
        waiting_workflow["approval_status"],
    )
    print(
        "진행률:",
        workflow_manager.get_workflow_progress(
            workflow_id
        )["progress_percent"],
    )

    approved = workflow_manager.approve_workflow(
        workflow_id,
        approval_note=(
            "OEM 견적 조사 Workflow 실행을 승인한다."
        ),
        approved_by="owner",
        auto_resume=True,
    )

    final_workflow = approved["workflow"]
    validation = (
        workflow_manager.validate_workflow_store()
    )
    statistics = workflow_manager.get_statistics()

    print("=" * 60)
    print("Workflow Manager 테스트 완료")
    print("최종 상태:", final_workflow["status"])
    print(
        "최종 승인 상태:",
        final_workflow["approval_status"],
    )
    print(
        "완료 단계 수:",
        workflow_manager.get_workflow_progress(
            workflow_id
        )["completed_steps"],
    )
    print("Workflow 구조 정상:", validation["valid"])
    print(
        "전체 Workflow 수:",
        statistics["total_workflows"],
    )
    print("=" * 60)
