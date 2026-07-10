from __future__ import annotations

import hashlib
import re
from typing import Any

from agents import Agent, Runner
from pydantic import BaseModel, Field

from agent_factory import AgentFactory, factory
from agent_registry import AgentRegistry, registry
from company_memory import CompanyMemory, company_memory
from handoff_manager import HandoffManager, handoff_manager


# =========================================================
# 예외
# =========================================================

class ManagerControllerError(Exception):
    """지점장 공통 실행 중 발생하는 기본 예외."""


class ManagerAnalysisError(ManagerControllerError):
    """지점장의 직원 구성 분석에 실패했을 때 발생한다."""


# =========================================================
# 지점장 분석 결과 구조
# =========================================================

class WorkerAnalysis(BaseModel):
    worker_name: str = Field(
        description="영문 또는 영문_형식의 Agent 이름"
    )
    worker_role: str = Field(
        description="한국어 직원 역할명"
    )
    worker_description: str = Field(
        description="직원이 담당할 실무 설명"
    )
    worker_instructions: str = Field(
        description=(
            "직원이 실제 업무를 수행하고 결과를 지점장에게 "
            "보고하도록 하는 완전한 실행 지침"
        )
    )
    assignment: str = Field(
        description="이 직원에게 배정할 구체적인 업무"
    )
    hiring_reason: str = Field(
        description="이 직원이 필요한 이유"
    )


class ManagerStaffingResult(BaseModel):
    analysis_summary: str = Field(
        description="지점장의 업무 분석과 실행계획 요약"
    )
    workers: list[WorkerAnalysis] = Field(
        min_length=1,
        description="업무 수행에 필요한 최소 직원 목록",
    )


# =========================================================
# 지점장 공통 Controller
# =========================================================

