from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Any

from agents import Agent, Runner
from pydantic import BaseModel, Field

from agent_factory import AgentFactory, factory
from agent_registry import AgentRegistry, registry
from company_memory import CompanyMemory, company_memory
from handoff_manager import HandoffManager, handoff_manager
from workflow_manager import WorkflowManager, workflow_manager


# =========================================================
# 예외
# =========================================================

class CEOControllerError(Exception):
    """CEO Controller 처리 중 발생하는 기본 예외."""


class CEORoutingError(CEOControllerError):
    """대표 지시 분석 또는 지점장 결정에 실패했을 때 발생한다."""


# =========================================================
# AI CEO 분석 결과 구조
# =========================================================

class ManagerAnalysis(BaseModel):
    """
    AI CEO가 대표 지시를 분석한 뒤 결정하는 지점장 한 명의 정보.
    """

    business_type: str = Field(
        description="업무 분야를 짧은 영문 식별자로 작성한다."
    )
    manager_name: str = Field(
        description="영문 또는 영문_형식의 Agent 이름"
    )
    manager_role: str = Field(
        description="한국어 지점장 역할명"
    )
    manager_description: str = Field(
        description="지점장이 총괄할 업무 설명"
    )
    manager_instructions: str = Field(
        description=(
            "지점장이 업무를 분석하고 필요한 직원을 검색·채용·지시·검토하도록 "
            "하는 완전한 운영 지침"
        )
    )
    delegation_reason: str = Field(
        description="이 지점장이 필요한 이유"
    )


class CEOAnalysisResult(BaseModel):
    """
    대표 지시 하나에 대해 AI CEO가 결정한 전체 조직 분석 결과.
    """

    summary: str = Field(
        description="대표 지시와 목표에 대한 CEO 분석 요약"
    )
    primary_business_type: str = Field(
        description="대표 업무 분야를 짧은 영문 식별자로 작성한다."
    )
    managers: list[ManagerAnalysis] = Field(
        min_length=1,
        description=(
            "필요한 지점장 목록. 한 분야면 한 명, 복합 업무면 여러 명을 지정한다."
        ),
    )


# =========================================================
# 내부 조직 정의
# =========================================================

@dataclass(frozen=True)
class ManagerDefinition:
    agent_id: str
    name: str
    role: str
    description: str
    instructions: str
    business_type: str
    delegation_reason: str


# =========================================================
# CEO Controller
# =========================================================

