from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from agents import Agent

from agent_registry import AgentRecord, AgentRegistry, registry


# =========================================================
# 예외
# =========================================================

class AgentFactoryError(Exception):
    """Agent Factory 처리 중 발생하는 기본 예외."""


class AgentValidationError(AgentFactoryError):
    """Agent 생성 요청값이 올바르지 않을 때 발생한다."""


class AgentNotFoundError(AgentFactoryError):
    """Registry에서 요청한 Agent를 찾지 못했을 때 발생한다."""


# =========================================================
# Agent 생성 요청 구조
# =========================================================

@dataclass(frozen=True)
class AgentSpec:
    """
    OpenAI Agent 생성과 Registry 등록에 필요한 표준 요청 구조.
    """

    agent_id: str
    name: str
    role: str
    level: str
    parent_agent_id: str | None
    instructions: str
    description: str
    status: str = "active"
    reusable: bool = True
    created_reason: str = ""
    model: str | None = None


# =========================================================
# Agent Factory
# =========================================================

class AgentFactory:
    """
    Business AI OS의 Agent 생성 공장.

    역할:
    1. Agent 생성 요청 검증
    2. Registry에서 기존 Agent 검색
    3. 기존 Agent 재사용
    4. OpenAI Agents SDK Agent 객체 생성
    5. Registry 자동 등록
    6. 실행 중 Agent 객체 캐시
    7. Handoff 연결 준비

    주의:
    - Registry에는 Agent의 영구 자산 정보가 저장된다.
    - 실제 Agent 객체는 현재 Python 실행 중 메모리에 캐시된다.
    - Handoff 연결은 handoffs 인수 또는 set_handoffs()로 설정한다.
    """

    ALLOWED_LEVELS = {
        "ceo",
        "manager",
        "worker",
        "specialist",
        "assistant",
    }

    def __init__(
        self,
        agent_registry: AgentRegistry | None = None,
    ) -> None:
        self.registry = agent_registry or registry
        self._agent_cache: dict[str, Agent[Any]] = {}

    # =====================================================
    # 공개 메서드
    # =====================================================

    def create_agent(
        self,
        *,
        agent_id: str,
        name: str,
        role: str,
        level: str,
        parent_agent_id: str | None,
        instructions: str,
        description: str,
        reusable: bool = True,
        created_reason: str = "",
        model: str | None = None,
        handoffs: list[Agent[Any]] | None = None,
        force_rebuild: bool = False,
    ) -> Agent[Any]:
        """
        신규 Agent를 생성하고 Registry에 등록한다.

        동일 agent_id 또는 동일 조직 내 같은 Agent가 이미 존재하면
        신규 등록 대신 기존 자산을 기반으로 Agent 객체를 반환한다.

        force_rebuild=True이면 메모리 캐시는 무시하지만
        Registry의 중복 방지 정책은 유지된다.
        """

        spec = AgentSpec(
            agent_id=agent_id,
            name=name,
            role=role,
            level=level,
            parent_agent_id=parent_agent_id,
            instructions=instructions,
            description=description,
            reusable=reusable,
            created_reason=created_reason,
            model=model,
        )

        self._validate_spec(spec)

        if not force_rebuild:
            cached_agent = self._agent_cache.get(spec.agent_id)

            if cached_agent is not None:
                if handoffs is not None:
                    cached_agent.handoffs = list(handoffs)

                return cached_agent

        now = self._utc_now()

        record = AgentRecord(
            agent_id=spec.agent_id,
            name=spec.name,
            role=spec.role,
            level=spec.level,
            parent_agent_id=spec.parent_agent_id,
            instructions=spec.instructions,
            description=spec.description,
            status=spec.status,
            reusable=spec.reusable,
            created_reason=spec.created_reason,
            created_at=now,
            updated_at=now,
        )

        registration_result = self.registry.register_agent(record)
        saved_record = registration_result.get("agent")

        if not isinstance(saved_record, dict):
            raise AgentFactoryError(
                f"Agent Registry 등록 결과가 올바르지 않습니다: {spec.agent_id}"
            )

        agent = self._build_agent_from_record(
            saved_record,
            model=spec.model,
            handoffs=handoffs,
        )

        saved_agent_id = str(saved_record.get("agent_id", spec.agent_id))
        self._agent_cache[saved_agent_id] = agent

        return agent

    def get_or_create_agent(
        self,
        *,
        agent_id: str,
        name: str,
        role: str,
        level: str,
        parent_agent_id: str | None,
        instructions: str,
        description: str,
        reusable: bool = True,
        created_reason: str = "",
        model: str | None = None,
        handoffs: list[Agent[Any]] | None = None,
    ) -> Agent[Any]:
        """
        기존 Agent가 있으면 재사용하고, 없으면 생성한다.
        Business AI OS에서 기본적으로 사용할 권장 메서드다.
        """

        cached_agent = self._agent_cache.get(agent_id)

        if cached_agent is not None:
            if handoffs is not None:
                cached_agent.handoffs = list(handoffs)

            return cached_agent

        existing_record = self.registry.get_agent_by_id(agent_id)

        if existing_record is None:
            existing_record = self.registry.find_agent(
                name=name,
                role=role,
                level=level,
                parent_agent_id=parent_agent_id,
                active_only=True,
            )

        if existing_record is not None:
            existing_agent_id = str(existing_record["agent_id"])

            cached_existing = self._agent_cache.get(existing_agent_id)

            if cached_existing is not None:
                if handoffs is not None:
                    cached_existing.handoffs = list(handoffs)

                return cached_existing

            agent = self._build_agent_from_record(
                existing_record,
                model=model,
                handoffs=handoffs,
            )

            self._agent_cache[existing_agent_id] = agent
            return agent

        return self.create_agent(
            agent_id=agent_id,
            name=name,
            role=role,
            level=level,
            parent_agent_id=parent_agent_id,
            instructions=instructions,
            description=description,
            reusable=reusable,
            created_reason=created_reason,
            model=model,
            handoffs=handoffs,
        )

    def load_agent(
        self,
        agent_id: str,
        *,
        model: str | None = None,
        handoffs: list[Agent[Any]] | None = None,
        include_inactive: bool = False,
        force_rebuild: bool = False,
    ) -> Agent[Any]:
        """
        Registry에 저장된 Agent를 agent_id로 불러온다.
        """

        if not force_rebuild:
            cached_agent = self._agent_cache.get(agent_id)

            if cached_agent is not None:
                if handoffs is not None:
                    cached_agent.handoffs = list(handoffs)

                return cached_agent

        record = self.registry.get_agent_by_id(agent_id)

        if record is None:
            raise AgentNotFoundError(
                f"Registry에 Agent가 없습니다: {agent_id}"
            )

        if not include_inactive and record.get("status") != "active":
            raise AgentNotFoundError(
                f"Agent가 비활성 상태입니다: {agent_id}"
            )

        agent = self._build_agent_from_record(
            record,
            model=model,
            handoffs=handoffs,
        )

        self._agent_cache[agent_id] = agent
        return agent

    def set_handoffs(
        self,
        agent_id: str,
        handoffs: list[Agent[Any]],
    ) -> Agent[Any]:
        """
        실행 중인 Agent 객체에 Handoff 대상 Agent를 연결한다.
        """

        agent = self.load_agent(agent_id)
        agent.handoffs = list(handoffs)

        return agent

    def clear_handoffs(
        self,
        agent_id: str,
    ) -> Agent[Any]:
        """
        실행 중인 Agent 객체의 Handoff 연결을 제거한다.
        """

        return self.set_handoffs(agent_id, [])

    def update_runtime_agent(
        self,
        agent_id: str,
        *,
        name: str | None = None,
        instructions: str | None = None,
        description: str | None = None,
        handoffs: list[Agent[Any]] | None = None,
    ) -> Agent[Any]:
        """
        현재 실행 중인 Agent 객체를 수정하고 Registry도 함께 갱신한다.
        """

        agent = self.load_agent(agent_id)
        updates: dict[str, Any] = {
            "updated_at": self._utc_now(),
        }

        if name is not None:
            cleaned_name = name.strip()

            if not cleaned_name:
                raise AgentValidationError("name은 비어 있을 수 없습니다.")

            agent.name = cleaned_name
            updates["name"] = cleaned_name

        if instructions is not None:
            cleaned_instructions = instructions.strip()

            if not cleaned_instructions:
                raise AgentValidationError(
                    "instructions는 비어 있을 수 없습니다."
                )

            agent.instructions = cleaned_instructions
            updates["instructions"] = cleaned_instructions

        if description is not None:
            cleaned_description = description.strip()
            agent.handoff_description = cleaned_description
            updates["description"] = cleaned_description

        if handoffs is not None:
            agent.handoffs = list(handoffs)

        update_result = self.registry.update_agent(
            agent_id,
            updates,
        )

        if not update_result.get("updated"):
            raise AgentFactoryError(
                f"Registry Agent 수정에 실패했습니다: {agent_id}"
            )

        return agent

    def deactivate_agent(
        self,
        agent_id: str,
    ) -> dict[str, Any]:
        """
        Registry의 Agent를 비활성화하고 실행 캐시에서 제거한다.
        """

        self._agent_cache.pop(agent_id, None)

        return self.registry.deactivate_agent(
            agent_id,
            updated_at=self._utc_now(),
        )

    def activate_agent(
        self,
        agent_id: str,
    ) -> dict[str, Any]:
        """
        Registry의 Agent를 다시 활성화한다.
        """

        return self.registry.activate_agent(
            agent_id,
            updated_at=self._utc_now(),
        )

    def remove_from_cache(
        self,
        agent_id: str,
    ) -> bool:
        """
        Registry 데이터는 유지하고 실행 캐시에서만 제거한다.
        """

        return self._agent_cache.pop(agent_id, None) is not None

    def clear_cache(self) -> None:
        """
        모든 실행 Agent 캐시를 비운다.
        """

        self._agent_cache.clear()

    def get_cached_agent(
        self,
        agent_id: str,
    ) -> Agent[Any] | None:
        """
        현재 실행 캐시에 있는 Agent를 반환한다.
        """

        return self._agent_cache.get(agent_id)

    def list_cached_agents(self) -> dict[str, Agent[Any]]:
        """
        현재 실행 중인 Agent 캐시 복사본을 반환한다.
        """

        return dict(self._agent_cache)

    # =====================================================
    # 내부 메서드
    # =====================================================

    def _build_agent_from_record(
        self,
        record: dict[str, Any],
        *,
        model: str | None = None,
        handoffs: list[Agent[Any]] | None = None,
    ) -> Agent[Any]:
        """
        Registry 기록을 OpenAI Agents SDK Agent 객체로 변환한다.
        """

        name = str(record.get("name", "")).strip()
        instructions = str(record.get("instructions", "")).strip()
        description = str(record.get("description", "")).strip()

        if not name:
            raise AgentValidationError(
                "Registry Agent의 name이 비어 있습니다."
            )

        if not instructions:
            raise AgentValidationError(
                f"Registry Agent의 instructions가 비어 있습니다: {name}"
            )

        agent_kwargs: dict[str, Any] = {
            "name": name,
            "instructions": instructions,
            "handoff_description": description or None,
            "handoffs": list(handoffs or []),
        }

        if model:
            agent_kwargs["model"] = model

        return Agent(**agent_kwargs)

    def _validate_spec(
        self,
        spec: AgentSpec,
    ) -> None:
        required_values = {
            "agent_id": spec.agent_id,
            "name": spec.name,
            "role": spec.role,
            "level": spec.level,
            "instructions": spec.instructions,
            "description": spec.description,
        }

        for field_name, value in required_values.items():
            if not isinstance(value, str) or not value.strip():
                raise AgentValidationError(
                    f"{field_name}은 비어 있을 수 없습니다."
                )

        if spec.level not in self.ALLOWED_LEVELS:
            allowed = ", ".join(sorted(self.ALLOWED_LEVELS))

            raise AgentValidationError(
                f"지원하지 않는 Agent level입니다: {spec.level}. "
                f"허용값: {allowed}"
            )

        if (
            spec.parent_agent_id is not None
            and not spec.parent_agent_id.strip()
        ):
            raise AgentValidationError(
                "parent_agent_id는 None 또는 비어 있지 않은 문자열이어야 합니다."
            )

        if spec.level == "ceo" and spec.parent_agent_id is not None:
            raise AgentValidationError(
                "CEO Agent의 parent_agent_id는 None이어야 합니다."
            )

        if spec.level != "ceo" and spec.parent_agent_id is None:
            raise AgentValidationError(
                f"{spec.level} Agent에는 parent_agent_id가 필요합니다."
            )

    @staticmethod
    def _utc_now() -> str:
        return datetime.now(timezone.utc).isoformat()