class ManagerController:
    """
    모든 지점장이 공통으로 사용하는 자동 운영 엔진.

    CEO에게 업무를 받으면:

    1. 지점장 자신의 역할과 지침 확인
    2. 대표 목표와 CEO 지시 분석
    3. 필요한 직원 역할 자동 결정
    4. Registry에서 기존 직원 검색
    5. 없으면 Agent Factory로 신규 채용
    6. 지점장 → 직원 Handoff 연결
    7. Workflow에 직원 배정
    8. 직원 구성 결과를 Company Memory에 저장

    특정 업종이나 업무 키워드를 코드에 고정하지 않는다.
    홈페이지, 제품, 병원, 학원 등 어떤 지점장도 이 엔진을 사용한다.
    """

    def __init__(
        self,
        *,
        agent_factory: AgentFactory | None = None,
        agent_registry: AgentRegistry | None = None,
        handoff_manager_instance: HandoffManager | None = None,
        company_memory_instance: CompanyMemory | None = None,
    ) -> None:
        self.factory = agent_factory or factory
        self.registry = agent_registry or registry
        self.handoff_manager = (
            handoff_manager_instance or handoff_manager
        )
        self.company_memory = (
            company_memory_instance or company_memory
        )

    # =====================================================
    # 지점장 자동 직원 구성
    # =====================================================

    def organize_workers(
        self,
        workflow_id: str,
    ) -> dict[str, Any]:
        """
        Workflow의 지점장이 업무를 분석하고 필요한 직원을 자동 구성한다.
        """

        # 순환 import 방지를 위해 실행 시점에 불러온다.
        from workflow_manager import workflow_manager

        workflow = workflow_manager.require_workflow(workflow_id)
        manager_agent_id = workflow.get("manager_agent_id")

        if not manager_agent_id:
            raise ManagerControllerError(
                "Workflow에 담당 지점장이 없습니다."
            )

        manager_record = self.registry.get_agent_by_id(
            str(manager_agent_id)
        )

        if manager_record is None:
            raise ManagerControllerError(
                f"Registry에 지점장이 없습니다: {manager_agent_id}"
            )

        analysis = self._analyze_required_workers(
            workflow=workflow,
            manager_record=manager_record,
        )

        worker_ids: list[str] = []
        worker_results: list[dict[str, Any]] = []

        for worker_analysis in analysis.workers:
            worker_id, worker_agent, created = (
                self._get_or_create_worker(
                    manager_agent_id=str(manager_agent_id),
                    analysis=worker_analysis,
                )
            )

            self._connect_worker(
                manager_agent_id=str(manager_agent_id),
                worker_agent_id=worker_id,
                assignment=worker_analysis.assignment,
            )

            worker_ids.append(worker_id)
            worker_results.append(
                {
                    "agent_id": worker_id,
                    "name": worker_agent.name,
                    "role": worker_analysis.worker_role,
                    "assignment": worker_analysis.assignment,
                    "created": created,
                }
            )

        workflow_manager.assign_workers(
            workflow_id=workflow_id,
            worker_agent_ids=worker_ids,
        )

        self.company_memory.remember_decision(
            title=f"지점장 자동 직원 구성: {workflow['title']}",
            content=(
                f"지점장: {manager_record.get('role')}\n"
                f"분석: {analysis.analysis_summary}\n"
                f"구성 직원: "
                f"{', '.join(worker['role'] for worker in worker_results)}"
            ),
            source="manager",
            source_agent_id=str(manager_agent_id),
            project_id=workflow.get("project_id"),
            importance=5,
            tags=[
                "manager",
                "자동직원구성",
                workflow_id,
            ],
        )

        return {
            "workflow_id": workflow_id,
            "manager_agent_id": str(manager_agent_id),
            "manager_role": manager_record.get("role"),
            "analysis_summary": analysis.analysis_summary,
            "worker_agent_ids": worker_ids,
            "workers": worker_results,
        }

    # =====================================================
    # OpenAI 기반 직원 구성 분석
    # =====================================================

    def _analyze_required_workers(
        self,
        *,
        workflow: dict[str, Any],
        manager_record: dict[str, Any],
    ) -> ManagerStaffingResult:
        manager_role = str(
            manager_record.get("role", "지점장")
        )
        manager_instructions = str(
            manager_record.get("instructions", "")
        )

        analysis_agent = Agent(
            name="Business_AI_OS_Manager_Staffing_Analyzer",
            instructions=f"""
너는 Business AI OS의 {manager_role}이다.

너의 기존 운영 지침:
{manager_instructions}

CEO에게 받은 업무를 분석하여 실제 업무를 수행할 직원 구성을 결정하라.

반드시 지켜야 할 원칙:

1. 지점장은 직접 실무를 대신 수행하지 않는다.
2. 기존 회사 자산과 기존 직원을 우선 활용한다.
3. 업무 완수에 꼭 필요한 최소 직원만 결정한다.
4. 특정 업종이나 사전 정의된 직원 목록에 의존하지 않는다.
5. 대표 목표와 업무 내용의 의미를 분석한다.
6. worker_name은 Python Agent 이름으로 사용할 수 있는 영문 또는
   영문과 밑줄 형식으로 작성한다.
7. worker_role은 구체적인 한국어 직원 역할명으로 작성한다.
8. worker_instructions에는 다음 책임을 반드시 포함한다.
   - 기존 자료 우선 검색
   - 배정 업무 실제 수행
   - 근거와 결과 정리
   - 도구나 계정 권한 필요 시 지점장에게 보고
   - 권한 연결 후 중단 업무 재개
   - 완료 결과를 지점장에게 보고
9. 대표에게 직접 보고하도록 지시하지 않는다.
10. 직원 채용 자체가 목적이 아니라 업무 완료가 목적이다.
""".strip(),
            output_type=ManagerStaffingResult,
        )

        prompt = f"""
[지점장 업무 분석 및 직원 구성 요청]

프로젝트:
{workflow.get('title')}

목표:
{workflow.get('objective')}

대표 지시:
{workflow.get('owner_instruction')}

담당 지점장:
{manager_role}

이 업무를 실제로 완수할 최소 직원 구성을 결정하라.
""".strip()

        try:
            result = Runner.run_sync(
                starting_agent=analysis_agent,
                input=prompt,
            )
        except Exception as exc:
            raise ManagerAnalysisError(
                f"지점장 직원 구성 분석에 실패했습니다: {exc}"
            ) from exc

        final_output = result.final_output

        if isinstance(final_output, ManagerStaffingResult):
            analysis = final_output
        else:
            try:
                analysis = ManagerStaffingResult.model_validate(
                    final_output
                )
            except Exception as exc:
                raise ManagerAnalysisError(
                    "지점장 분석 결과 형식이 올바르지 않습니다."
                ) from exc

        if not analysis.workers:
            raise ManagerAnalysisError(
                "지점장이 필요한 직원을 결정하지 못했습니다."
            )

        return analysis

    # =====================================================
    # 직원 검색 및 생성
    # =====================================================

    def _get_or_create_worker(
        self,
        *,
        manager_agent_id: str,
        analysis: WorkerAnalysis,
    ) -> tuple[str, Any, bool]:
        role = self._clean(analysis.worker_role)

        if not role:
            raise ManagerAnalysisError(
                "직원 역할이 비어 있습니다."
            )

        existing = self.registry.find_agent(
            role=role,
            level="worker",
            parent_agent_id=manager_agent_id,
            active_only=True,
        )

        if existing is not None:
            worker_id = str(existing["agent_id"])
            return (
                worker_id,
                self.factory.load_agent(worker_id),
                False,
            )

        worker_id = self._make_worker_agent_id(
            manager_agent_id=manager_agent_id,
            role=role,
        )

        worker_agent = self.factory.get_or_create_agent(
            agent_id=worker_id,
            name=self._safe_agent_name(
                analysis.worker_name
            ),
            role=role,
            level="worker",
            parent_agent_id=manager_agent_id,
            instructions=analysis.worker_instructions.strip(),
            description=self._clean(
                analysis.worker_description
            ),
            created_reason=(
                "지점장이 업무를 분석해 자동 채용"
            ),
        )

        saved = self.registry.find_agent(
            role=role,
            level="worker",
            parent_agent_id=manager_agent_id,
            active_only=True,
        )

        saved_id = (
            str(saved["agent_id"])
            if saved is not None
            else worker_id
        )

        return saved_id, worker_agent, True

    # =====================================================
    # 지점장 → 직원 Handoff
    # =====================================================

    def _connect_worker(
        self,
        *,
        manager_agent_id: str,
        worker_agent_id: str,
        assignment: str,
    ) -> None:
        self.handoff_manager.register_handoff(
            source_agent_id=manager_agent_id,
            target_agent_id=worker_agent_id,
            description=(
                self._clean(assignment)
                or "지점장이 직원에게 실무를 위임한다."
            ),
            created_reason=(
                "지점장 자동 업무 분석 및 직원 위임"
            ),
        )

        self.handoff_manager.sync_agent_runtime(
            manager_agent_id
        )

    # =====================================================
    # 기존 관리 기능
    # =====================================================

    def assign_workers(
        self,
        workflow_id: str,
        worker_agent_ids: list[str],
    ) -> dict[str, Any]:
        from workflow_manager import workflow_manager

        return workflow_manager.assign_workers(
            workflow_id=workflow_id,
            worker_agent_ids=worker_agent_ids,
        )

    def review(
        self,
        workflow_id: str,
    ) -> dict[str, Any]:
        from workflow_manager import workflow_manager

        workflow = workflow_manager.require_workflow(
            workflow_id
        )

        report = {
            "workflow_id": workflow_id,
            "title": workflow["title"],
            "manager": workflow["manager_agent_id"],
            "workers": workflow["worker_agent_ids"],
            "status": workflow["status"],
            "progress": (
                workflow_manager.get_workflow_progress(
                    workflow_id
                )
            ),
        }

        self.company_memory.remember_agent_result(
            title=f"지점장 검토: {workflow['title']}",
            content=(
                "지점장이 직원 구성과 업무 진행 결과를 "
                "검토하고 AI CEO에게 보고했다."
            ),
            source_agent_id=str(
                workflow["manager_agent_id"]
            ),
            project_id=workflow.get("project_id"),
            related_agent_ids=workflow["worker_agent_ids"],
            importance=4,
            tags=[
                "manager",
                "review",
                workflow_id,
            ],
        )

        return report

    def handoff_to_worker(
        self,
        manager_agent_id: str,
        worker_agent_id: str,
        description: str,
    ) -> dict[str, Any]:
        handoff = self.handoff_manager.get_handoff(
            source_agent_id=manager_agent_id,
            target_agent_id=worker_agent_id,
        )

        if handoff is None:
            return self.handoff_manager.register_handoff(
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

    # =====================================================
    # ID 및 문자열 처리
    # =====================================================

    @staticmethod
    def _make_worker_agent_id(
        *,
        manager_agent_id: str,
        role: str,
    ) -> str:
        digest = hashlib.sha1(
            f"{manager_agent_id}:{role}".encode("utf-8")
        ).hexdigest()[:10]

        return f"worker_{digest}"

    @staticmethod
    def _safe_agent_name(value: str) -> str:
        cleaned = re.sub(
            r"[^A-Za-z0-9_]+",
            "_",
            str(value).strip(),
        ).strip("_")

        if not cleaned:
            return "General_Worker"

        if cleaned[0].isdigit():
            cleaned = f"Worker_{cleaned}"

        return cleaned

    @staticmethod
    def _clean(value: Any) -> str:
        if value is None:
            return ""

        return " ".join(
            str(value).strip().split()
        )


# =========================================================
# 공용 Controller
# =========================================================

manager_controller = ManagerController()


# =========================================================
# 단독 실행 안내
# =========================================================

if __name__ == "__main__":
    print("=" * 60)
    print("Manager Controller 공통 자동 실행 엔진")
    print("기능:")
    print("1. 지점장 업무 자동 분석")
    print("2. 필요한 직원 자동 결정")
    print("3. 기존 직원 검색")
    print("4. 없으면 신규 직원 자동 채용")
    print("5. 지점장 → 직원 Handoff")
    print("6. Workflow 직원 배정")
    print("=" * 60)
    print(
        "실제 테스트는 Workflow ID를 사용해 "
        "manager_controller.organize_workers(workflow_id)로 실행합니다."
    )
    print("=" * 60)