class CEOController:
    """
    Business AI OS의 AI CEO 실행 컨트롤러.

    운영 구조:

    대표 지시
    → AI CEO가 OpenAI로 업무 분석
    → 필요한 지점장 결정
    → Registry에서 기존 지점장 검색
    → 없으면 Agent Factory로 지점장 임명
    → CEO에서 지점장으로 Handoff 연결
    → 대표 업무를 주 담당 지점장 Workflow로 전달

    중요 원칙:
    - CEO는 직원을 직접 선발하지 않는다.
    - 직원 검색·채용·업무 배정은 지점장의 책임이다.
    - 제품, 홈페이지, 학원, 병원 등 업무별 고정 키워드를 사용하지 않는다.
    - 새로운 종류의 업무도 AI CEO가 의미를 분석해 지점장을 결정한다.
    """

    CEO_AGENT_ID = "ceo_001"

    def __init__(
        self,
        *,
        agent_factory: AgentFactory | None = None,
        agent_registry: AgentRegistry | None = None,
        handoff_manager_instance: HandoffManager | None = None,
        workflow_manager_instance: WorkflowManager | None = None,
        company_memory_instance: CompanyMemory | None = None,
    ) -> None:
        self.factory = agent_factory or factory
        self.registry = agent_registry or registry
        self.handoff_manager = handoff_manager_instance or handoff_manager
        self.workflow_manager = workflow_manager_instance or workflow_manager
        self.company_memory = company_memory_instance or company_memory

    # =====================================================
    # 대표 지시 시작
    # =====================================================

    def start(
        self,
        *,
        title: str,
        objective: str,
        owner_instruction: str,
        project_id: str | None = None,
        requires_approval: bool = True,
    ) -> dict[str, Any]:
        title = self._clean(title)
        objective = self._clean(objective) or title
        owner_instruction = self._clean(owner_instruction) or objective

        if not title:
            raise CEOControllerError(
                "프로젝트 제목은 비어 있을 수 없습니다."
            )

        self._ensure_ceo_agent()

        from development_engine import development_engine
        if development_engine.is_development_instruction(owner_instruction):
            created = self.workflow_manager.create_workflow(
                title=title,
                objective=objective,
                owner_instruction=owner_instruction,
                ceo_agent_id=self.CEO_AGENT_ID,
                manager_agent_id=None,
                worker_agent_ids=[],
                project_id=project_id,
                requested_by="owner",
                requires_approval=requires_approval,
                metadata={
                    "business_type": "development_engine",
                    "development_mode": True,
                    "execution_engine": "development_engine",
                    "worker_selection_owner": "development_engine",
                },
            )
            workflow_id = created["workflow"]["workflow_id"]
            execution = self.workflow_manager.run_workflow(workflow_id)
            workflow = execution["workflow"]
            return {
                "workflow_id": workflow_id,
                "status": workflow["status"],
                "approval_status": workflow["approval_status"],
                "business_type": "development_engine",
                "analysis_summary": (
                    "개발 업무로 판정하여 일반 지점장/Worker를 우회하고 "
                    "Development Engine을 기본 실행 엔진으로 호출했습니다."
                ),
                "manager": {
                    "agent_id": "development_engine",
                    "name": "Development_Engine",
                    "role": "AI 개발 실행 엔진",
                },
                "managers": [],
                "workers": ["development_engine"],
                "worker_selection_owner": "development_engine",
            }

        analysis = self._analyze_owner_instruction(
            title=title,
            objective=objective,
            owner_instruction=owner_instruction,
        )

        manager_definitions = [
            self._to_manager_definition(manager)
            for manager in analysis.managers
        ]

        manager_agents: list[Any] = []

        for definition in manager_definitions:
            manager_agent = self._get_or_create_manager(definition)
            manager_agents.append(manager_agent)

            self._connect_manager(
                manager_agent_id=self._resolve_saved_manager_id(
                    definition
                ),
                delegation_reason=definition.delegation_reason,
            )

        if not manager_definitions:
            raise CEORoutingError(
                "AI CEO가 담당 지점장을 결정하지 못했습니다."
            )

        primary_definition = manager_definitions[0]
        primary_manager_id = self._resolve_saved_manager_id(
            primary_definition
        )
        primary_manager_agent = manager_agents[0]

        # CEO는 직원을 직접 구성하지 않는다.
        # worker_agent_ids는 빈 목록으로 전달하고,
        # 실제 직원 구성은 지점장 실행 단계에서 담당한다.
        created = self.workflow_manager.create_workflow(
            title=title,
            objective=objective,
            owner_instruction=owner_instruction,
            ceo_agent_id=self.CEO_AGENT_ID,
            manager_agent_id=primary_manager_id,
            worker_agent_ids=[],
            project_id=project_id,
            requested_by="owner",
            requires_approval=requires_approval,
            metadata={
                "business_type": analysis.primary_business_type,
                "ceo_analysis_summary": analysis.summary,
                "organization_created_automatically": True,
                "primary_manager_agent_id": primary_manager_id,
                "required_manager_agent_ids": [
                    self._resolve_saved_manager_id(definition)
                    for definition in manager_definitions
                ],
                "worker_selection_owner": "manager",
            },
        )

        workflow_id = created["workflow"]["workflow_id"]
        execution = self.workflow_manager.run_workflow(workflow_id)
        workflow = execution["workflow"]

        self.company_memory.remember_decision(
            title=f"AI CEO 자동 지점장 구성: {title}",
            content=(
                f"CEO 분석: {analysis.summary}\n"
                f"주 담당 지점장: {primary_definition.role}\n"
                f"구성 지점장: "
                f"{', '.join(definition.role for definition in manager_definitions)}\n"
                f"직원 구성은 각 지점장이 담당한다."
            ),
            source="ai_ceo",
            source_agent_id=self.CEO_AGENT_ID,
            project_id=project_id,
            importance=5,
            tags=[
                "CEO",
                "자동업무분류",
                "자동지점장구성",
                analysis.primary_business_type,
                workflow_id,
            ],
        )

        manager_results = [
            {
                "agent_id": self._resolve_saved_manager_id(definition),
                "name": agent.name,
                "role": definition.role,
                "business_type": definition.business_type,
                "delegation_reason": definition.delegation_reason,
            }
            for definition, agent in zip(
                manager_definitions,
                manager_agents,
            )
        ]

        return {
            "workflow_id": workflow_id,
            "status": workflow["status"],
            "approval_status": workflow["approval_status"],
            "business_type": analysis.primary_business_type,
            "analysis_summary": analysis.summary,
            "manager": {
                "agent_id": primary_manager_id,
                "name": primary_manager_agent.name,
                "role": primary_definition.role,
            },
            "managers": manager_results,
            "workers": [],
            "worker_selection_owner": "manager",
        }

    # =====================================================
    # 승인 / 반려 / 보고
    # =====================================================

    def approve(
        self,
        workflow_id: str,
        *,
        approval_note: str = "대표 승인",
    ) -> dict[str, Any]:
        return self.workflow_manager.approve_workflow(
            workflow_id,
            approval_note=approval_note,
            approved_by="owner",
            auto_resume=True,
        )

    def reject(
        self,
        workflow_id: str,
        reason: str,
    ) -> dict[str, Any]:
        return self.workflow_manager.reject_workflow(
            workflow_id,
            rejection_reason=self._clean(reason) or "대표 반려",
            rejected_by="owner",
        )

    def report(
        self,
        workflow_id: str,
    ) -> dict[str, Any]:
        workflow = self.workflow_manager.require_workflow(workflow_id)

        return {
            "workflow": workflow,
            "progress": self.workflow_manager.get_workflow_progress(
                workflow_id
            ),
            "context": self.company_memory.build_context_text(
                project_id=workflow.get("project_id"),
                limit=30,
            ),
        }

    # =====================================================
    # AI CEO 자동 업무 분석
    # =====================================================

    def _analyze_owner_instruction(
        self,
        *,
        title: str,
        objective: str,
        owner_instruction: str,
    ) -> CEOAnalysisResult:
        """
        키워드 규칙이 아니라 OpenAI Agent가 대표 지시의 의미를 분석한다.
        """

        analysis_agent = Agent(
            name="Business_AI_OS_CEO_Analyzer",
            instructions="""
너는 Business AI OS의 AI CEO이다.

대표의 지시와 목표를 분석하여 어떤 지점장이 필요한지 결정하라.

반드시 지켜야 할 원칙:

1. CEO는 대표의 목표를 분석하고 지점장만 임명한다.
2. CEO가 실무 직원을 직접 선택하거나 채용하면 안 된다.
3. 직원 구성은 각 지점장이 업무를 분석한 뒤 결정한다.
4. 기존 조직으로 해결 가능한 일반적인 역할명을 우선 사용한다.
5. 업무가 복합적이면 필요한 지점장을 여러 명 결정할 수 있다.
6. 첫 번째 지점장은 전체 Workflow의 주 담당 지점장이어야 한다.
7. 제품, 홈페이지, 병원, 학원, 정부지원, 마케팅 등
   미리 정해진 키워드 표에 의존하지 말고 지시의 의미로 판단한다.
8. manager_instructions에는 다음 책임을 반드시 포함한다.
   - 업무 분석
   - 세부 실행계획 수립
   - 기존 회사 자산 우선 검색
   - 기존 직원 검색
   - 필요한 경우에만 신규 직원 채용
   - 직원 업무 배정
   - 직원 결과 검토
   - 권한 필요 시 CEO에게 상향 보고
   - 권한 연결 후 업무 재개
   - 완료 후 CEO 보고
9. manager_name은 Python Agent 이름으로 사용 가능한 영문 또는
   영문과 밑줄 형식으로 작성한다.
10. business_type은 짧은 영문 snake_case로 작성한다.
11. 대표가 요구한 결과물의 성격을 정확히 구분한다.
    - 소개, 홍보, 회사 안내 목적이면 일반 홈페이지 또는 랜딩페이지다.
    - 업무 지시, 승인, 반려, 진행 상태, 직원 관리, Workflow 관리,
      보고서 확인이 목적이면 운영 대시보드 또는 관리자 시스템이다.
12. 운영 시스템을 일반 소개 홈페이지로 축소해서 해석하지 않는다.
13. manager_instructions에 다음 내용을 구체적으로 포함한다.
    - 최종 결과물의 종류
    - 실제 사용 주체
    - 반드시 구현해야 할 핵심 기능
    - 필요한 화면과 데이터
    - 완료 판단 기준
14. 대표 지시에서 요구한 기능을 지점장에게 전달할 때 누락하거나
    단순화하지 않는다.
""".strip(),
            output_type=CEOAnalysisResult,
        )

        prompt = f"""
[대표 지시 분석 요청]

프로젝트 제목:
{title}

목표:
{objective}

대표 지시:
{owner_instruction}

위 업무를 수행하기 위해 필요한 지점장을 결정하라.
CEO는 지점장까지만 결정하고 직원은 결정하지 않는다.

대표 지시를 단순한 업종명이나 홈페이지 제작 요청으로 축소하지 마라.

반드시 다음을 먼저 판단하라.

1. 실제 사용자는 누구인가
2. 최종 결과물은 소개 페이지인가, 운영 시스템인가
3. 사용자가 실제로 수행해야 하는 핵심 기능은 무엇인가
4. 어떤 화면, 데이터, 승인 흐름이 필요한가
5. 언제 업무가 완료되었다고 판단할 수 있는가

판단한 결과를 manager_description, manager_instructions,
delegation_reason에 구체적으로 반영하라.

운영 홈페이지가 다음 기능을 요구하는 경우에는 일반 랜딩페이지가 아니라
실제로 사용할 수 있는 운영 대시보드 또는 관리자 시스템으로 정의하라.

- 대표 업무 지시
- 승인 및 반려
- Workflow 진행 상태
- 지점장과 직원 현황
- 권한 요청
- 운영보고
- 결과물 및 보고서 확인
""".strip()

        try:
            result = Runner.run_sync(
                starting_agent=analysis_agent,
                input=prompt,
            )
        except Exception as exc:
            raise CEORoutingError(
                f"AI CEO 업무 분석에 실패했습니다: {exc}"
            ) from exc

        final_output = result.final_output

        if isinstance(final_output, CEOAnalysisResult):
            analysis = final_output
        else:
            try:
                analysis = CEOAnalysisResult.model_validate(
                    final_output
                )
            except Exception as exc:
                raise CEORoutingError(
                    "AI CEO 분석 결과 형식이 올바르지 않습니다."
                ) from exc

        if not analysis.managers:
            raise CEORoutingError(
                "AI CEO가 필요한 지점장을 결정하지 못했습니다."
            )

        return analysis

    # =====================================================
    # 분석 결과 → 지점장 정의
    # =====================================================

    def _to_manager_definition(
        self,
        analysis: ManagerAnalysis,
    ) -> ManagerDefinition:
        role = self._clean(analysis.manager_role)
        name = self._safe_agent_name(analysis.manager_name)

        if not role:
            raise CEORoutingError(
                "AI CEO 분석 결과의 지점장 역할이 비어 있습니다."
            )

        return ManagerDefinition(
            agent_id=self._make_manager_agent_id(
                business_type=analysis.business_type,
                role=role,
            ),
            name=name,
            role=role,
            description=self._clean(
                analysis.manager_description
            ),
            instructions=analysis.manager_instructions.strip(),
            business_type=self._safe_business_type(
                analysis.business_type
            ),
            delegation_reason=self._clean(
                analysis.delegation_reason
            ),
        )

    # =====================================================
    # CEO Agent 보장
    # =====================================================

    def _ensure_ceo_agent(self) -> None:
        existing = self.registry.get_agent_by_id(
            self.CEO_AGENT_ID
        )

        if existing is not None:
            return

        self.factory.get_or_create_agent(
            agent_id=self.CEO_AGENT_ID,
            name="Business_AI_OS_CEO",
            role="AI CEO",
            level="ceo",
            parent_agent_id=None,
            instructions="""
너는 Business AI OS의 AI CEO이다.

1. 대표의 목표와 지시를 분석한다.
2. 회사헌법, 운영원칙과 기존 자산을 먼저 확인한다.
3. 업무를 담당할 기존 지점장을 검색한다.
4. 적합한 지점장이 없을 때만 새 지점장을 임명한다.
5. 지점장에게 목표와 책임을 위임한다.
6. 직원을 직접 선발하거나 실무를 직접 수행하지 않는다.
7. 직원 구성과 실무 관리는 지점장에게 맡긴다.
8. 사람이 해야 하는 권한이나 승인은 대표에게 보고한다.
9. 대표 처리 후 중단된 업무를 지점장이 재개하도록 한다.
10. 지점장 결과를 최종 검토하고 대표에게 보고한다.
""".strip(),
            description="Business AI OS 전체 운영을 총괄한다.",
            created_reason="CEO Controller 자동 생성",
        )

    # =====================================================
    # 지점장 검색 및 생성
    # =====================================================

    def _get_or_create_manager(
        self,
        definition: ManagerDefinition,
    ) -> Any:
        existing = self.registry.find_agent(
            role=definition.role,
            level="manager",
            parent_agent_id=self.CEO_AGENT_ID,
            active_only=True,
        )

        if existing is not None:
            return self.factory.load_agent(
                str(existing["agent_id"])
            )

        return self.factory.get_or_create_agent(
            agent_id=definition.agent_id,
            name=definition.name,
            role=definition.role,
            level="manager",
            parent_agent_id=self.CEO_AGENT_ID,
            instructions=definition.instructions,
            description=definition.description,
            created_reason=(
                "AI CEO가 대표 지시를 분석해 자동 임명"
            ),
        )

    def _resolve_saved_manager_id(
        self,
        definition: ManagerDefinition,
    ) -> str:
        """
        같은 역할의 기존 지점장이 있으면 실제 저장된 ID를 사용한다.
        """

        existing = self.registry.find_agent(
            role=definition.role,
            level="manager",
            parent_agent_id=self.CEO_AGENT_ID,
            active_only=True,
        )

        if existing is not None:
            return str(existing["agent_id"])

        return definition.agent_id

    # =====================================================
    # CEO → 지점장 Handoff
    # =====================================================

    def _connect_manager(
        self,
        *,
        manager_agent_id: str,
        delegation_reason: str,
    ) -> None:
        self.handoff_manager.register_handoff(
            source_agent_id=self.CEO_AGENT_ID,
            target_agent_id=manager_agent_id,
            description=(
                delegation_reason
                or "대표 업무를 담당 지점장에게 위임한다."
            ),
            created_reason=(
                "AI CEO 자동 업무 분석 및 지점장 위임"
            ),
        )

        self.handoff_manager.rebuild_organization(
            self.CEO_AGENT_ID
        )

    # =====================================================
    # ID 및 문자열 처리
    # =====================================================

    @staticmethod
    def _make_manager_agent_id(
        *,
        business_type: str,
        role: str,
    ) -> str:
        safe_type = CEOController._safe_business_type(
            business_type
        )
        digest = hashlib.sha1(
            role.encode("utf-8")
        ).hexdigest()[:8]

        return f"manager_{safe_type}_{digest}"

    @staticmethod
    def _safe_business_type(value: str) -> str:
        cleaned = re.sub(
            r"[^a-z0-9_]+",
            "_",
            str(value).strip().lower(),
        ).strip("_")

        return cleaned or "general_operations"

    @staticmethod
    def _safe_agent_name(value: str) -> str:
        cleaned = re.sub(
            r"[^A-Za-z0-9_]+",
            "_",
            str(value).strip(),
        ).strip("_")

        if not cleaned:
            return "General_Manager"

        if cleaned[0].isdigit():
            cleaned = f"Manager_{cleaned}"

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

