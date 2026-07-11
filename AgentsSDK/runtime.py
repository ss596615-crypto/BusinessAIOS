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
from manager import manager_controller
from worker_controller import worker_controller
from workflow_manager import workflow_manager


BASE_DIR = Path(__file__).resolve().parent
ROUTING_STATE_DIR = BASE_DIR / "company_assets" / "runtime_routes"


class BusinessAIRuntime:
    """
    Business AI OS 통합 Runtime
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
            result["next_action"] = "대표 승인 후 Development Engine V2 실행"

        return result

    def process_instruction(
        self,
        *,
        title: str,
        objective: str,
        owner_instruction: str,
        project_id: str | None = None,
    ) -> dict[str, Any]:
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
        route = self._load_route(workflow_id)

        if not route or not route.get("development_mode"):
            return ceo_controller.approve(workflow_id)

        state_file = development_engine.state_file_for(workflow_id)

        if state_file.exists():
            state = json.loads(state_file.read_text(encoding="utf-8"))
            evidence = state.get("development_evidence") or {}

            if evidence.get("pending_push"):
                push_result = development_engine.push_after_approval(
                    workflow_id
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
                    "next_action": "AI CEO 회의실 최종 보고",
                }

            return {
                "workflow_id": workflow_id,
                "status": state.get("status", "completed"),
                "approval_stage": "already_completed",
                "execution_engine": "development_engine_v2",
                "development_result": state,
                "next_action": state.get("next_action"),
            }

        approval_result = ceo_controller.approve(workflow_id)

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