# =========================================================
# 공용 Factory 인스턴스
# =========================================================

factory = AgentFactory()


# =========================================================
# 단독 실행 테스트
# =========================================================

if __name__ == "__main__":
    oem_staff = factory.get_or_create_agent(
        agent_id="oem_staff_001",
        name="OEM_Staff",
        role="OEM 담당 직원",
        level="worker",
        parent_agent_id="manager_product_001",
        instructions="""
너는 Business AI OS의 OEM 담당 직원이다.

담당업무

1. OEM 업체 조사
2. OEM 견적 요청
3. MOQ 확인
4. 제조일정 확인
5. 제조 가능 여부 분석

모든 결과는 제품 관리 지점장에게 보고한다.
""".strip(),
        description="OEM 견적 및 제조사 관리를 담당한다.",
        created_reason="Business AI OS V2 Agent Factory 테스트",
    )

    product_manager = factory.get_or_create_agent(
        agent_id="manager_product_001",
        name="Product_Manager",
        role="제품 관리 지점장",
        level="manager",
        parent_agent_id="ceo_001",
        instructions="""
너는 Business AI OS의 제품 관리 지점장이다.

역할

1. 제품기획
2. OEM
3. 원료검토
4. 경쟁제품 분석
5. 상세페이지
6. 판매채널

OEM 관련 업무는 반드시 OEM 직원에게 위임한다.

모든 결과는 AI CEO에게 보고한다.
""".strip(),
        description="제품 출시 업무 전체를 총괄한다.",
        created_reason="Business AI OS V2 Agent Factory 테스트",
        handoffs=[oem_staff],
    )

    ceo = factory.get_or_create_agent(
        agent_id="ceo_001",
        name="Business_AI_OS_CEO",
        role="AI CEO",
        level="ceo",
        parent_agent_id=None,
        instructions="""
너는 Business AI OS의 AI CEO이다.

대표의 목표를 분석한다.

반드시 아래 순서를 따른다.

1. 회사헌법
2. 운영원칙
3. 기존 회사 자산
4. 기존 Agent
5. 기존 Workflow

제품 출시 업무이면 제품 관리 지점장에게 위임한다.

직접 실무를 하지 않는다.
""".strip(),
        description="Business AI OS 전체 운영을 총괄한다.",
        created_reason="Business AI OS V2 Agent Factory 테스트",
        handoffs=[product_manager],
    )

    print("=" * 60)
    print("Agent Factory 테스트 완료")
    print("CEO:", ceo.name)
    print("CEO Handoffs:", [agent.name for agent in ceo.handoffs])
    print(
        "Product Manager Handoffs:",
        [agent.name for agent in product_manager.handoffs],
    )
    print("캐시 Agent ID:", list(factory.list_cached_agents().keys()))
    print("=" * 60)
