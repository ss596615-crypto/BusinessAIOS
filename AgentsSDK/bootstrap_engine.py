from __future__ import annotations

import json
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from development_engine import (
    DevelopmentEngine,
    DevelopmentEngineError,
)


BASE_DIR = Path(__file__).resolve().parent
REPO_ROOT = BASE_DIR.parent.resolve()

BOOTSTRAP_STATE_DIR = (
    BASE_DIR
    / "company_assets"
    / "bootstrap_runs"
)

BOOTSTRAP_STATE_DIR.mkdir(
    parents=True,
    exist_ok=True,
)


class BootstrapEngineError(RuntimeError):
    pass


class BootstrapEngine:
    """
    Git 작업공간 자동 관리 엔진.

    실행 순서:

    1. 현재 Git 상태 확인
    2. 기존 변경사항 자동 stash
    3. 개발 브랜치 확인
    4. 원격 저장소 fetch
    5. Development Engine 실행
    6. Git Commit 완료 후 대표 승인 대기
    7. 대표 승인 후 Git Push
    8. 기존 stash 자동 복원
    9. 충돌 발생 시 자동 중단 및 보고
    10. Push 후 Runtime 자동 재시작 및 검증
    """

    ENGINE_NAME = "bootstrap_engine_v1"
    DEVELOPMENT_BRANCH = "ai-ceo-dev"

    PROTECTED_PATHS = (
        "AgentsSDK/bootstrap_engine.py",
        "AgentsSDK/runtime.py",
        "AgentsSDK/business_ai_hq.py",
        "AgentsSDK/company_assets/bootstrap_runs/",
        "AgentsSDK/company_assets/runtime_routes/",
        "AgentsSDK/company_assets/development_runs/",
    )

    def __init__(
        self,
        repo_root: Path = REPO_ROOT,
    ) -> None:
        self.repo_root = repo_root.resolve()

    def execute(
        self,
        workflow: dict[str, Any],
        worker_agent_id: str,
    ) -> dict[str, Any]:
        workflow_id = str(
            workflow.get("workflow_id") or ""
        ).strip()

        if not workflow_id:
            raise BootstrapEngineError(
                "Workflow ID가 없습니다."
            )

        self._ensure_git_repository()

        state = self._load_state(workflow_id)

        if (
            state
            and state.get("development_completed")
            and state.get("development_result")
        ):
            return state["development_result"]

        state = {
            "workflow_id": workflow_id,
            "engine": self.ENGINE_NAME,
            "status": "preparing",
            "stash_created": False,
            "stash_reference": "",
            "stash_message": "",
            "protected_paths": list(
                self.PROTECTED_PATHS
            ),
            "development_completed": False,
            "push_completed": False,
            "restore_completed": False,
            "restore_conflict": False,
            "failure_reason": "",
            "created_at": self._now(),
            "updated_at": self._now(),
        }

        self._save_state(workflow_id, state)

        try:
            original_status = self._git(
                ["status", "--porcelain"],
                check=False,
            )["stdout"].splitlines()

            state["original_git_status"] = (
                original_status
            )

            if original_status:
                stash_result = (
                    self._stash_existing_changes(
                        workflow_id
                    )
                )

                state.update(stash_result)

            branch = self._current_branch()

            if branch != self.DEVELOPMENT_BRANCH:
                checkout = self._git(
                    [
                        "checkout",
                        self.DEVELOPMENT_BRANCH,
                    ],
                    check=False,
                )

                if checkout["returncode"] != 0:
                    raise BootstrapEngineError(
                        "개발 브랜치 전환 실패:\n"
                        + checkout["stdout"]
                        + checkout["stderr"]
                    )

            fetch = self._git(
                [
                    "fetch",
                    "origin",
                    self.DEVELOPMENT_BRANCH,
                ],
                check=False,
            )

            state["branch"] = self._current_branch()
            state["fetch_output"] = (
                fetch["stdout"]
                + fetch["stderr"]
            )
            state["status"] = (
                "development_running"
            )
            state["updated_at"] = self._now()

            self._save_state(
                workflow_id,
                state,
            )

            engine = DevelopmentEngine(
                repo_root=self.repo_root
            )

            engine._ensure_clean_worktree = (
                lambda: None
            )

            result = engine.execute(
                workflow=workflow,
                worker_agent_id=worker_agent_id,
            )

            state["status"] = (
                "waiting_git_push_approval"
            )
            state["development_completed"] = True
            state["development_result"] = result
            state["updated_at"] = self._now()

            self._save_state(
                workflow_id,
                state,
            )

            result.setdefault(
                "bootstrap_evidence",
                {},
            )

            result["bootstrap_evidence"].update(
                {
                    "engine": self.ENGINE_NAME,
                    "stash_created": state.get(
                        "stash_created"
                    ),
                    "stash_reference": state.get(
                        "stash_reference"
                    ),
                    "original_git_status": (
                        original_status
                    ),
                    "protected_paths": list(
                        self.PROTECTED_PATHS
                    ),
                    "branch": state.get("branch"),
                    "restore_pending": bool(
                        state.get("stash_created")
                    ),
                }
            )

            return result

        except Exception as exc:
            state["status"] = "failed"
            state["failure_reason"] = str(exc)
            state["updated_at"] = self._now()

            self._save_state(
                workflow_id,
                state,
            )

            raise

    def push_after_approval(
        self,
        workflow_id: str,
    ) -> dict[str, Any]:
        state = self._load_state(workflow_id)

        if not state:
            return {
                "pushed": False,
                "reason": (
                    "bootstrap_state_not_found"
                ),
            }

        if not state.get(
            "development_completed"
        ):
            return {
                "pushed": False,
                "reason": (
                    "development_not_completed"
                ),
            }

        state["status"] = "git_push_running"
        state["updated_at"] = self._now()

        self._save_state(
            workflow_id,
            state,
        )

        engine = DevelopmentEngine(
            repo_root=self.repo_root
        )

        try:
            push_result = (
                engine.push_after_approval(
                    workflow_id
                )
            )

            state["push_result"] = push_result

            if not push_result.get("pushed"):
                reason = push_result.get(
                    "reason"
                )

                if reason != "push_not_pending":
                    state["status"] = (
                        "git_push_failed"
                    )
                    state["failure_reason"] = (
                        str(reason)
                    )
                    state["updated_at"] = (
                        self._now()
                    )

                    self._save_state(
                        workflow_id,
                        state,
                    )

                    return push_result

            state["push_completed"] = True
            state["status"] = (
                "restoring_workspace"
            )
            state["updated_at"] = self._now()

            self._save_state(
                workflow_id,
                state,
            )

            restore_result = (
                self.restore_workspace(
                    workflow_id
                )
            )

            state = (
                self._load_state(workflow_id)
                or state
            )

            if restore_result.get(
                "restored"
            ):
                state["status"] = "completed"
            elif restore_result.get(
                "reason"
            ) == "stash_not_created":
                state["status"] = "completed"
            else:
                state["status"] = (
                    "restore_conflict"
                )

            state["updated_at"] = self._now()

            self._save_state(
                workflow_id,
                state,
            )

            return {
                "pushed": bool(
                    push_result.get("pushed")
                    or push_result.get(
                        "reason"
                    )
                    == "push_not_pending"
                ),
                "workflow_id": workflow_id,
                "push_result": push_result,
                "restore_result": (
                    restore_result
                ),
                "bootstrap_state": state,
            }

        except Exception as exc:
            state["status"] = "git_push_failed"
            state["failure_reason"] = str(exc)
            state["updated_at"] = self._now()

            self._save_state(
                workflow_id,
                state,
            )

            raise

    def restore_workspace(
        self,
        workflow_id: str,
    ) -> dict[str, Any]:
        state = self._load_state(workflow_id)

        if not state:
            return {
                "restored": False,
                "reason": (
                    "bootstrap_state_not_found"
                ),
            }

        if not state.get("stash_created"):
            state["restore_completed"] = True
            state["updated_at"] = self._now()

            self._save_state(
                workflow_id,
                state,
            )

            return {
                "restored": False,
                "reason": "stash_not_created",
            }

        if state.get("restore_completed"):
            return {
                "restored": True,
                "reason": "already_restored",
            }

        stash_reference = str(
            state.get("stash_reference")
            or ""
        ).strip()

        if not stash_reference:
            stash_reference = "stash@{0}"

        restore = self._git(
            [
                "stash",
                "pop",
                stash_reference,
            ],
            check=False,
        )

        output = (
            restore["stdout"]
            + restore["stderr"]
        )

        state["restore_output"] = output
        state["restore_returncode"] = (
            restore["returncode"]
        )
        state["updated_at"] = self._now()

        if restore["returncode"] == 0:
            state["restore_completed"] = True
            state["restore_conflict"] = False
            state["status"] = "completed"

            self._save_state(
                workflow_id,
                state,
            )

            return {
                "restored": True,
                "workflow_id": workflow_id,
                "output": output,
            }

        state["restore_completed"] = False
        state["restore_conflict"] = True
        state["status"] = "restore_conflict"
        state["failure_reason"] = (
            "기존 작업공간 복원 중 충돌 발생"
        )

        self._save_state(
            workflow_id,
            state,
        )

        return {
            "restored": False,
            "workflow_id": workflow_id,
            "reason": "stash_pop_conflict",
            "output": output,
            "manual_action_required": False,
            "next_action": (
                "AI CEO가 충돌 파일을 분석하고 "
                "자동 복구 Workflow를 생성해야 합니다."
            ),
        }

    def get_status(
        self,
        workflow_id: str,
    ) -> dict[str, Any]:
        state = self._load_state(workflow_id)

        if not state:
            return {
                "workflow_id": workflow_id,
                "status": "not_found",
            }

        return state

    def _stash_existing_changes(
        self,
        workflow_id: str,
    ) -> dict[str, Any]:
        stash_message = (
            "Business AI OS Bootstrap "
            f"{workflow_id} "
            f"{uuid.uuid4().hex[:8]}"
        )

        args = [
            "stash",
            "push",
            "-u",
            "-m",
            stash_message,
        ]

        protected_exprs = [
            f":(exclude){protected}"
            for protected in self.PROTECTED_PATHS
        ]

        if protected_exprs:
            args.extend(protected_exprs)
        else:
            args.append(".")

        result = self._git(
            args,
            check=False,
        )

        output = (
            result["stdout"]
            + result["stderr"]
        )

        if result["returncode"] != 0:
            raise BootstrapEngineError(
                "Git 작업공간 자동 stash 실패:\n"
                + output
            )

        stash_list = self._git(
            [
                "stash",
                "list",
                "--format=%gd|%gs",
            ],
            check=False,
        )["stdout"].splitlines()

        stash_reference = ""

        for line in stash_list:
            if stash_message in line:
                stash_reference = (
                    line.split("|", 1)[0]
                )
                break

        stash_created = bool(
            stash_reference
        )

        return {
            "stash_created": stash_created,
            "stash_reference": (
                stash_reference
            ),
            "stash_message": stash_message,
            "stash_output": output,
        }

    def _ensure_git_repository(self) -> None:
        if not (
            self.repo_root / ".git"
        ).exists():
            raise BootstrapEngineError(
                "Git 저장소가 연결되어 있지 않습니다."
            )

    def _current_branch(self) -> str:
        return self._git(
            [
                "branch",
                "--show-current",
            ]
        )["stdout"].strip()

    def _git(
        self,
        args: list[str],
        check: bool = True,
    ) -> dict[str, Any]:
        proc = subprocess.run(
            [
                "git",
                *args,
            ],
            cwd=self.repo_root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=180,
            check=False,
        )

        if (
            check
            and proc.returncode != 0
        ):
            raise BootstrapEngineError(
                "git "
                + " ".join(args)
                + " 실패:\n"
                + proc.stdout
                + "\n"
                + proc.stderr
            )

        return {
            "returncode": proc.returncode,
            "stdout": proc.stdout,
            "stderr": proc.stderr,
        }

    def _state_file(
        self,
        workflow_id: str,
    ) -> Path:
        return (
            BOOTSTRAP_STATE_DIR
            / f"{workflow_id}.json"
        )

    def _load_state(
        self,
        workflow_id: str,
    ) -> dict[str, Any] | None:
        state_file = self._state_file(
            workflow_id
        )

        if not state_file.exists():
            return None

        try:
            return json.loads(
                state_file.read_text(
                    encoding="utf-8"
                )
            )
        except (
            OSError,
            json.JSONDecodeError,
        ):
            return None

    def _save_state(
        self,
        workflow_id: str,
        state: dict[str, Any],
    ) -> None:
        state["updated_at"] = self._now()

        self._state_file(workflow_id).parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        self._state_file(workflow_id).write_text(
            json.dumps(
                state,
                ensure_ascii=False,
                indent=2,
                default=str,
            ),
            encoding="utf-8",
        )

    @staticmethod
    def _now() -> str:
        return datetime.now(
            timezone.utc
        ).isoformat()


bootstrap_engine = BootstrapEngine()