ceo_controller = CEOController()


# =========================================================
# 완성본 실행 테스트
# =========================================================

if __name__ == "__main__":
    result = ceo_controller.start(
        title="Business AI OS 운영 홈페이지 제작",
        objective=(
            "대표가 업무를 지시하고 승인·반려하며 "
            "진행 상태를 확인할 수 있는 홈페이지를 만든다."
        ),
        owner_instruction=(
            "Business AI OS 운영 홈페이지를 만들어라."
        ),
        project_id="project_business_ai_os_web_001",
        requires_approval=True,
    )

    print("=" * 60)
    print("CEO Controller 자동 업무 분류 테스트")
    print("Workflow ID:", result["workflow_id"])
    print("업무 유형:", result["business_type"])
    print("CEO 분석:", result["analysis_summary"])
    print("주 담당 지점장:", result["manager"]["role"])
    print(
        "전체 지점장:",
        [manager["role"] for manager in result["managers"]],
    )
    print("직원 구성 담당:", result["worker_selection_owner"])
    print("상태:", result["status"])
    print("승인 상태:", result["approval_status"])

    approved = ceo_controller.approve(
        result["workflow_id"],
        approval_note="홈페이지 제작 업무를 승인한다.",
    )

    print("최종 상태:", approved["workflow"]["status"])
    print("=" * 60)
