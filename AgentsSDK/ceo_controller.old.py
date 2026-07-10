from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from agent_factory import AgentFactory, factory
from agent_registry import AgentRegistry, registry
from company_memory import CompanyMemory, company_memory
from handoff_manager import HandoffManager, handoff_manager
from workflow_manager import WorkflowManager, workflow_manager


class CEOControllerError(Exception):
    pass


class CEORoutingError(CEOControllerError):
    pass


@dataclass(frozen=True)
class ManagerDefinition:
    agent_id: str
    name: str
    role: str
    description: str
    instructions: str


@dataclass(frozen=True)
class WorkerDefinition:
    agent_id: str
    name: str
    role: str
    description: str
    instructions: str


class CEOController:
    """
    대표 지시를 분석하고 필요한 지점장과 직원을 자동 검색·생성한 뒤
    Handoff와 Workflow를 시작하는 실사용 CEO Controller.
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
            raise CEOControllerError("프로젝트 제목은 비어 있을 수 없습니다.")

        self._ensure_ceo_agent()

        business_type = self._analyze_business_type(
            title=title,
            objective=objective,
            owner_instruction=owner_instruction,
        )

        manager_def = self._select_manager(business_type)
        manager_agent = self._get_or_create_manager(manager_def)

        worker_defs = self._select_workers(
            business_type=business_type,
            title=title,
            objective=objective,
            owner_instruction=owner_instruction,
        )

        worker_agents = [
            self._get_or_create_worker(
                definition=worker_def,
                manager_agent_id=manager_def.agent_id,
            )
            for worker_def in worker_defs
        ]

        self._connect_organization(
            manager_agent_id=manager_def.agent_id,
            worker_agent_ids=[worker.agent_id for worker in worker_defs],
        )

        created = self.workflow_manager.create_workflow(
            title=title,
            objective=objective,
            owner_instruction=owner_instruction,
            ceo_agent_id=self.CEO_AGENT_ID,
            manager_agent_id=manager_def.agent_id,
            worker_agent_ids=[worker.agent_id for worker in worker_defs],
            project_id=project_id,
            requested_by="owner",
            requires_approval=requires_approval,
            metadata={
                "business_type": business_type,
                "organization_created_automatically": True,
            },
        )

        workflow_id = created["workflow"]["workflow_id"]
        execution = self.workflow_manager.run_workflow(workflow_id)
        workflow = execution["workflow"]

        self.company_memory.remember_decision(
            title=f"자동 조직 구성: {title}",
            content=(
                f"AI CEO가 업무를 {business_type}으로 판단하고 "
                f"{manager_def.role} 및 "
                f"{', '.join(worker.role for worker in worker_defs)}을 구성했다."
            ),
            source="ai_ceo",
            source_agent_id=self.CEO_AGENT_ID,
            project_id=project_id,
            importance=5,
            tags=["CEO", "자동조직구성", business_type, workflow_id],
        )

        return {
            "workflow_id": workflow_id,
            "status": workflow["status"],
            "approval_status": workflow["approval_status"],
            "business_type": business_type,
            "manager": {
                "agent_id": manager_def.agent_id,
                "name": manager_agent.name,
                "role": manager_def.role,
            },
            "workers": [
                {
                    "agent_id": definition.agent_id,
                    "name": agent.name,
                    "role": definition.role,
                }
                for definition, agent in zip(worker_defs, worker_agents)
            ],
        }

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

    def report(self, workflow_id: str) -> dict[str, Any]:
        workflow = self.workflow_manager.require_workflow(workflow_id)
        return {
            "workflow": workflow,
            "progress": self.workflow_manager.get_workflow_progress(workflow_id),
            "context": self.company_memory.build_context_text(
                project_id=workflow.get("project_id"),
                limit=30,
            ),
        }

    def _analyze_business_type(
        self,
        *,
        title: str,
        objective: str,
        owner_instruction: str,
    ) -> str:
        combined = f"{title} {objective} {owner_instruction}".lower()

        product_keywords = (
            "제품", "상품", "출시", "멜라토닌", "건강기능식품",
            "건기식", "oem", "제조", "원료", "상세페이지", "판매",
        )

        if any(keyword in combined for keyword in product_keywords):
            return "product_launch"

        raise CEORoutingError(
            "현재 완성 버전은 제품 출시 업무를 지원합니다."
        )

    def _select_manager(self, business_type: str) -> ManagerDefinition:
        if business_type != "product_launch":
            raise CEORoutingError(f"지원하지 않는 업무 유형: {business_type}")

        return ManagerDefinition(
            agent_id="manager_product_001",
            name="Product_Manager",
            role="제품 관리 지점장",
            description="제품 출시 업무 전체를 총괄한다.",
            instructions="""너는 Business AI OS의 제품 관리 지점장이다.

