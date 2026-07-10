from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agents import Agent

from agent_factory import (
    AgentFactory,
    AgentFactoryError,
    AgentNotFoundError,
    factory,
)
from agent_registry import AgentRegistry, registry


# =========================================================
# 저장 위치
# =========================================================

BASE_DIR = Path(__file__).resolve().parent
ASSETS_DIR = BASE_DIR / "company_assets"
HANDOFF_FILE = ASSETS_DIR / "handoffs.json"


# =========================================================
# 예외
# =========================================================

class HandoffManagerError(Exception):
    """Handoff Manager 처리 중 발생하는 기본 예외."""


class HandoffValidationError(HandoffManagerError):
    """Handoff 요청값이 올바르지 않을 때 발생한다."""


class HandoffNotFoundError(HandoffManagerError):
    """요청한 Handoff를 찾지 못했을 때 발생한다."""


class HandoffCycleError(HandoffManagerError):
    """순환 Handoff가 감지됐을 때 발생한다."""


# =========================================================
# Handoff 자산 구조
# =========================================================

@dataclass
class HandoffRecord:
    source_agent_id: str
    target_agent_id: str
    description: str = ""
    status: str = "active"
    created_reason: str = ""
    created_at: str = ""
    updated_at: str = ""


# =========================================================
# Handoff Manager
# =========================================================

