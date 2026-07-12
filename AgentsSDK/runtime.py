from __future__ import annotations

import json
import os
import re
import socket
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ceo_controller import ceo_controller
from bootstrap_engine import bootstrap_engine
from development_engine import development_engine
from manager import manager_controller
from worker_controller import worker_controller
from workflow_manager import workflow_manager


BASE_DIR = Path(__file__).resolve().parent
REPO_ROOT = BASE_DIR.parent.resolve()
ROUTING_STATE_DIR = BASE_DIR / "company_assets" / "runtime_routes"
RUNTIME_STATE_DIR = BASE_DIR / "company_assets" / "runtime_restart_runs"


@dataclass
class RuntimeProcessState:
    pid: int | None = None
    creation_time: str = ""
    command: str = ""
    working_directory: str = ""


class BusinessAIRuntime:
    """운영 엔진과 개발 엔지�� 분리하는 Business AI OS 실행 라우터."""

    DEVELOPMENT_ENGINE_NAME = "development_engine_v2"
    DEVELOPMENT_MANAGER_ID = "development_engine"
    DEVELOPMENT_MANAGER = {
        "agent_id": DEVELOPMENT_MANAGER_ID,
        "name": "Development_Engine",
        "role": "AI 개발 실행 엔진",
    }

    def __init__(self) -> None:
        ROUTING_STATE_DIR.mkdir(parents=True, exist_ok=True)
        RUNTIME_STATE_DIR.mkdir(parents=True, exist_ok=True)

    def start(
        self,
        *,
        title: str,
        objective: str,
        owner_instruction: str,
        project_id: str | None = None,
    ) -> dict[str, Any]:
        combined_instruction = " ".join(
            str(value or "")
            for value in (title, objective, owner_instruction)
        )

        if development_engine.is_development_instruction(combined_instruction):
            return self._start_development_workflow(
                title=title,
                objective=objective,
                owner_instruction=owner_instruction,
                project_id=project_id,
            )

        result = ceo_controller.start(
            title=title,
            objective=objective,
            owner_instruction=owner_instruction,
            project_id=project_id,
        )

        if isinstance(result, dict):
            result.setdefault("execution_engine", "business_ai_os_operating")
            result.setdefault("development_mode", False)

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

        if match:
            workflow_id = match.group(1)
            route = self._load_route(workflow_id)

            if route and route.get("development_mode"):
                return self._handle_development_followup(
                    workflow_id,
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
            if any(word.lower() in lowered for word in existing_words):
                return workflow_manager.handle_existing_workflow_request(
                    workflow_id,
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

        status = str(route.get("status") or "")
        approval_stage = str(route.get("approval_stage") or "execution")

        if status in {"completed", "rejected"}:
            return self._development_result_payload(route)

        if approval_stage == "git_push":
            return self._approve_development_push(route)

        return self._approve_development_execution(route)

    def reject(self, workflow_id: str, reason: str) -> dict[str, Any]:
        route = self._load_route(workflow_id)

        if not route or not route.get("development_mode"):
            return ceo_controller.reject(workflow_id, reason)

        route.update(
            {
                "status": "rejected",
                "approval_status": "rejected",
                "rejection_reason": str(reason or "").strip(),
                "engine_status": "rejected",
                "next_action": "대표 반려로 개발 업무 종료",
                "updated_at": self._now(),
                "completed_at": self._now(),
            }
        )
        self._save_route(workflow_id, route)
        return self._development_result_payload(route)

    def report(self, workflow_id: str) -> dict[str, Any]:
        route = self._load_route(workflow_id)

        if not route or not route.get("development_mode"):
            return ceo_controller.report(workflow_id)

        state = self._read_development_state(workflow_id)

        return {
            "workflow_id": workflow_id,
            "execution_engine": self.DEVELOPMENT_ENGINE_NAME,
            "development_mode": True,
            "engine_status": route.get("engine_status"),
            "workflow": self._public_development_workflow(route),
            "progress": self._development_progress(route),
            "development_result": state,
            "context": route.get("owner_instruction", ""),
        }

    def progress(self, workflow_id: str) -> dict[str, Any]:
        route = self._load_route(workflow_id)

        if route and route.get("development_mode"):
            return self._development_progress(route)

        return workflow_manager.get_workflow_progress(workflow_id)

    def assign_workers(
        self,
        workflow_id: str,
        worker_ids: list[str],
    ) -> dict[str, Any]:
        route = self._load_route(workflow_id)

        if route and route.get("development_mode"):
            return {
                "workflow_id": workflow_id,
                "assigned": False,
                "reason": (
                    "개발 Workflow는 일반 운영 직원을 배정하지 않고 "
                    "Development Engine이 직접 실행합니다."
                ),
                "execution_engine": self.DEVELOPMENT_ENGINE_NAME,
            }

        return manager_controller.assign_workers(
            workflow_id=workflow_id,
            worker_agent_ids=worker_ids,
        )

    def worker_context(self, workflow_id: str) -> dict[str, Any]:
        route = self._load_route(workflow_id)

        if route and route.get("development_mode"):
            return {
                "workflow_id": workflow_id,
                "execution_engine": self.DEVELOPMENT_ENGINE_NAME,
                "owner_instruction": route.get("owner_instruction"),
                "objective": route.get("objective"),
                "project_id": route.get("project_id"),
            }

        return worker_controller.build_context(workflow_id)

    def restart_runtime_after_push(
        self,
        workflow_id: str,
        *,
        hq_entrypoint: str = "AgentsSDK/business_ai_hq.py",
        streamlit_port: int = 8501,
    ) -> dict[str, Any]:
        state = self._create_restart_state(workflow_id, hq_entrypoint, streamlit_port)
        self._save_runtime_state(workflow_id, state)

        try:
            current = self._inspect_runtime_process()
            state["current_process"] = current
            state["stage"] = "preflight_ok"
            self._save_runtime_state(workflow_id, state)

            changed_modules = self._detect_changed_python_modules()
            state["changed_python_modules"] = changed_modules
            self._save_runtime_state(workflow_id, state)

            if current.pid:
                stop_result = self._stop_process_tree(current.pid)
                state["stop_result"] = stop_result
                self._save_runtime_state(workflow_id, state)

            deploy_result = self._apply_changed_modules(changed_modules)
            state["deploy_result"] = deploy_result
            self._save_runtime_state(workflow_id, state)

            start_result = self._start_streamlit_server(hq_entrypoint, streamlit_port)
            state["start_result"] = start_result
            self._save_runtime_state(workflow_id, state)

            validation = self._validate_business_ai_hq(hq_entrypoint, streamlit_port)
            state["validation_result"] = validation
            self._save_runtime_state(workflow_id, state)

            if not validation.get("passed"):
                raise RuntimeError(validation.get("reason") or "business_ai_hq.py 실행 검증 실패")

            state["status"] = "completed"
            state["completed_at"] = self._now()
            state["next_action"] = "Workflow completed"
            self._save_runtime_state(workflow_id, state)
            return state

        except Exception as exc:
            restore_result = self._restore_previous_process(state)
            state["restore_result"] = restore_result
            state["status"] = "failed"
            state["failure_reason"] = str(exc)
            state["runtime_monitor"] = {
                "visible_reason": str(exc),
                "stage": state.get("stage", ""),
                "validation_result": state.get("validation_result", {}),
                "start_result": state.get("start_result", {}),
            }
            state["completed_at"] = self._now()
            self._save_runtime_state(workflow_id, state)
            raise

    def _start_development_workflow(
        self,
        *,
        title: str,
        objective: str,
        owner_instruction: str,
        project_id: str | None,
    ) -> dict[str, Any]:
        workflow_id = f"wf_{uuid.uuid4().hex[:16]}"
        now = self._now()

        route = {
            "workflow_id": workflow_id,
            "title": title,
            "objective": objective,
            "owner_instruction": owner_instruction,
            "project_id": project_id,
            "requested_by": "owner",
            "business_type": "development_engine",
            "execution_engine": self.DEVELOPMENT_ENGINE_NAME,
            "development_mode": True,
            "manager": dict(self.DEVELOPMENT_MANAGER),
            "managers": [],
            "workers": [],
            "worker_agent_id": self.DEVELOPMENT_MANAGER_ID,
            "status": "waiting_approval",
            "approval_status": "pending",
            "approval_stage": "execution",
            "engine_status": "waiting_execution_approval",
            "analysis_summary": (
                "개발 업무로 판정되어 일반 운영 지점장과 직원을 배정하지 않고 "
                "Development Engine V2에 전용 배정했습니다."
            ),
            "result_summary": "",
            "failure_reason": "",
            "rejection_reason": "",
            "next_action": "대표 승인 후 Development Engine V2 실행",
            "created_at": now,
            "updated_at": now,
            "completed_at": "",
        }

        self._save_route(workflow_id, route)
        return self._start_payload(route)

    def _approve_development_execution(
        self,
        route: dict[str, Any],
    ) -> dict[str, Any]:
        workflow_id = str(route["workflow_id"])

        route.update(
            {
                "status": "in_progress",
                "approval_status": "approved",
                "engine_status": "development_engine_running",
                "updated_at": self._now(),
                "next_action": "Development Engine V2 실행 중",
            }
        )
        self._save_route(workflow_id, route)

        workflow = {
            "workflow_id": workflow_id,
            "title": route.get("title"),
            "objective": route.get("objective"),
            "owner_instruction": route.get("owner_instruction"),
            "project_id": route.get("project_id"),
            "requested_by": "owner",
            "status": "in_progress",
            "approval_status": "approved",
            "metadata": {
                "business_type": "development_engine",
                "development_mode": True,
                "execution_engine": self.DEVELOPMENT_ENGINE_NAME,
                "routed_by": "BusinessAIRuntime",
            },
        }

        try:
            development_result = bootstrap_engine.execute(
                workflow=workflow,
                worker_agent_id=self.DEVELOPMENT_MANAGER_ID,
            )
        except Exception as exc:
            route.update(
                {
                    "status": "failed",
                    "approval_status": "approved",
                    "engine_status": "development_engine_failed",
                    "failure_reason": str(exc),
                    "next_action": "개발 실패 원인 확인 후 재지시",
                    "updated_at": self._now(),
                    "completed_at": self._now(),
                }
            )
            self._save_route(workflow_id, route)
            return self._development_result_payload(route)

        route.update(
            {
                "status": "waiting_approval",
                "approval_status": "pending",
                "approval_stage": "git_push",
                "engine_status": "waiting_git_push_approval",
                "result_summary": development_result.get(
                    "result_summary",
                    development_result.get("work_summary", ""),
                ),
                "next_action": "대표 승인 후 Git Push",
                "updated_at": self._now(),
            }
        )
        self._save_route(workflow_id, route)

        payload = self._development_result_payload(route)
        payload["development_result"] = development_result
        return payload

    def _approve_development_push(
        self,
        route: dict[str, Any],
    ) -> dict[str, Any]:
        workflow_id = str(route["workflow_id"])

        route.update(
            {
                "status": "in_progress",
                "approval_status": "approved",
                "engine_status": "git_push_running",
                "updated_at": self._now(),
                "next_action": "Git Push 실행 중",
            }
        )
        self._save_route(workflow_id, route)

        try:
            push_result = bootstrap_engine.push_after_approval(workflow_id)
            runtime_result = self.restart_runtime_after_push(workflow_id)
        except Exception as exc:
            route.update(
                {
                    "status": "failed",
                    "engine_status": "runtime_restart_failed",
                    "failure_reason": str(exc),
                    "next_action": "기존 프로세스 복구 후 원인 보고",
                    "updated_at": self._now(),
                }
            )
            self._save_route(workflow_id, route)
            return self._development_result_payload(route)

        if not push_result.get("pushed"):
            reason = str(push_result.get("reason") or "unknown")
            if reason == "push_not_pending":
                route.update(
                    {
                        "status": "completed",
                        "approval_status": "approved",
                        "engine_status": "completed",
                        "next_action": "개발 및 Git 반영 완료",
                        "updated_at": self._now(),
                        "completed_at": self._now(),
                    }
                )
            else:
                route.update(
                    {
                        "status": "failed",
                        "engine_status": "git_push_failed",
                        "failure_reason": reason,
                        "next_action": "Git Push 상태 확인",
                        "updated_at": self._now(),
                    }
                )
        else:
            route.update(
                {
                    "status": "completed",
                    "approval_status": "approved",
                    "engine_status": "completed",
                    "next_action": "개발 및 Git 반영 완료",
                    "updated_at": self._now(),
                    "completed_at": self._now(),
                }
            )

        self._save_route(workflow_id, route)
        payload = self._development_result_payload(route)
        payload["push_result"] = push_result
        payload["runtime_restart_result"] = runtime_result
        return payload

    def _handle_development_followup(
        self,
        workflow_id: str,
        instruction: str,
    ) -> dict[str, Any]:
        lowered = instruction.lower()

        if "승인" in instruction or "push" in lowered:
            return self.approve(workflow_id)

        if "반려" in instruction or "거절" in instruction:
            return self.reject(workflow_id, instruction)

        return self.report(workflow_id)

    def _start_payload(
        self,
        route: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "workflow_id": route["workflow_id"],
            "status": route["status"],
            "approval_status": route["approval_status"],
            "business_type": route["business_type"],
            "analysis_summary": route["analysis_summary"],
            "manager": route["manager"],
            "managers": route["managers"],
            "workers": route["workers"],
            "worker_selection_owner": self.DEVELOPMENT_ENGINE_NAME,
            "execution_engine": self.DEVELOPMENT_ENGINE_NAME,
            "development_mode": True,
            "engine_status": route["engine_status"],
            "next_action": route["next_action"],
        }

    def _development_result_payload(
        self,
        route: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "workflow_id": route["workflow_id"],
            "status": route.get("status"),
            "approval_status": route.get("approval_status"),
            "approval_stage": route.get("approval_stage"),
            "business_type": route.get("business_type"),
            "execution_engine": self.DEVELOPMENT_ENGINE_NAME,
            "development_mode": True,
            "engine_status": route.get("engine_status"),
            "manager": route.get("manager"),
            "workers": route.get("workers", []),
            "analysis_summary": route.get("analysis_summary"),
            "result_summary": route.get("result_summary"),
            "failure_reason": route.get("failure_reason"),
            "rejection_reason": route.get("rejection_reason"),
            "next_action": route.get("next_action"),
            "progress": self._development_progress(route),
        }

    def _public_development_workflow(
        self,
        route: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "workflow_id": route["workflow_id"],
            "title": route.get("title"),
            "objective": route.get("objective"),
            "owner_instruction": route.get("owner_instruction"),
            "project_id": route.get("project_id"),
            "requested_by": route.get("requested_by"),
            "status": route.get("status"),
            "requires_approval": True,
            "approval_status": route.get("approval_status"),
            "result_summary": route.get("result_summary"),
            "next_action": route.get("next_action"),
            "failure_reason": route.get("failure_reason"),
            "rejection_reason": route.get("rejection_reason"),
            "metadata": {
                "business_type": route.get("business_type"),
                "development_mode": True,
                "execution_engine": self.DEVELOPMENT_ENGINE_NAME,
            },
            "created_at": route.get("created_at"),
            "updated_at": route.get("updated_at"),
            "completed_at": route.get("completed_at"),
        }

    def _development_progress(
        self,
        route: dict[str, Any],
    ) -> dict[str, Any]:
        status = str(route.get("status") or "")
        stage = str(route.get("approval_stage") or "execution")

        if status == "completed":
            percent = 100.0
            completed_steps = 5
            failed_steps = 0
            pending_steps = 0
        elif status == "failed":
            percent = 40.0 if stage == "execution" else 80.0
            completed_steps = 1 if stage == "execution" else 4
            failed_steps = 1
            pending_steps = max(0, 5 - completed_steps - failed_steps)
        elif status == "rejected":
            percent = 0.0 if stage == "execution" else 80.0
            completed_steps = 0 if stage == "execution" else 4
            failed_steps = 0
            pending_steps = 0
        elif stage == "git_push":
            percent = 80.0
            completed_steps = 4
            failed_steps = 0
            pending_steps = 1
        elif status == "in_progress":
            percent = 40.0
            completed_steps = 1
            failed_steps = 0
            pending_steps = 4
        else:
            percent = 20.0
            completed_steps = 1
            failed_steps = 0
            pending_steps = 4

        return {
            "workflow_id": route["workflow_id"],
            "status": status,
            "total_steps": 5,
            "completed_steps": completed_steps,
            "failed_steps": failed_steps,
            "pending_steps": pending_steps,
            "current_step_index": min(completed_steps, 4),
            "progress_percent": percent,
            "approval_status": route.get("approval_status"),
            "approval_stage": route.get("approval_stage"),
            "execution_engine": self.DEVELOPMENT_ENGINE_NAME,
            "development_mode": True,
            "engine_status": route.get("engine_status"),
        }

    def _read_development_state(
        self,
        workflow_id: str,
    ) -> dict[str, Any] | None:
        state_file = development_engine.state_file_for(workflow_id)

        if not state_file.exists():
            return None

        try:
            return json.loads(state_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

    def _route_file(self, workflow_id: str) -> Path:
        return ROUTING_STATE_DIR / f"{workflow_id}.json"


    def _save_route(
        self,
        workflow_id: str,
        route: dict[str, Any],
    ) -> None:
        route["updated_at"] = route.get("updated_at") or self._now()

        self._route_file(workflow_id).parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        self._route_file(workflow_id).write_text(
            json.dumps(
                route,
                ensure_ascii=False,
                indent=2,
                default=str,
            ),
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

    def _create_restart_state(self, workflow_id: str, hq_entrypoint: str, streamlit_port: int) -> dict[str, Any]:
        return {
            "workflow_id": workflow_id,
            "status": "running",
            "stage": "created",
            "hq_entrypoint": hq_entrypoint,
            "streamlit_port": streamlit_port,
            "current_process": {},
            "changed_python_modules": [],
            "stop_result": {},
            "deploy_result": {},
            "start_result": {},
            "validation_result": {},
            "restore_result": {},
            "failure_reason": "",
            "next_action": "Runtime 재시작 진행 중",
            "created_at": self._now(),
            "updated_at": self._now(),
            "completed_at": "",
        }

    def _inspect_runtime_process(self) -> RuntimeProcessState:
        script = r"""
import json, os
try:
    import psutil
except Exception:
    print(json.dumps({"pid": None, "creation_time": "", "command": "", "working_directory": ""}, ensure_ascii=False))
    raise SystemExit(0)
for p in psutil.process_iter(['pid','name','cmdline','cwd','create_time']):
    try:
        cmd = ' '.join(p.info.get('cmdline') or [])
        if 'streamlit' in cmd.lower() and 'business_ai_hq.py' in cmd.lower():
            print(json.dumps({
                'pid': p.info.get('pid'),
                'creation_time': str(p.info.get('create_time') or ''),
                'command': cmd,
                'working_directory': str(p.info.get('cwd') or ''),
            }, ensure_ascii=False))
            raise SystemExit(0)
    except Exception:
        pass
print(json.dumps({"pid": None, "creation_time": "", "command": "", "working_directory": ""}, ensure_ascii=False))
"""
        result = subprocess.run([sys.executable, "-c", script], cwd=REPO_ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
        try:
            payload = json.loads(result.stdout.strip() or "{}")
        except json.JSONDecodeError:
            payload = {}
        return RuntimeProcessState(
            pid=payload.get("pid"),
            creation_time=str(payload.get("creation_time") or ""),
            command=str(payload.get("command") or ""),
            working_directory=str(payload.get("working_directory") or ""),
        )

    def _detect_changed_python_modules(self) -> list[str]:
        diff = subprocess.run(["git", "diff", "--name-only", "HEAD"], cwd=REPO_ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60, check=False)
        modules = []
        for line in diff.stdout.splitlines():
            rel = line.strip().replace("\\", "/")
            if rel.endswith(".py") and rel.startswith("AgentsSDK/"):
                modules.append(rel)
        return modules

    def _apply_changed_modules(self, modules: list[str]) -> dict[str, Any]:
        return {
            "applied": bool(modules),
            "modules": modules,
            "strategy": "git_worktree_refresh",
        }

    def _start_streamlit_server(self, hq_entrypoint: str, streamlit_port: int) -> dict[str, Any]:
        entrypoint = (REPO_ROOT / hq_entrypoint).resolve()
        if not entrypoint.exists():
            raise FileNotFoundError(f"실행 파일을 찾을 수 없습니다: {entrypoint}")
        cmd = [sys.executable, "-m", "streamlit", "run", str(entrypoint), "--server.port", str(streamlit_port), "--server.address", "127.0.0.1"]
        proc = subprocess.Popen(cmd, cwd=entrypoint.parent, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
        time.sleep(8)
        return {"started": True, "pid": proc.pid, "command": cmd, "entrypoint": str(entrypoint), "working_directory": str(entrypoint.parent)}

    def _validate_business_ai_hq(self, hq_entrypoint: str, streamlit_port: int) -> dict[str, Any]:
        entrypoint = (REPO_ROOT / hq_entrypoint).resolve()
        compile_result = subprocess.run([sys.executable, "-m", "py_compile", str(entrypoint)], cwd=REPO_ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60, check=False)
        if compile_result.returncode != 0:
            return {"passed": False, "reason": compile_result.stderr.strip() or compile_result.stdout.strip() or "py_compile 실패"}

        if not self._check_local_port("127.0.0.1", streamlit_port, timeout=20):
            return {
                "passed": False,
                "reason": f"127.0.0.1:{streamlit_port} 접속 확인에 실패했습니다.",
                "port": streamlit_port,
            }
        return {"passed": True, "reason": "business_ai_hq.py py_compile OK 및 Streamlit 접속 확인 완료", "port": streamlit_port}

    def _check_local_port(self, host: str, port: int, *, timeout: int = 10) -> bool:
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                with socket.create_connection((host, port), timeout=2):
                    return True
            except OSError:
                time.sleep(1)
        return False

    def _stop_process_tree(self, pid: int) -> dict[str, Any]:
        script = f"""
import json
try:
    import psutil
    p = psutil.Process({pid})
    children = p.children(recursive=True)
    for child in children:
        try:
            child.terminate()
        except Exception:
            pass
    p.terminate()
    gone, alive = psutil.wait_procs([p, *children], timeout=10)
    for proc in alive:
        try:
            proc.kill()
        except Exception:
            pass
    print(json.dumps({{"stopped": True, "pid": {pid}}}, ensure_ascii=False))
except Exception as exc:
    print(json.dumps({{"stopped": False, "pid": {pid}, "error": str(exc)}}, ensure_ascii=False))
"""
        proc = subprocess.run([sys.executable, "-c", script], cwd=REPO_ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30, check=False)
        try:
            return json.loads(proc.stdout.strip() or "{}")
        except json.JSONDecodeError:
            return {"stopped": False, "pid": pid, "error": proc.stderr.strip() or proc.stdout.strip()}

    def _restore_previous_process(self, state: dict[str, Any]) -> dict[str, Any]:
        current = state.get("current_process") or {}
        pid = current.get("pid")
        if not pid:
            return {"restored": False, "reason": "no_previous_process"}
        return self._stop_process_tree(int(pid))

    def _atomic_write_json(self, path: Path, data: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_suffix(path.suffix + f".{uuid.uuid4().hex}.tmp")
        tmp_path.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        os.replace(tmp_path, path)

    def _save_runtime_state(self, workflow_id: str, state: dict[str, Any]) -> None:
        path = RUNTIME_STATE_DIR / f"{workflow_id}.json"
        self._atomic_write_json(path, state)

    def _load_runtime_state(self, workflow_id: str) -> dict[str, Any] | None:
        path = RUNTIME_STATE_DIR / f"{workflow_id}.json"
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()


runtime = BusinessAIRuntime()