AI CEO에게 제품 출시 목표를 받으면 다음 순서로 운영한다.

1. 대표 목표와 CEO 지시를 분석한다.
2. 기존 회사 자료와 기존 Agent를 먼저 확인한다.
3. 제품 출시 업무를 세부 작업으로 나눈다.
4. 필요한 기존 직원을 검색한다.
5. 기존 직원이 없을 때만 신규 직원을 채용한다.
6. 직원에게 실무를 위임한다.
7. 직원이 도구 또는 계정 권한을 요청하면 검토한다.
8. 사람만 처리할 수 있는 권한이면 CEO에게 상향 보고한다.
9. 권한 연결 후 중단된 업무를 재개시킨다.
10. 직원 결과를 검토하고 CEO에게 보고한다.

직접 실무를 대신 수행하지 않는다.""",
        )

    def _select_workers(
        self,
        *,
        business_type: str,
        title: str,
        objective: str,
        owner_instruction: str,
    ) -> list[WorkerDefinition]:
        if business_type != "product_launch":
            raise CEORoutingError(f"지원하지 않는 업무 유형: {business_type}")

        combined = f"{title} {objective} {owner_instruction}".lower()
        workers: list[WorkerDefinition] = []

        workers.append(
            WorkerDefinition(
                agent_id="oem_staff_001",
                name="OEM_Staff",
                role="OEM 담당 직원",
                description="OEM 제조사, 견적, MOQ, 제조일정 조사를 담당한다.",
                instructions="""너는 Business AI OS의 OEM 담당 직원이다.

1. 기존 OEM 자료를 먼저 검색한다.
2. 적합한 제조사를 조사한다.
3. 제조 가능 여부, MOQ, 견적, 일정, 인증 조건을 정리한다.
4. 업무 중 도구 연결이나 계정 권한이 필요하면 지점장에게 보고한다.
5. 권한 연결 후 중단된 업무를 자동 재개한다.
6. 결과를 제품 관리 지점장에게 보고한다.

대표에게 직접 보고하지 않는다.""",
            )
        )

        workers.append(
            WorkerDefinition(
                agent_id="market_research_staff_001",
                name="Market_Research_Staff",
                role="시장조사 직원",
                description="시장, 경쟁제품, 가격과 판매 포인트 조사를 담당한다.",
                instructions="""너는 Business AI OS의 시장조사 직원이다.

1. 시장과 고객 수요를 조사한다.
2. 경쟁제품의 가격, 구성, 후기와 판매 포인트를 분석한다.
3. 제품 차별화 방향을 제안한다.
4. 근거와 불확실한 부분을 구분한다.
5. 결과를 제품 관리 지점장에게 보고한다.""",
            )
        )

        if "멜라토닌" in combined:
            workers.append(
                WorkerDefinition(
                    agent_id="regulatory_staff_001",
                    name="Regulatory_Staff",
                    role="인허가·표시 검토 직원",
                    description="제품 유형, 원료, 표시·광고 및 인허가를 검토한다.",
                    instructions="""너는 Business AI OS의 인허가·표시 검토 직원이다.

1. 제품 유형과 적용 규정을 검토한다.
2. 원료 사용 가능성과 표시 기준을 검토한다.
3. 광고 문구의 허용 범위를 검토한다.
4. 확인되지 않은 효능을 확정적으로 표현하지 않는다.
5. 사람이 처리해야 할 행정이나 권한이 있으면 지점장에게 보고한다.
6. 결과를 제품 관리 지점장에게 보고한다.""",
                )
            )

        unique = {worker.agent_id: worker for worker in workers}
        return list(unique.values())

    def _ensure_ceo_agent(self) -> None:
        if self.registry.get_agent_by_id(self.CEO_AGENT_ID):
            return

        self.factory.get_or_create_agent(
            agent_id=self.CEO_AGENT_ID,
            name="Business_AI_OS_CEO",
            role="AI CEO",
            level="ceo",
            parent_agent_id=None,
            instructions="""너는 Business AI OS의 AI CEO이다.

