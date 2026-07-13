"""
Business AI OS V2
runtime.py

AI CEO 통합 Runtime
- 일반 업무: 기존 AI CEO Workflow 실행
- 개발 업무: Development Engine V2 실행
- 개발 완료 후 대표 승인 시 Git Push
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ceo_controller import ceo_controller
from development_engine import development_engine
from development_planner import development_planner
from manager import manager_controller
from worker_controller import worker_controller
from workflow_manager import workflow_manager

BASE_DIR = Path(__file__).resolve().parent
ROUTING_STATE_DIR = BASE_DIR / "company_assets" / "runtime_routes"


class BusinessAIRuntime:
    """
    Business AI OS 통합 Runtime

    실행 흐름
    1. 대표 지시 접수
    2. AI CEO Workflow 생성
    3. 개발 업무 자동 판별
    4. 대표 실행 승인
    5. Development Engine V2 실행
    6. AI 수정 및 자동 테스트
    7. Git Commit
    8. 대표 Push 승인
    9. Git Push
    """

    def __init__(self) -> None:
        ROUTING_STATE_DIR.mkdir(parents=True, exist_ok=True)

    def start(
        self,
        *,
        title: str,
        objective: str,
        owner_instruction: str,
        project_id: str | None = None,
    ) -> dict[str, Any]:
        """
        AI CEO Workflow를 생성하고 실행 엔진을 자동 지정한다.

        개발 업무는 Development Engine V2로 지정하고,
        일반 업무는 기존 AI CEO Workflow 엔진을 사용한다.
        """
        result = ceo_controller.start(
            title=title,
            objective=objective,
            owner_instruction=owner_instruction,
            project_id=project_id,
        )

        workflow_id = str(result.get("workflow_id") or "").strip()
        is_development = development_engine.is_development_instruction(
            " ".join(
                str(value or "")
                for value in (title, objective, owner_instruction)
            )
        )

        engine_name = (
            "development_engine_v2"
            if is_development
            else "business_ai_os_default"
        )

        route = {
            "workflow_id": workflow_id,
            "title": title,
            "objective": objective,
            "owner_instruction": owner_instruction,
            "project_id": project_id,
            "execution_engine": engine_name,
            "development_mode": is_development,
            "worker_agent_id": self._select_worker_agent_id(result),
            "workflow_snapshot": result,
            "created_at": self._now(),
            "updated_at": self._now(),
        }

        if workflow_id:
            self._save_route(workflow_id, route)

        result["execution_engine"] = engine_name
        result["development_mode"] = is_development

        if is_development:
            result["engine_status"] = "waiting_execution_approval"
            result["next_action"] = (
                "대표 승인 후 Development Engine V2 실행"
            )

        return result

    def process_instruction(
        self,
        *,
        title: str,
        objective: str,
        owner_instruction: str,
        project_id: str | None = None,
    ) -> dict[str, Any]:
        """
        기존 Workflow ID가 포함된 후속 명령은 기존 Workflow로 전달하고,
        신규 명령만 새 Workflow로 생성한다.
        """
        match = re.search(
            r"\b(wf_[0-9a-fA-F]{8,64})\b",
            owner_instruction,
        )

        existing_words = (
            "조회",
            "검증",
            "재실행",
            "재개",
            "취소",
            "상태 확인",
            "산출물",
            "증거",
            "git diff",
            "테스트 결과",
            "계속 구현",
            "승인",
            "반려",
            "push",
        )

        lowered = owner_instruction.lower()

        if match and any(word.lower() in lowered for word in existing_words):
            return workflow_manager.handle_existing_workflow_request(
                match.group(1),
                owner_instruction,
            )

        return self.start(
            title=title,
            objective=objective,
            owner_instruction=owner_instruction,
            project_id=project_id,
        )

    def approve(self, workflow_id: str) -> dict[str, Any]:
        """
        개발 Workflow 승인 처리

        첫 번째 승인:
        - 기존 AI CEO 승인 처리
        - Development Engine V2 실행
        - AI 수정
        - 자동 테스트
        - Git Commit

        두 번째 승인:
        - Git Push

        일반 Workflow:
        - 기존 AI CEO 승인 처리
        """
        route = self._load_route(workflow_id)

        if not route or not route.get("development_mode"):
            return ceo_controller.approve(workflow_id)

        state_file = development_engine.state_file_for(workflow_id)

        if state_file.exists():
            state = json.loads(
                state_file.read_text(encoding="utf-8")
            )
            evidence = state.get("development_evidence") or {}

            if evidence.get("pending_push"):
                push_result = development_engine.push_after_approval(
                    workflow_id
                )

                planner_result = development_planner.register_workflow(
                    workflow_id=workflow_id,
                    development_result={
                        "push_result": push_result,
                    },
                )

                route["updated_at"] = self._now()
                route["engine_status"] = "git_push_completed"
                self._save_route(workflow_id, route)

                return {
                    "workflow_id": workflow_id,
                    "status": "completed",
                    "approval_stage": "git_push",
                    "execution_engine": "development_engine_v2",
                    "push_result": push_result,
                    "planner_result": planner_result,
                    "next_action": "다음 개발 Workflow 승인 대기",
                }

            return {
                "workflow_id": workflow_id,
                "status": state.get("status", "completed"),
                "approval_stage": "already_completed",
                "execution_engine": "development_engine_v2",
                "development_result": state,
                "next_action": state.get("next_action"),
            }

        current_workflow = workflow_manager.require_workflow(
            workflow_id
        )

        if current_workflow.get("status") == "waiting_approval":
            approval_result = ceo_controller.approve(workflow_id)

        elif (
            current_workflow.get("approval_status") == "approved"
            and current_workflow.get("status")
            in {"approved", "running", "ready"}
        ):
            approval_result = {
                "approved": True,
                "recovered": True,
                "workflow": current_workflow,
            }

        else:
            raise RuntimeError(
                "Development Engine을 실행할 수 없는 Workflow 상태입니다. "
                f"status={current_workflow.get('status')}, "
                f"approval_status={current_workflow.get('approval_status')}"
            )

        workflow = self._build_development_workflow(
            workflow_id=workflow_id,
            route=route,
            approval_result=approval_result,
        )

        worker_agent_id = str(
            route.get("worker_agent_id")
            or "development_worker_001"
        )

        development_result = development_engine.execute(
            workflow=workflow,
            worker_agent_id=worker_agent_id,
        )

        route["updated_at"] = self._now()
        route["engine_status"] = "waiting_git_push_approval"
        self._save_route(workflow_id, route)

        return {
            "workflow_id": workflow_id,
            "status": "waiting_approval",
            "approval_stage": "git_push",
            "execution_engine": "development_engine_v2",
            "ceo_approval": approval_result,
            "development_result": development_result,
            "next_action": "대표 승인 후 Git Push",
        }

    def reject(self, workflow_id: str, reason: str) -> dict[str, Any]:
        route = self._load_route(workflow_id)

        if route:
            route["updated_at"] = self._now()
            route["engine_status"] = "rejected"
            route["rejection_reason"] = reason
            self._save_route(workflow_id, route)

        return ceo_controller.reject(workflow_id, reason)

    def report(self, workflow_id: str) -> dict[str, Any]:
        base_report = ceo_controller.report(workflow_id)
        route = self._load_route(workflow_id)

        if not route:
            return base_report

        state_file = development_engine.state_file_for(workflow_id)
        development_result = None

        if state_file.exists():
            development_result = json.loads(
                state_file.read_text(encoding="utf-8")
            )

        return {
            "workflow_id": workflow_id,
            "execution_engine": route.get("execution_engine"),
            "development_mode": route.get("development_mode", False),
            "engine_status": route.get("engine_status"),
            "ceo_report": base_report,
            "development_result": development_result,
        }

    def progress(self, workflow_id: str) -> dict[str, Any]:
        progress = workflow_manager.get_workflow_progress(workflow_id)
        route = self._load_route(workflow_id)

        if route:
            progress["execution_engine"] = route.get("execution_engine")
            progress["development_mode"] = route.get(
                "development_mode",
                False,
            )
            progress["engine_status"] = route.get("engine_status")

        return progress

    def assign_workers(
        self,
        workflow_id: str,
        worker_ids: list[str],
    ) -> dict[str, Any]:
        result = manager_controller.assign_workers(
            workflow_id=workflow_id,
            worker_agent_ids=worker_ids,
        )

        route = self._load_route(workflow_id)
        if route and worker_ids:
            route["worker_agent_id"] = worker_ids[0]
            route["updated_at"] = self._now()
            self._save_route(workflow_id, route)

        return result

    def worker_context(self, workflow_id: str) -> dict[str, Any]:
        return worker_controller.build_context(workflow_id)

    def _build_development_workflow(
        self,
        *,
        workflow_id: str,
        route: dict[str, Any],
        approval_result: Any,
    ) -> dict[str, Any]:
        snapshot = route.get("workflow_snapshot")
        workflow = dict(snapshot) if isinstance(snapshot, dict) else {}

        workflow.update(
            {
                "workflow_id": workflow_id,
                "title": route.get("title"),
                "objective": route.get("objective"),
                "owner_instruction": route.get("owner_instruction"),
                "project_id": route.get("project_id"),
                "approval_result": approval_result,
            }
        )

        metadata = workflow.get("metadata")
        if not isinstance(metadata, dict):
            metadata = {}

        metadata.update(
            {
                "development_mode": True,
                "execution_engine": "development_engine_v2",
                "routed_by": "BusinessAIRuntime",
            }
        )
        workflow["metadata"] = metadata

        return workflow

    @staticmethod
    def _select_worker_agent_id(result: dict[str, Any]) -> str:
        workers = result.get("workers")

        if isinstance(workers, list) and workers:
            first = workers[0]
            if isinstance(first, dict):
                for key in ("agent_id", "worker_agent_id", "id"):
                    value = str(first.get(key) or "").strip()
                    if value:
                        return value

        manager = result.get("manager")
        if isinstance(manager, dict):
            for key in ("agent_id", "manager_agent_id", "id"):
                value = str(manager.get(key) or "").strip()
                if value:
                    return value

        return "development_worker_001"

    def _route_file(self, workflow_id: str) -> Path:
        return ROUTING_STATE_DIR / f"{workflow_id}.json"

    def _save_route(
        self,
        workflow_id: str,
        route: dict[str, Any],
    ) -> None:
        self._route_file(workflow_id).write_text(
            json.dumps(route, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )

    def _load_route(
        self,
        workflow_id: str,
    ) -> dict[str, Any] | None:
        route_file = self._route_file(workflow_id)

        if not route_file.exists():
            return None

        try:
            return json.loads(route_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

runtime = BusinessAIRuntime()


if __name__ == "__main__":
    print("=" * 60)
    print("Business AI Runtime 연결 테스트")

    result = runtime.start(
        title="Development Engine 연결 테스트",
        objective=(
            "AI CEO 회의실의 개발 업무를 "
            "Development Engine V2로 전달한다."
        ),
        owner_instruction=(
            "AI CEO 회의실의 기본 개발 실행 엔진으로 "
            "Development Engine V2를 연결하라."
        ),
        project_id="business_ai_os_release",
    )

    print("Workflow:", result.get("workflow_id"))
    print("실행 엔진:", result.get("execution_engine"))
    print("개발 모드:", result.get("development_mode"))
    print("상태:", result.get("status"))
    print("다음 작업:", result.get("next_action"))
    print("=" * 60)