class HandoffManager:
    """
    Business AI OS의 Agent 간 업무 위임 관계를 관리한다.

    역할:
    1. Agent 간 Handoff 등록
    2. 중복 Handoff 방지
    3. 순환 Handoff 방지
    4. Handoff 활성화 및 비활성화
    5. Runtime Agent 객체와 Handoff 자산 동기화
    6. 조직 전체 Handoff 구조 조회
    7. Handoff 자산 영구 저장

    저장 구조:
    company_assets/handoffs.json

    기본 원칙:
    - source Agent가 target Agent에게 업무를 위임한다.
    - 동일 source/target Handoff는 중복 생성하지 않는다.
    - 자기 자신에게 Handoff할 수 없다.
    - 순환 구조는 기본적으로 허용하지 않는다.
    """

    def __init__(
        self,
        *,
        agent_factory: AgentFactory | None = None,
        agent_registry: AgentRegistry | None = None,
        handoff_file: Path = HANDOFF_FILE,
    ) -> None:
        self.factory = agent_factory or factory
        self.registry = agent_registry or registry
        self.handoff_file = handoff_file
        self._ensure_handoff_file()

    # =====================================================
    # 파일 관리
    # =====================================================

    def _ensure_handoff_file(self) -> None:
        self.handoff_file.parent.mkdir(parents=True, exist_ok=True)

        if not self.handoff_file.exists():
            self._write_data({"handoffs": []})

    def _read_data(self) -> dict[str, Any]:
        try:
            with self.handoff_file.open("r", encoding="utf-8") as file:
                data = json.load(file)

            if not isinstance(data, dict):
                return {"handoffs": []}

            if not isinstance(data.get("handoffs"), list):
                data["handoffs"] = []

            return data

        except (json.JSONDecodeError, OSError):
            return {"handoffs": []}

    def _write_data(self, data: dict[str, Any]) -> None:
        with self.handoff_file.open("w", encoding="utf-8") as file:
            json.dump(
                data,
                file,
                ensure_ascii=False,
                indent=2,
            )

    # =====================================================
    # 등록 및 연결
    # =====================================================

    def register_handoff(
        self,
        *,
        source_agent_id: str,
        target_agent_id: str,
        description: str = "",
        created_reason: str = "",
        prevent_cycle: bool = True,
        sync_runtime: bool = True,
    ) -> dict[str, Any]:
        """
        source Agent에서 target Agent로 Handoff 관계를 등록한다.

        이미 같은 관계가 있으면 신규 생성하지 않고 기존 관계를 반환한다.
        비활성 상태의 동일 관계가 있으면 다시 활성화한다.
        """

        self._validate_agent_ids(
            source_agent_id=source_agent_id,
            target_agent_id=target_agent_id,
        )

        source_record = self._get_active_agent_record(source_agent_id)
        target_record = self._get_active_agent_record(target_agent_id)

        if prevent_cycle and self.would_create_cycle(
            source_agent_id=source_agent_id,
            target_agent_id=target_agent_id,
        ):
            raise HandoffCycleError(
                "Handoff 등록 시 순환 구조가 생성됩니다: "
                f"{source_agent_id} -> {target_agent_id}"
            )

        data = self._read_data()
        existing = self._find_record_in_data(
            data,
            source_agent_id=source_agent_id,
            target_agent_id=target_agent_id,
            active_only=False,
        )

        now = self._utc_now()

        if existing is not None:
            if existing.get("status") != "active":
                existing["status"] = "active"
                existing["updated_at"] = now

                if description:
                    existing["description"] = description

                if created_reason:
                    existing["created_reason"] = created_reason

                self._write_data(data)

                if sync_runtime:
                    self.sync_agent_runtime(source_agent_id)

                return {
                    "created": False,
                    "reactivated": True,
                    "reason": "handoff_reactivated",
                    "handoff": existing,
                    "source_agent": source_record,
                    "target_agent": target_record,
                }

            if sync_runtime:
                self.sync_agent_runtime(source_agent_id)

            return {
                "created": False,
                "reactivated": False,
                "reason": "handoff_exists",
                "handoff": existing,
                "source_agent": source_record,
                "target_agent": target_record,
            }

        record = HandoffRecord(
            source_agent_id=source_agent_id,
            target_agent_id=target_agent_id,
            description=description,
            status="active",
            created_reason=created_reason,
            created_at=now,
            updated_at=now,
        )

        handoff_data = asdict(record)
        data["handoffs"].append(handoff_data)
        self._write_data(data)

        if sync_runtime:
            self.sync_agent_runtime(source_agent_id)

        return {
            "created": True,
            "reactivated": False,
            "reason": "handoff_registered",
            "handoff": handoff_data,
            "source_agent": source_record,
            "target_agent": target_record,
        }

    def connect_agents(
        self,
        source_agent_id: str,
        target_agent_id: str,
        *,
        description: str = "",
        created_reason: str = "",
    ) -> Agent[Any]:
        """
        Handoff를 등록하고 source Runtime Agent를 반환한다.
        """

        self.register_handoff(
            source_agent_id=source_agent_id,
            target_agent_id=target_agent_id,
            description=description,
            created_reason=created_reason,
            sync_runtime=True,
        )

        return self.factory.load_agent(source_agent_id)

    def connect_multiple(
        self,
        source_agent_id: str,
        target_agent_ids: list[str],
        *,
        created_reason: str = "",
    ) -> Agent[Any]:
        """
        하나의 source Agent에 여러 target Agent를 연결한다.
        """

        if not isinstance(target_agent_ids, list) or not target_agent_ids:
            raise HandoffValidationError(
                "target_agent_ids에는 한 명 이상의 Agent ID가 필요합니다."
            )

        unique_target_ids = list(dict.fromkeys(target_agent_ids))

        for target_agent_id in unique_target_ids:
            self.register_handoff(
                source_agent_id=source_agent_id,
                target_agent_id=target_agent_id,
                created_reason=created_reason,
                sync_runtime=False,
            )

        return self.sync_agent_runtime(source_agent_id)

    # =====================================================
    # 조회
    # =====================================================

    def get_handoff(
        self,
        *,
        source_agent_id: str,
        target_agent_id: str,
        active_only: bool = True,
    ) -> dict[str, Any] | None:
        """
        source/target 기준으로 Handoff 한 건을 조회한다.
        """

        return self._find_record_in_data(
            self._read_data(),
            source_agent_id=source_agent_id,
            target_agent_id=target_agent_id,
            active_only=active_only,
        )

    def list_handoffs(
        self,
        *,
        source_agent_id: str | None = None,
        target_agent_id: str | None = None,
        status: str | None = "active",
    ) -> list[dict[str, Any]]:
        """
        조건에 맞는 Handoff 목록을 반환한다.
        """

        results: list[dict[str, Any]] = []

        for handoff in self._read_data()["handoffs"]:
            if (
                source_agent_id is not None
                and handoff.get("source_agent_id") != source_agent_id
            ):
                continue

            if (
                target_agent_id is not None
                and handoff.get("target_agent_id") != target_agent_id
            ):
                continue

            if status and handoff.get("status") != status:
                continue

            results.append(handoff)

        return results

    def get_target_agent_ids(
        self,
        source_agent_id: str,
        *,
        active_only: bool = True,
    ) -> list[str]:
        """
        source Agent가 Handoff할 수 있는 target Agent ID 목록을 반환한다.
        """

        status = "active" if active_only else None

        return [
            str(record["target_agent_id"])
            for record in self.list_handoffs(
                source_agent_id=source_agent_id,
                status=status,
            )
        ]

    def get_source_agent_ids(
        self,
        target_agent_id: str,
        *,
        active_only: bool = True,
    ) -> list[str]:
        """
        target Agent에게 Handoff하는 source Agent ID 목록을 반환한다.
        """

        status = "active" if active_only else None

        return [
            str(record["source_agent_id"])
            for record in self.list_handoffs(
                target_agent_id=target_agent_id,
                status=status,
            )
        ]

    def get_runtime_handoffs(
        self,
        source_agent_id: str,
    ) -> list[Agent[Any]]:
        """
        Registry와 Handoff 자산을 기준으로 Runtime Agent 객체 목록을 생성한다.
        """

        target_agent_ids = self.get_target_agent_ids(source_agent_id)
        runtime_targets: list[Agent[Any]] = []

        for target_agent_id in target_agent_ids:
            try:
                target_agent = self.factory.load_agent(target_agent_id)
            except AgentNotFoundError as exc:
                raise HandoffManagerError(
                    f"Handoff 대상 Agent를 불러올 수 없습니다: {target_agent_id}"
                ) from exc

            runtime_targets.append(target_agent)

        return runtime_targets

    def get_handoff_tree(
        self,
        root_agent_id: str,
        *,
        max_depth: int = 20,
    ) -> dict[str, Any]:
        """
        root Agent부터 시작하는 Handoff 조직도를 트리 형태로 반환한다.
        """

        if max_depth < 1:
            raise HandoffValidationError(
                "max_depth는 1 이상이어야 합니다."
            )

        self._get_active_agent_record(root_agent_id)

        return self._build_tree(
            agent_id=root_agent_id,
            visited=set(),
            depth=0,
            max_depth=max_depth,
        )

    # =====================================================
    # Runtime 동기화
    # =====================================================

    def sync_agent_runtime(
        self,
        source_agent_id: str,
    ) -> Agent[Any]:
        """
        저장된 Handoff 정보를 source Runtime Agent 객체에 적용한다.
        """

        source_agent = self.factory.load_agent(source_agent_id)
        runtime_targets = self.get_runtime_handoffs(source_agent_id)
        source_agent.handoffs = runtime_targets

        return source_agent

    def sync_all_runtime(self) -> dict[str, Agent[Any]]:
        """
        활성 Handoff를 가진 모든 source Agent를 Runtime에 동기화한다.
        """

        source_agent_ids = {
            str(record["source_agent_id"])
            for record in self.list_handoffs(status="active")
        }

        synced_agents: dict[str, Agent[Any]] = {}

        for source_agent_id in source_agent_ids:
            synced_agents[source_agent_id] = self.sync_agent_runtime(
                source_agent_id
            )

        return synced_agents

    def rebuild_organization(
        self,
        root_agent_id: str,
    ) -> Agent[Any]:
        """
        root Agent 이하의 조직 Handoff 구조를 재귀적으로 Runtime에 복원한다.
        """

        self._get_active_agent_record(root_agent_id)
        visited: set[str] = set()

        def rebuild(agent_id: str) -> Agent[Any]:
            if agent_id in visited:
                return self.factory.load_agent(agent_id)

            visited.add(agent_id)

            target_ids = self.get_target_agent_ids(agent_id)
            target_agents = [rebuild(target_id) for target_id in target_ids]

            return self.factory.load_agent(
                agent_id,
                handoffs=target_agents,
                force_rebuild=True,
            )

        return rebuild(root_agent_id)

    # =====================================================
    # 비활성화 및 삭제
    # =====================================================

    def deactivate_handoff(
        self,
        *,
        source_agent_id: str,
        target_agent_id: str,
        sync_runtime: bool = True,
    ) -> dict[str, Any]:
        """
        Handoff를 비활성화한다.
        """

        data = self._read_data()
        record = self._find_record_in_data(
            data,
            source_agent_id=source_agent_id,
            target_agent_id=target_agent_id,
            active_only=False,
        )

        if record is None:
            return {
                "updated": False,
                "reason": "handoff_not_found",
                "handoff": None,
            }

        record["status"] = "inactive"
        record["updated_at"] = self._utc_now()
        self._write_data(data)

        if sync_runtime:
            self.sync_agent_runtime(source_agent_id)

        return {
            "updated": True,
            "reason": "handoff_deactivated",
            "handoff": record,
        }

    def activate_handoff(
        self,
        *,
        source_agent_id: str,
        target_agent_id: str,
        prevent_cycle: bool = True,
        sync_runtime: bool = True,
    ) -> dict[str, Any]:
        """
        기존 비활성 Handoff를 다시 활성화한다.
        """

        self._validate_agent_ids(
            source_agent_id=source_agent_id,
            target_agent_id=target_agent_id,
        )

        self._get_active_agent_record(source_agent_id)
        self._get_active_agent_record(target_agent_id)

        if prevent_cycle and self.would_create_cycle(
            source_agent_id=source_agent_id,
            target_agent_id=target_agent_id,
            ignore_existing_pair=True,
        ):
            raise HandoffCycleError(
                "Handoff 활성화 시 순환 구조가 생성됩니다: "
                f"{source_agent_id} -> {target_agent_id}"
            )

        data = self._read_data()
        record = self._find_record_in_data(
            data,
            source_agent_id=source_agent_id,
            target_agent_id=target_agent_id,
            active_only=False,
        )

        if record is None:
            raise HandoffNotFoundError(
                "활성화할 Handoff가 없습니다: "
                f"{source_agent_id} -> {target_agent_id}"
            )

        record["status"] = "active"
        record["updated_at"] = self._utc_now()
        self._write_data(data)

        if sync_runtime:
            self.sync_agent_runtime(source_agent_id)

        return {
            "updated": True,
            "reason": "handoff_activated",
            "handoff": record,
        }

    def delete_handoff(
        self,
        *,
        source_agent_id: str,
        target_agent_id: str,
        sync_runtime: bool = True,
    ) -> dict[str, Any]:
        """
        Handoff 자산을 실제로 삭제한다.

        운영에서는 가능한 한 deactivate_handoff()를 먼저 사용한다.
        """

        data = self._read_data()
        original_count = len(data["handoffs"])

        data["handoffs"] = [
            handoff
            for handoff in data["handoffs"]
            if not (
                handoff.get("source_agent_id") == source_agent_id
                and handoff.get("target_agent_id") == target_agent_id
            )
        ]

        if len(data["handoffs"]) == original_count:
            return {
                "deleted": False,
                "reason": "handoff_not_found",
            }

        self._write_data(data)

        if sync_runtime:
            try:
                self.sync_agent_runtime(source_agent_id)
            except (AgentFactoryError, HandoffManagerError):
                pass

        return {
            "deleted": True,
            "reason": "handoff_deleted",
        }

    def remove_all_source_handoffs(
        self,
        source_agent_id: str,
        *,
        delete: bool = False,
    ) -> dict[str, Any]:
        """
        source Agent의 모든 Handoff를 비활성화하거나 삭제한다.
        """

        data = self._read_data()
        affected = 0
        now = self._utc_now()

        if delete:
            retained: list[dict[str, Any]] = []

            for handoff in data["handoffs"]:
                if handoff.get("source_agent_id") == source_agent_id:
                    affected += 1
                    continue

                retained.append(handoff)

            data["handoffs"] = retained

        else:
            for handoff in data["handoffs"]:
                if (
                    handoff.get("source_agent_id") == source_agent_id
                    and handoff.get("status") == "active"
                ):
                    handoff["status"] = "inactive"
                    handoff["updated_at"] = now
                    affected += 1

        self._write_data(data)

        try:
            self.sync_agent_runtime(source_agent_id)
        except (AgentFactoryError, HandoffManagerError):
            pass

        return {
            "success": True,
            "affected": affected,
            "mode": "delete" if delete else "deactivate",
        }

    # =====================================================
    # 순환 검사
    # =====================================================

    def would_create_cycle(
        self,
        *,
        source_agent_id: str,
        target_agent_id: str,
        ignore_existing_pair: bool = False,
    ) -> bool:
        """
        source -> target 관계 추가 시 순환 구조가 되는지 검사한다.

        target에서 출발해 source에 도달할 수 있으면 순환이다.
        """

        if source_agent_id == target_agent_id:
            return True

        graph = self._build_graph()

        if ignore_existing_pair:
            graph.setdefault(source_agent_id, set()).discard(target_agent_id)

        graph.setdefault(source_agent_id, set()).add(target_agent_id)

        return self._path_exists(
            graph=graph,
            start_agent_id=target_agent_id,
            destination_agent_id=source_agent_id,
        )

    def validate_all_handoffs(self) -> dict[str, Any]:
        """
        저장된 전체 Handoff 구조를 검사한다.
        """

        errors: list[dict[str, str]] = []
        active_handoffs = self.list_handoffs(status="active")

        for record in active_handoffs:
            source_agent_id = str(record.get("source_agent_id", ""))
            target_agent_id = str(record.get("target_agent_id", ""))

            if source_agent_id == target_agent_id:
                errors.append(
                    {
                        "type": "self_handoff",
                        "source_agent_id": source_agent_id,
                        "target_agent_id": target_agent_id,
                    }
                )
                continue

            if self.registry.get_agent_by_id(source_agent_id) is None:
                errors.append(
                    {
                        "type": "source_agent_not_found",
                        "source_agent_id": source_agent_id,
                        "target_agent_id": target_agent_id,
                    }
                )

            if self.registry.get_agent_by_id(target_agent_id) is None:
                errors.append(
                    {
                        "type": "target_agent_not_found",
                        "source_agent_id": source_agent_id,
                        "target_agent_id": target_agent_id,
                    }
                )

        cycle_paths = self._find_cycle_paths()

        for cycle_path in cycle_paths:
            errors.append(
                {
                    "type": "handoff_cycle",
                    "source_agent_id": cycle_path[0],
                    "target_agent_id": cycle_path[-1],
                    "path": " -> ".join(cycle_path),
                }
            )

        return {
            "valid": len(errors) == 0,
            "active_handoff_count": len(active_handoffs),
            "errors": errors,
        }

    # =====================================================
    # 내부 유틸리티
    # =====================================================

    def _get_active_agent_record(
        self,
        agent_id: str,
    ) -> dict[str, Any]:
        record = self.registry.get_agent_by_id(agent_id)

        if record is None:
            raise HandoffValidationError(
                f"Registry에 Agent가 없습니다: {agent_id}"
            )

        if record.get("status") != "active":
            raise HandoffValidationError(
                f"비활성 Agent는 Handoff에 사용할 수 없습니다: {agent_id}"
            )

        return record

    def _validate_agent_ids(
        self,
        *,
        source_agent_id: str,
        target_agent_id: str,
    ) -> None:
        if not isinstance(source_agent_id, str) or not source_agent_id.strip():
            raise HandoffValidationError(
                "source_agent_id는 비어 있을 수 없습니다."
            )

        if not isinstance(target_agent_id, str) or not target_agent_id.strip():
            raise HandoffValidationError(
                "target_agent_id는 비어 있을 수 없습니다."
            )

        if source_agent_id == target_agent_id:
            raise HandoffValidationError(
                "Agent는 자기 자신에게 Handoff할 수 없습니다."
            )

    @staticmethod
    def _find_record_in_data(
        data: dict[str, Any],
        *,
        source_agent_id: str,
        target_agent_id: str,
        active_only: bool,
    ) -> dict[str, Any] | None:
        for handoff in data.get("handoffs", []):
            if handoff.get("source_agent_id") != source_agent_id:
                continue

            if handoff.get("target_agent_id") != target_agent_id:
                continue

            if active_only and handoff.get("status") != "active":
                continue

            return handoff

        return None

    def _build_graph(self) -> dict[str, set[str]]:
        graph: dict[str, set[str]] = {}

        for handoff in self.list_handoffs(status="active"):
            source_agent_id = str(handoff["source_agent_id"])
            target_agent_id = str(handoff["target_agent_id"])

            graph.setdefault(source_agent_id, set()).add(target_agent_id)
            graph.setdefault(target_agent_id, set())

        return graph

    @staticmethod
    def _path_exists(
        *,
        graph: dict[str, set[str]],
        start_agent_id: str,
        destination_agent_id: str,
    ) -> bool:
        stack = [start_agent_id]
        visited: set[str] = set()

        while stack:
            current_agent_id = stack.pop()

            if current_agent_id == destination_agent_id:
                return True

            if current_agent_id in visited:
                continue

            visited.add(current_agent_id)
            stack.extend(graph.get(current_agent_id, set()))

        return False

    def _find_cycle_paths(self) -> list[list[str]]:
        graph = self._build_graph()
        cycle_paths: list[list[str]] = []
        visited: set[str] = set()
        active_stack: set[str] = set()
        path: list[str] = []

        def visit(agent_id: str) -> None:
            if agent_id in active_stack:
                try:
                    start_index = path.index(agent_id)
                    cycle = path[start_index:] + [agent_id]
                except ValueError:
                    cycle = [agent_id, agent_id]

                if cycle not in cycle_paths:
                    cycle_paths.append(cycle)

                return

            if agent_id in visited:
                return

            visited.add(agent_id)
            active_stack.add(agent_id)
            path.append(agent_id)

            for target_agent_id in graph.get(agent_id, set()):
                visit(target_agent_id)

            path.pop()
            active_stack.remove(agent_id)

        for agent_id in graph:
            visit(agent_id)

        return cycle_paths

    def _build_tree(
        self,
        *,
        agent_id: str,
        visited: set[str],
        depth: int,
        max_depth: int,
    ) -> dict[str, Any]:
        record = self.registry.get_agent_by_id(agent_id)

        node: dict[str, Any] = {
            "agent_id": agent_id,
            "name": record.get("name") if record else None,
            "role": record.get("role") if record else None,
            "level": record.get("level") if record else None,
            "children": [],
        }

        if depth >= max_depth:
            node["truncated"] = True
            return node

        if agent_id in visited:
            node["cycle_detected"] = True
            return node

        next_visited = set(visited)
        next_visited.add(agent_id)

        for target_agent_id in self.get_target_agent_ids(agent_id):
            node["children"].append(
                self._build_tree(
                    agent_id=target_agent_id,
                    visited=next_visited,
                    depth=depth + 1,
                    max_depth=max_depth,
                )
            )

        return node

    @staticmethod
    def _utc_now() -> str:
        return datetime.now(timezone.utc).isoformat()