1. 대표 목표를 분석한다.
2. 회사헌법, 운영원칙과 기존 자산을 확인한다.
3. 담당 지점장을 검색한다.
4. 없을 때만 지점장을 임명한다.
5. 지점장에게 목표와 책임을 위임한다.
6. 직접 실무를 수행하지 않는다.
7. 사람만 처리할 수 있는 권한은 대표에게 보고한다.
8. 대표 처리 후 중단된 업무를 재개시킨다.
9. 지점장 결과를 검토한다.
10. 대표에게 최종 결과와 승인 사항을 보고한다.""",
            description="Business AI OS 전체 운영을 총괄한다.",
            created_reason="CEO Controller 자동 생성",
        )

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

        if existing:
            return self.factory.load_agent(str(existing["agent_id"]))

        return self.factory.get_or_create_agent(
            agent_id=definition.agent_id,
            name=definition.name,
            role=definition.role,
            level="manager",
            parent_agent_id=self.CEO_AGENT_ID,
            instructions=definition.instructions,
            description=definition.description,
            created_reason="AI CEO 자동 지점장 임명",
        )

    def _get_or_create_worker(
        self,
        *,
        definition: WorkerDefinition,
        manager_agent_id: str,
    ) -> Any:
        existing = self.registry.find_agent(
            role=definition.role,
            level="worker",
            parent_agent_id=manager_agent_id,
            active_only=True,
        )

        if existing:
            return self.factory.load_agent(str(existing["agent_id"]))

        return self.factory.get_or_create_agent(
            agent_id=definition.agent_id,
            name=definition.name,
            role=definition.role,
            level="worker",
            parent_agent_id=manager_agent_id,
            instructions=definition.instructions,
            description=definition.description,
            created_reason="제품 관리 지점장 자동 직원 채용",
        )

    def _connect_organization(
        self,
        *,
        manager_agent_id: str,
        worker_agent_ids: list[str],
    ) -> None:
        self.handoff_manager.register_handoff(
            source_agent_id=self.CEO_AGENT_ID,
            target_agent_id=manager_agent_id,
            description="제품 출시 업무를 제품 관리 지점장에게 위임한다.",
            created_reason="CEO Controller 자동 조직 연결",
        )

        for worker_agent_id in worker_agent_ids:
            self.handoff_manager.register_handoff(
                source_agent_id=manager_agent_id,
                target_agent_id=worker_agent_id,
                description="제품 출시 실무를 담당 직원에게 위임한다.",
                created_reason="CEO Controller 자동 조직 연결",
            )

        self.handoff_manager.rebuild_organization(self.CEO_AGENT_ID)

    @staticmethod
    def _clean(value: Any) -> str:
        if value is None:
            return ""
        return " ".join(str(value).strip().split())


ceo_controller = CEOController()


if __name__ == "__main__":
    result = ceo_controller.start(
        title="I-um Bio 식물성 멜라토닌 출시",
        objective="식물성 멜라토닌 제품을 기획하고 OEM 제조 준비와 시장 검토를 진행한다.",
        owner_instruction="식물성 멜라토닌 제품을 출시하라.",
        project_id="project_melatonin_launch_001",
        requires_approval=True,
    )

    print("=" * 60)
    print("CEO Controller 완성본 테스트")
    print("Workflow ID:", result["workflow_id"])
    print("업무 유형:", result["business_type"])
    print("지점장:", result["manager"]["role"])
    print("직원:", [worker["role"] for worker in result["workers"]])
    print("상태:", result["status"])
    print("승인 상태:", result["approval_status"])

    approved = ceo_controller.approve(
        result["workflow_id"],
        approval_note="식물성 멜라토닌 출시 업무를 승인한다.",
    )

    print("최종 상태:", approved["workflow"]["status"])
    print("=" * 60)
