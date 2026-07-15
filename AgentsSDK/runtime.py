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
from tool_creation_manager import tool_creation_manager
from worker_controller import worker_controller
from workflow_manager import workflow_manager


BASE_DIR = Path(__file__).resolve().parent
ROUTING_STATE_DIR = BASE_DIR / "company_assets" / "runtime_routes"


class BusinessAIRuntime:
    """
    Business AI OS Tool 중심 통합 Runtime.

    실행 흐름:
    1. 대표 지시 접수
    2. AI CEO Workflow 생성
    3. 지점장 및 직원 배정
    4. 대표 실행 승인
    5. Worker Controller 실행
    6. 기존 Tool 검색 및 재사용
    7. Tool이 없으면 생성 승인 요청
    8. 대표 승인 후 자동 생성·테스트·등록·업무 재개
    9. 개발 Tool 실행 결과 Git Commit
    10. 대표 Push 승인 후 Git Push
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
            " ".join(str(value or "") for value in (title, objective, owner_instruction))
        )

        engine_name = "worker_tool_execution" if is_development else "business_ai_os_default"

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
            "engine_status": "waiting_execution_approval" if is_development else "waiting_approval",
            "tool_creation_request_id": "",
            "created_at": self._now(),
            "updated_at": self._now(),
        }

        if workflow_id:
            self._save_route(workflow_id, route)

        result["execution_engine"] = engine_name
        result["development_mode"] = is_development
        result["engine_status"] = route["engine_status"]

        if is_development:
            result["next_action"] = "대표 승인 후 직원이 기존 Development Engine Tool을 검색하여 실행"

        return result

    def process_instruction(
        self,
        *,
        title: str,
        objective: str,
        owner_instruction: str,
        project_id: str | None = None,
    ) -> dict[str, Any]:
        tool_request_match = re.search(r"\b(tcreq_[0-9a-fA-F]{8,64})\b", owner_instruction)
        lowered = owner_instruction.lower()

        if tool_request_match:
            request_id = tool_request_match.group(1)
            if "승인" in lowered:
                return self.approve(request_id)
            if "반려" in lowered or "거절" in lowered:
                return self.reject(request_id, owner_instruction)
            return {
                "request_id": request_id,
                "request": tool_creation_manager.require_request(request_id),
            }

        workflow_match = re.search(r"\b(wf_[0-9a-fA-F]{8,64})\b", owner_instruction)
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

        if workflow_match and any(word.lower() in lowered for word in existing_words):
            return workflow_manager.handle_existing_workflow_request(workflow_match.group(1), owner_instruction)

        return self.start(title=title, objective=objective, owner_instruction=owner_instruction, project_id=project_id)

    def approve(self, approval_id: str) -> dict[str, Any]:
        if str(approval_id).startswith("tcreq_"):
            return self._approve_tool_creation_request(approval_id)

        workflow_id = approval_id
        route = self._load_route(workflow_id)

        if not route or not route.get("development_mode"):
            approval_result = ceo_controller.approve(workflow_id)
            if route:
                current_workflow = workflow_manager.require_workflow(workflow_id)
                workflow_status = str(current_workflow.get("status") or "").strip()
                route["updated_at"] = self._now()
                route["engine_status"] = "completed" if workflow_status == "completed" else workflow_status or "approved"
                self._save_route(workflow_id, route)
            return approval_result

        state_file = development_engine.state_file_for(workflow_id)
        if state_file.exists():
            state = json.loads(state_file.read_text(encoding="utf-8"))
            evidence = state.get("development_evidence") or {}
            if evidence.get("pending_push"):
                push_result = development_engine.push_after_approval(workflow_id)
                planner_result = development_planner.register_workflow(
                    workflow_id=workflow_id,
                    development_result={"push_result": push_result},
                )
                completed_at = self._now()
                workflow_manager._set_workflow_fields(
                    workflow_id,
                    {
                        "status": "completed",
                        "approval_status": "approved",
                        "completed_at": completed_at,
                        "updated_at": completed_at,
                        "failure_reason": "",
                    },
                )
                route["updated_at"] = completed_at
                route["engine_status"] = "git_push_completed"
                self._save_route(workflow_id, route)
                return {
                    "workflow_id": workflow_id,
                    "status": "completed",
                    "approval_stage": "git_push",
                    "execution_engine": "worker_tool_execution",
                    "push_result": push_result,
                    "planner_result": planner_result,
                    "next_action": "다음 개발 Workflow 승인 대기",
                }
            return {
                "workflow_id": workflow_id,
                "status": state.get("status", "completed"),
                "approval_stage": "already_completed",
                "execution_engine": "worker_tool_execution",
                "development_result": state,
                "next_action": state.get("next_action"),
            }

        current_workflow = workflow_manager.require_workflow(workflow_id)
        if current_workflow.get("status") == "waiting_approval":
            approval_result = workflow_manager.approve_workflow(
                workflow_id,
                approval_note="대표 개발 실행 승인",
                approved_by="owner",
                auto_resume=False,
            )
        elif current_workflow.get("approval_status") == "approved" and current_workflow.get("status") in {"approved", "running", "ready"}:
            approval_result = {"approved": True, "recovered": True, "workflow": current_workflow}
        else:
            raise RuntimeError(
                "직원 Tool 실행을 시작할 수 없는 Workflow 상태입니다. "
                f"status={current_workflow.get('status')}, approval_status={current_workflow.get('approval_status')}"
            )

        workflow = self._build_development_workflow(workflow_id=workflow_id, route=route, approval_result=approval_result)
        worker_agent_id = self._resolve_registered_worker_id(workflow=workflow, route=route)
        route["worker_agent_id"] = worker_agent_id
        route["updated_at"] = self._now()
        self._save_route(workflow_id, route)

        worker_result = worker_controller.execute(
            workflow_id=workflow_id,
            worker_agent_id=worker_agent_id,
            workflow=workflow,
            step={
                "step_id": "development_tool_execution",
                "assigned_agent_id": worker_agent_id,
                "input_data": {"assignment": route.get("owner_instruction")},
            },
        )

        route["updated_at"] = self._now()
        if worker_result.get("status") == "waiting_permission" and worker_result.get("tool_creation_request_id"):
            request_id = str(worker_result.get("tool_creation_request_id"))
            route["tool_creation_request_id"] = request_id
            route["engine_status"] = "waiting_tool_creation_approval"
            self._save_route(workflow_id, route)
            return {
                "workflow_id": workflow_id,
                "status": "waiting_approval",
                "approval_stage": "tool_creation",
                "execution_engine": "worker_tool_execution",
                "ceo_approval": approval_result,
                "worker_result": worker_result,
                "tool_creation_request_id": request_id,
                "next_action": "대표 승인 후 Tool 자동 생성·테스트·Registry 등록 및 업무 재개",
            }

        route["engine_status"] = "waiting_git_push_approval"
        self._save_route(workflow_id, route)
        return {
            "workflow_id": workflow_id,
            "status": "waiting_approval",
            "approval_stage": "git_push",
            "execution_engine": "worker_tool_execution",
            "ceo_approval": approval_result,
            "worker_result": worker_result,
            "next_action": "대표 승인 후 Git Push",
        }

    def _approve_tool_creation_request(self, request_id: str) -> dict[str, Any]:
        approval_result = tool_creation_manager.approve(request_id, approved_by="owner")
        request = tool_creation_manager.require_request(request_id)
        resume_result = worker_controller.resume_tool_request(request_id)
        workflow_id = str(request.get("workflow_id", ""))
        route = self._load_route(workflow_id)
        if route:
            route["updated_at"] = self._now()
            route["tool_creation_request_id"] = request_id
            state_file = development_engine.state_file_for(workflow_id)
            route["engine_status"] = "waiting_git_push_approval" if state_file.exists() else "tool_execution_completed"
            self._save_route(workflow_id, route)
        return {
            "request_id": request_id,
            "workflow_id": workflow_id,
            "status": "waiting_approval" if route and route.get("development_mode") else "completed",
            "approval_stage": "git_push" if route and route.get("development_mode") else "tool_completed",
            "tool_approval": approval_result,
            "resume_result": resume_result,
            "next_action": "대표 승인 후 Git Push" if route and route.get("development_mode") else "AI CEO 최종 보고",
        }

    def reject(self, approval_id: str, reason: str) -> dict[str, Any]:
        if str(approval_id).startswith("tcreq_"):
            return tool_creation_manager.reject(approval_id, reason)
        workflow_id = approval_id
        route = self._load_route(workflow_id)
        if route:
            route["updated_at"] = self._now()
            route["engine_status"] = "rejected"
            route["rejection_reason"] = reason
            self._save_route(workflow_id, route)
        return ceo_controller.reject(workflow_id, reason)

    def report(self, workflow_id: str) -> dict[str, Any]:
        workflow = workflow_manager.require_workflow(workflow_id)
        progress = workflow_manager.get_workflow_progress(workflow_id)
        route = self._load_route(workflow_id) or {}
        return {
            "workflow_id": workflow_id,
            "workflow": workflow,
            "progress": progress,
            "status": workflow.get("status"),
            "approval_status": workflow.get("approval_status"),
            "engine_status": route.get("engine_status") or workflow.get("metadata", {}).get("engine_status") or workflow.get("status"),
            "next_action": workflow.get("next_action") or route.get("next_action") or "결정 중",
            "execution_engine": route.get("execution_engine"),
            "development_mode": route.get("development_mode", False),
        }

    def progress(self, workflow_id: str) -> dict[str, Any]:
        workflow = workflow_manager.require_workflow(workflow_id)
        progress = workflow_manager.get_workflow_progress(workflow_id)
        route = self._load_route(workflow_id) or {}
        progress["execution_engine"] = route.get("execution_engine")
        progress["development_mode"] = route.get("development_mode", False)
        progress["engine_status"] = route.get("engine_status") or workflow.get("metadata", {}).get("engine_status") or workflow.get("status")
        progress["tool_creation_request_id"] = route.get("tool_creation_request_id", "")
        progress["next_action"] = workflow.get("next_action") or route.get("next_action") or "결정 중"
        return progress

    def assign_workers(self, workflow_id: str, worker_ids: list[str]) -> dict[str, Any]:
        result = manager_controller.assign_workers(workflow_id=workflow_id, worker_agent_ids=worker_ids)
        route = self._load_route(workflow_id)
        if route and worker_ids:
            route["worker_agent_id"] = worker_ids[0]
            route["updated_at"] = self._now()
            self._save_route(workflow_id, route)
        return result

    def worker_context(self, workflow_id: str) -> str:
        return worker_controller.build_context(workflow_id)

    def _build_development_workflow(self, *, workflow_id: str, route: dict[str, Any], approval_result: Any) -> dict[str, Any]:
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
                "manager_agent_id": workflow.get("manager_agent_id") or self._select_manager_agent_id(workflow),
            }
        )
        metadata = workflow.get("metadata")
        if not isinstance(metadata, dict):
            metadata = {}
        metadata.update(
            {
                "development_mode": True,
                "execution_engine": "worker_tool_execution",
                "routed_by": "BusinessAIRuntime",
                "tool_requirement": {
                    "tool_id": "tool_development_engine",
                    "tool_name": "Development Engine Tool",
                    "category": "development",
                    "query": "development engine",
                },
            }
        )
        workflow["metadata"] = metadata
        return workflow

    def _resolve_registered_worker_id(self, *, workflow: dict[str, Any], route: dict[str, Any]) -> str:
        candidates: list[str] = []
        route_candidate = str(route.get("worker_agent_id") or "").strip()
        if route_candidate:
            candidates.append(route_candidate)
        steps = workflow.get("steps") or []
        if isinstance(steps, list):
            for step in steps:
                if not isinstance(step, dict):
                    continue
                assigned_id = str(step.get("assigned_agent_id") or "").strip()
                step_type = str(step.get("step_type") or "").strip().lower()
                if assigned_id and step_type in {"worker_execution", "worker_task", "execution", "development"}:
                    candidates.insert(0, assigned_id)
                elif assigned_id:
                    candidates.append(assigned_id)
        workers = workflow.get("workers")
        if isinstance(workers, list):
            for worker in workers:
                if not isinstance(worker, dict):
                    continue
                for key in ("agent_id", "worker_agent_id", "id"):
                    value = str(worker.get(key) or "").strip()
                    if value:
                        candidates.insert(0, value)
                        break
        seen: set[str] = set()
        for candidate in candidates:
            if not candidate or candidate in seen:
                continue
            seen.add(candidate)
            agent = worker_controller.registry.get_agent_by_id(candidate)
            if agent and agent.get("status") == "active":
                return candidate
        raise RuntimeError("개발 Workflow에 배정된 실제 Registry 직원 ID를 찾을 수 없습니다. 후보: " + ", ".join(candidates))

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

    @staticmethod
    def _select_manager_agent_id(workflow: dict[str, Any]) -> str:
        manager = workflow.get("manager")
        if isinstance(manager, dict):
            for key in ("agent_id", "manager_agent_id", "id"):
                value = str(manager.get(key) or "").strip()
                if value:
                    return value
        return ""

    def _route_file(self, workflow_id: str) -> Path:
        return ROUTING_STATE_DIR / f"{workflow_id}.json"

    def _save_route(self, workflow_id: str, route: dict[str, Any]) -> None:
        self._route_file(workflow_id).write_text(json.dumps(route, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

    def _load_route(self, workflow_id: str) -> dict[str, Any] | None:
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
    print("Business AI Runtime V2.5 연결 테스트")
    print("실행 구조:")
    print("대표 → AI CEO → 지점장 → 직원 → Tool Registry → Execution Tool Core")
    print("Runtime:", type(runtime).__name__)
    print("=" * 60)