# =========================================================
# 공용 Handoff Manager 인스턴스
# =========================================================

handoff_manager = HandoffManager()


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
        created_reason="Handoff Manager 테스트",
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
        created_reason="Handoff Manager 테스트",
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
        created_reason="Handoff Manager 테스트",
    )

    handoff_manager.register_handoff(
        source_agent_id="ceo_001",
        target_agent_id="manager_product_001",
        description="제품 출시 업무를 제품 관리 지점장에게 위임한다.",
        created_reason="CEO 조직 Handoff 구성",
    )

    handoff_manager.register_handoff(
        source_agent_id="manager_product_001",
        target_agent_id="oem_staff_001",
        description="OEM 관련 업무를 OEM 직원에게 위임한다.",
        created_reason="제품 관리 조직 Handoff 구성",
    )

    rebuilt_ceo = handoff_manager.rebuild_organization("ceo_001")
    validation = handoff_manager.validate_all_handoffs()
    tree = handoff_manager.get_handoff_tree("ceo_001")

    print("=" * 60)
    print("Handoff Manager 테스트 완료")
    print("CEO:", rebuilt_ceo.name)
    print("CEO Handoffs:", [agent.name for agent in rebuilt_ceo.handoffs])

    if rebuilt_ceo.handoffs:
        manager = rebuilt_ceo.handoffs[0]
        print(
            "Product Manager Handoffs:",
            [agent.name for agent in manager.handoffs],
        )

    print("Handoff 구조 정상:", validation["valid"])
    print("활성 Handoff 수:", validation["active_handoff_count"])
    print("조직도:")
    print(json.dumps(tree, ensure_ascii=False, indent=2))
    print("=" * 60)
