from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


# =========================================================
# 저장 위치
# =========================================================

BASE_DIR = Path(__file__).resolve().parent
ASSETS_DIR = BASE_DIR / "company_assets"
REGISTRY_FILE = ASSETS_DIR / "agents.json"


# =========================================================
# Agent 자산 구조
# =========================================================

@dataclass
class AgentRecord:
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
    created_at: str = ""
    updated_at: str = ""


# =========================================================
# Agent Registry
# =========================================================

class AgentRegistry:
    """
    Business AI OS의 Agent 자산 관리소.

    역할:
    1. 기존 Agent 검색
    2. 신규 Agent 등록
    3. Agent 수정
    4. Agent 상태 변경
    5. 중복 Agent 생성 방지
    """

    def __init__(self, registry_file: Path = REGISTRY_FILE) -> None:
        self.registry_file = registry_file
        self._ensure_registry_file()

    def _ensure_registry_file(self) -> None:
        self.registry_file.parent.mkdir(parents=True, exist_ok=True)

        if not self.registry_file.exists():
            self._write_data({"agents": []})

    def _read_data(self) -> dict[str, Any]:
        try:
            with self.registry_file.open("r", encoding="utf-8") as file:
                data = json.load(file)

            if not isinstance(data, dict):
                return {"agents": []}

            if not isinstance(data.get("agents"), list):
                data["agents"] = []

            return data

        except (json.JSONDecodeError, OSError):
            return {"agents": []}

    def _write_data(self, data: dict[str, Any]) -> None:
        with self.registry_file.open("w", encoding="utf-8") as file:
            json.dump(
                data,
                file,
                ensure_ascii=False,
                indent=2,
            )

    def list_agents(
        self,
        *,
        level: str | None = None,
        status: str | None = "active",
        parent_agent_id: str | None = None,
    ) -> list[dict[str, Any]]:
        agents = self._read_data()["agents"]

        results: list[dict[str, Any]] = []

        for agent in agents:
            if level and agent.get("level") != level:
                continue

            if status and agent.get("status") != status:
                continue

            if (
                parent_agent_id is not None
                and agent.get("parent_agent_id") != parent_agent_id
            ):
                continue

            results.append(agent)

        return results

    def get_agent_by_id(
        self,
        agent_id: str,
    ) -> dict[str, Any] | None:
        for agent in self._read_data()["agents"]:
            if agent.get("agent_id") == agent_id:
                return agent

        return None

    def find_agent(
        self,
        *,
        name: str | None = None,
        role: str | None = None,
        level: str | None = None,
        parent_agent_id: str | None = None,
        active_only: bool = True,
    ) -> dict[str, Any] | None:
        """
        조건에 맞는 기존 Agent 한 명을 검색한다.
        """

        agents = self._read_data()["agents"]

        normalized_name = self._normalize(name)
        normalized_role = self._normalize(role)

        for agent in agents:
            if active_only and agent.get("status") != "active":
                continue

            if level and agent.get("level") != level:
                continue

            if (
                parent_agent_id is not None
                and agent.get("parent_agent_id") != parent_agent_id
            ):
                continue

            if normalized_name:
                saved_name = self._normalize(agent.get("name", ""))

                if normalized_name not in saved_name:
                    continue

            if normalized_role:
                saved_role = self._normalize(agent.get("role", ""))

                if normalized_role not in saved_role:
                    continue

            return agent

        return None

    def agent_exists(
        self,
        *,
        name: str | None = None,
        role: str | None = None,
        level: str | None = None,
        parent_agent_id: str | None = None,
    ) -> bool:
        return (
            self.find_agent(
                name=name,
                role=role,
                level=level,
                parent_agent_id=parent_agent_id,
            )
            is not None
        )

    def register_agent(
        self,
        record: AgentRecord,
    ) -> dict[str, Any]:
        """
        Agent를 회사 자산으로 등록한다.

        동일 agent_id가 있거나,
        같은 조직 안에 동일한 이름과 역할의 Agent가 있으면
        신규 생성하지 않고 기존 Agent를 반환한다.
        """

        data = self._read_data()
        agents = data["agents"]

        existing_by_id = self.get_agent_by_id(record.agent_id)

        if existing_by_id:
            return {
                "created": False,
                "reason": "same_agent_id_exists",
                "agent": existing_by_id,
            }

        existing_agent = self.find_agent(
            name=record.name,
            role=record.role,
            level=record.level,
            parent_agent_id=record.parent_agent_id,
            active_only=False,
        )

        if existing_agent:
            return {
                "created": False,
                "reason": "same_agent_exists",
                "agent": existing_agent,
            }

        agent_data = asdict(record)
        agents.append(agent_data)

        self._write_data(data)

        return {
            "created": True,
            "reason": "registered",
            "agent": agent_data,
        }

    def update_agent(
        self,
        agent_id: str,
        updates: dict[str, Any],
    ) -> dict[str, Any]:
        """
        기존 Agent 정보를 수정한다.
        agent_id는 변경할 수 없다.
        """

        data = self._read_data()

        allowed_fields = {
            "name",
            "role",
            "level",
            "parent_agent_id",
            "instructions",
            "description",
            "status",
            "reusable",
            "created_reason",
            "updated_at",
        }

        safe_updates = {
            key: value
            for key, value in updates.items()
            if key in allowed_fields
        }

        for agent in data["agents"]:
            if agent.get("agent_id") == agent_id:
                agent.update(safe_updates)
                self._write_data(data)

                return {
                    "updated": True,
                    "agent": agent,
                }

        return {
            "updated": False,
            "reason": "agent_not_found",
            "agent": None,
        }

    def deactivate_agent(
        self,
        agent_id: str,
        updated_at: str = "",
    ) -> dict[str, Any]:
        return self.update_agent(
            agent_id,
            {
                "status": "inactive",
                "updated_at": updated_at,
            },
        )

    def activate_agent(
        self,
        agent_id: str,
        updated_at: str = "",
    ) -> dict[str, Any]:
        return self.update_agent(
            agent_id,
            {
                "status": "active",
                "updated_at": updated_at,
            },
        )

    def delete_agent(
        self,
        agent_id: str,
    ) -> dict[str, Any]:
        """
        실제 삭제 기능.

        운영에서는 가능한 한 deactivate_agent를 먼저 사용한다.
        """

        data = self._read_data()
        original_count = len(data["agents"])

        data["agents"] = [
            agent
            for agent in data["agents"]
            if agent.get("agent_id") != agent_id
        ]

        if len(data["agents"]) == original_count:
            return {
                "deleted": False,
                "reason": "agent_not_found",
            }

        self._write_data(data)

        return {
            "deleted": True,
            "reason": "deleted",
        }

    @staticmethod
    def _normalize(value: str | None) -> str:
        if not value:
            return ""

        return "".join(value.lower().split())


# =========================================================
# 공용 Registry 인스턴스
# =========================================================

registry = AgentRegistry()


# =========================================================
# 단독 실행 테스트
# =========================================================

if __name__ == "__main__":
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc).isoformat()

    test_agent = AgentRecord(
        agent_id="manager_product_001",
        name="Product_Manager",
        role="제품 관리 지점장",
        level="manager",
        parent_agent_id="ceo_001",
        instructions="제품 출시와 제품 관리 업무를 총괄한다.",
        description="제품 관리 지점장 테스트 Agent",
        created_reason="Agent Registry 기능 테스트",
        created_at=now,
        updated_at=now,
    )

    result = registry.register_agent(test_agent)

    print("=" * 60)
    print("Agent 등록 테스트")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print("=" * 60)
    print("현재 Agent 목록")
    print(
        json.dumps(
            registry.list_agents(),
            ensure_ascii=False,
            indent=2,
        )
    )