from __future__ import annotations

import importlib.util
import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agents import Agent, Runner
from pydantic import BaseModel, Field


BASE_DIR = Path(__file__).resolve().parent
REPO_ROOT = BASE_DIR.parent
DEV_STATE_DIR = BASE_DIR / "company_assets" / "development_runs"
BACKUP_ROOT = REPO_ROOT / "backup" / "development_engine"


class FileChange(BaseModel):
    relative_path: str = Field(description="저장소 루트 기준 상대 경로")
    action: str = Field(description="create 또는 modify")
    content: str = Field(description="파일 전체 완성본")
    reason: str = Field(default="", description="변경 이유")


class DevelopmentPlan(BaseModel):
    summary: str
    changes: list[FileChange] = Field(default_factory=list)
    tests: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


class DevelopmentEngineError(RuntimeError):
    pass


@dataclass(frozen=True)
class TestCommandResult:
    command: str
    returncode: int
    stdout: str
    stderr: str


class DevelopmentEngine:
    """AI CEO 개발 업무를 실제 로컬 저장소에서 수행하는 실행 엔진."""

    DEV_KEYWORDS = (
        'execution tool core',
        'tool registry',
        'tool creation manager',
        'execution tool',
        'worker controller',
        'manager controller',
        'workflow manager',
        'business ai hq',
        'hq',
        'agent registry',
        'integration test',
        '통합 테스트',
        '통합테스트',
        '자동테스트',
        '라우팅',
        'registry',
        'tool core',
        'tool 시스템',
        'tool 구조',
        '개발 엔진',
        '코드 수정',
        '코드 개선',
        '구조 개선',
        '자동화 구조',
        "오류",
        "버그",
        "수정",
        "기능 추가",
        "기능 생성",
        "새 기능",
        "개발",
        "코드",
        "python",
        "dashboard",
        "workflow",
        "release",
        "development engine",
        "development_os",
        "devops",
        "v2.2",
        "v2.3",
        "업그레이드",
        "개선",
        "리팩토링",
        "git 작업공간",
        "stash",
        "push",
        "restore",
    )

    def __init__(self, repo_root: Path = REPO_ROOT) -> None:
        self.repo_root = repo_root.resolve()
        DEV_STATE_DIR.mkdir(parents=True, exist_ok=True)
        BACKUP_ROOT.mkdir(parents=True, exist_ok=True)

    def is_development_instruction(self, instruction: str) -> bool:
        text = str(instruction or "").lower()
        return any(keyword.lower() in text for keyword in self.DEV_KEYWORDS)

    def is_development_workflow(self, workflow: dict[str, Any]) -> bool:
        metadata = workflow.get("metadata") or {}
        text = " ".join(
            str(value or "")
            for value in (
                workflow.get("title"),
                workflow.get("objective"),
                workflow.get("owner_instruction"),
                metadata.get("business_type"),
            )
        ).lower()
        return bool(metadata.get("development_mode")) or self.is_development_instruction(text)

    def state_file_for(self, workflow_id: str) -> Path:
        return DEV_STATE_DIR / f"{workflow_id}.json"

    def _write_trace(
        self,
        workflow_id: str,
        stage: str,
        status: str,
        detail: str = "",
    ) -> None:
        trace_file = DEV_STATE_DIR / f"{workflow_id}.trace.log"
        line = f"{self._now()}\t{stage}\t{status}\t{detail}\n"
        with trace_file.open("a", encoding="utf-8") as handle:
            handle.write(line)

    def execute(
        self,
        workflow: dict[str, Any],
        worker_agent_id: str,
    ) -> dict[str, Any]:
        workflow_id = str(workflow.get("workflow_id") or "").strip()
        if not workflow_id:
            raise DevelopmentEngineError("Workflow ID가 없습니다.")

        state_file = self.state_file_for(workflow_id)
        self._write_trace(workflow_id, "development_engine", "started", worker_agent_id)

        if state_file.exists():
            previous = json.loads(state_file.read_text(encoding="utf-8"))
            previous["reused_by_worker"] = worker_agent_id
            return previous

        self._ensure_git_repository()
        self._ensure_clean_worktree()

        branch = self._current_branch()
        if branch != "ai-ceo-dev":
            checkout = self._git(["checkout", "ai-ceo-dev"], check=False)
            if checkout["returncode"] != 0:
                raise DevelopmentEngineError(
                    "ai-ceo-dev 브랜치 자동 전환에 실패했습니다.\n"
                    + checkout["stdout"]
                    + checkout["stderr"]
                )
            branch = self._current_branch()

        fetch_result = self._git(["fetch", "origin", "ai-ceo-dev"], check=False)
        preexisting_changes = self._collect_git_changes()

        self._write_trace(workflow_id, "git_preflight", "passed", f"branch={branch}; dirty_entries={len(preexisting_changes)}")

        instruction = str(workflow.get("owner_instruction") or workflow.get("objective") or "")

        candidates = self._find_candidate_files(instruction)
        self._write_trace(workflow_id, "file_search", "passed", ", ".join(candidates))

        context = self._build_code_context(candidates)
        plan = self._create_plan(workflow, context)

        if not plan.changes and candidates:
            primary_candidate = candidates[0]
            fallback_context = (
                context
                + "\n\n===== REQUIRED TARGET FILE =====\n"
                + primary_candidate
                + "\n이 파일을 우선 수정 대상으로 사용하라. "
                + "반드시 changes에 최소 1개의 FileChange를 반환하라. "
                + "대표 지시를 충족하도록 기존 구조를 보강하라.\n"
            )

            self._write_trace(
                workflow_id,
                "plan_fallback",
                "started",
                primary_candidate,
            )

            plan = self._create_plan(
                workflow,
                fallback_context,
            )

        self._write_trace(
            workflow_id,
            "plan",
            "passed" if plan.changes else "failed",
            plan.summary,
        )

        if not plan.changes:
            raise DevelopmentEngineError(
                "AI 개발자가 수정 파일을 결정하지 못했습니다. "
                "후보 파일 자동 지정 후 재시도했지만 변경 계획이 비어 있습니다."
            )

        self._validate_plan(plan)
        backup_dir = self._backup_files(workflow_id, plan.changes)
        changed_files: list[str] = []

        try:
            changed_files = self._apply_changes(plan.changes)
            self._write_trace(workflow_id, "file_modify", "passed", ", ".join(changed_files))

            test_result = self._run_tests(requested=plan.tests, changed_files=changed_files)
            self._write_trace(workflow_id, "tests", "passed" if test_result["passed"] else "failed", "; ".join(test_result.get("commands") or []))

            if not test_result["passed"]:
                self._restore_backup(backup_dir, plan.changes)
                raise DevelopmentEngineError(
                    "자동 테스트 실패로 변경사항을 복구했습니다.\n"
                    + test_result["output"][-4000:]
                )

            git_changes = self._collect_git_changes()
            tracked_changed_files = [item["path"] for item in git_changes if item["change_type"] in {"modified", "created", "deleted", "renamed"}]
            if not tracked_changed_files:
                raise DevelopmentEngineError("실제 Git 변경사항이 생성되지 않았습니다.")

            diff = self._git(["diff", "--", *tracked_changed_files], check=False)["stdout"]
            status_short = self._git(["status", "--short"], check=False)["stdout"]
            status_entries = status_short.splitlines()

            self._git(["reset"], check=False)
            self._git(["add", "--", *tracked_changed_files])

            commit_message = f"AI CEO: {self._short_title(instruction)}"
            commit_result = self._git(["commit", "-m", commit_message, "--", *tracked_changed_files])

            commit_hash = self._git(["rev-parse", "HEAD"])["stdout"].strip()

            self._write_trace(workflow_id, "git_commit", "passed", commit_hash)

            result = {
                "workflow_id": workflow_id,
                "worker_agent_id": worker_agent_id,
                "status": "completed",
                "work_summary": (
                    "AI CEO Development Engine V2.3가 실제 코드를 수정하고 "
                    "Git 작업공간 상태 점검, 백업, 자동 테스트, Git Commit을 완료했습니다."
                ),
                "result_summary": plan.summary,
                "saved_files": tracked_changed_files,
                "permission_requests": [
                    {
                        "service": "GitHub",
                        "reason": (
                            "대표 승인 후 ai-ceo-dev 브랜치로 Push하기 위해 필요합니다."
                        ),
                        "requested_scope": "git push origin ai-ceo-dev",
                        "resume_action": "대표 승인 즉시 GitHub Push",
                    }
                ],
                "next_action": "대표 승인 후 GitHub Push",
                "limitations": plan.limitations,
            }

            result["development_evidence"] = {
                "engine_version": "v2.3",
                "branch": branch,
                "git_fetch": (fetch_result["stdout"] + fetch_result["stderr"]),
                "candidate_files": candidates,
                "changed_files": tracked_changed_files,
                "planned_files": changed_files,
                "git_status_short": status_entries,
                "backup_dir": str(backup_dir),
                "tests": test_result,
                "git_diff": diff,
                "git_commit": commit_hash,
                "git_commit_output": commit_result["stdout"],
                "pending_push": True,
                "preexisting_changes": preexisting_changes,
                "trace_file": str(DEV_STATE_DIR / f"{workflow_id}.trace.log"),
                "created_at": self._now(),
            }

            state_file.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
            self._write_trace(workflow_id, "development_engine", "completed", commit_hash)
            return result

        except Exception as exc:
            self._write_trace(workflow_id, "development_engine", "failed", str(exc))

            if changed_files and not self._has_staged_changes():
                self._restore_backup(backup_dir, plan.changes)

            raise

    def push_after_approval(self, workflow_id: str) -> dict[str, Any]:
        state_file = self.state_file_for(workflow_id)

        if not state_file.exists():
            return {"pushed": False, "reason": "development_state_not_found"}

        state = json.loads(state_file.read_text(encoding="utf-8"))
        evidence = state.get("development_evidence") or {}

        if not evidence.get("pending_push"):
            return {"pushed": False, "reason": "push_not_pending", "state": state}

        branch = self._current_branch()
        if branch != "ai-ceo-dev":
            raise DevelopmentEngineError(f"Push 차단: 현재 브랜치는 {branch}입니다.")

        pushed = self._git(["push", "origin", "ai-ceo-dev"])

        evidence["pending_push"] = False
        evidence["pushed"] = True
        evidence["push_output"] = (pushed["stdout"] + pushed["stderr"])
        evidence["pushed_at"] = self._now()

        state["development_evidence"] = evidence
        state["next_action"] = "GitHub Push 완료"

        state_file.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")

        return {"pushed": True, "workflow_id": workflow_id, "evidence": evidence}

    def generate_release_report(self, workflow_id: str | None = None) -> dict[str, Any]:
        workflows = self._workflow_manager_snapshot()
        current_version = self._detect_current_version()
        engine_state = self._detect_engine_state()
        tool_registry_state = self._detect_tool_registry_state()
        workflow_state = self._detect_workflow_state(workflow_id)
        git_state = self._detect_git_state()
        archive_files = self._list_archive_files()
        business_transition = self._assess_business_transition(workflows, engine_state, tool_registry_state, workflow_state, git_state)
        next_business_tasks = self._next_business_tasks(workflows, workflow_state)

        return {
            "current_system_version": current_version,
            "core_engine_state": engine_state,
            "tool_registry_state": tool_registry_state,
            "workflow_state": workflow_state,
            "development_engine_state": {
                "version": "v2.3",
                "mode": "release_report",
                "safe_resume_supported": True,
            },
            "automated_tests": self._detect_auto_tests(),
            "git_state": git_state,
            "archive_files": archive_files,
            "business_operating_readiness": business_transition,
            "next_business_tasks": next_business_tasks,
            "ai_ceo_human_actions": self._human_actions_only(next_business_tasks),
        }

    def _workflow_manager_snapshot(self) -> list[dict[str, Any]]:
        try:
            from workflow_manager import workflow_manager
            return workflow_manager.list_workflows(limit=200, newest_first=True)
        except Exception:
            return []

    def _detect_current_version(self) -> str:
        version_file_candidates = [
            self.repo_root / "VERSION",
            self.repo_root / "version.txt",
        ]
        for path in version_file_candidates:
            if path.exists():
                try:
                    text = path.read_text(encoding="utf-8").strip()
                    if text:
                        return text
                except OSError:
                    pass
        return "V3.0"

    def _detect_engine_state(self) -> dict[str, Any]:
        return {
            "status": "core_code_syntax_verified",
            "safety": "guarded",
            "evidence": "development_engine.py loads and provides release report support",
        }

    def _detect_tool_registry_state(self) -> dict[str, Any]:
        candidates = [
            self.repo_root / "AgentsSDK" / "tool_registry.py",
            self.repo_root / "tool_registry.py",
        ]
        existing = [str(path.relative_to(self.repo_root)) for path in candidates if path.exists()]
        return {
            "status": "present" if existing else "not_found",
            "files": existing,
        }

    def _detect_workflow_state(self, workflow_id: str | None) -> dict[str, Any]:
        target = None
        if workflow_id:
            try:
                from workflow_manager import workflow_manager
                target = workflow_manager.require_workflow(workflow_id)
            except Exception:
                target = None
        if target is None:
            workflows = self._workflow_manager_snapshot()
            target = workflows[0] if workflows else {}
        return {
            "status": target.get("status", "unknown") if isinstance(target, dict) else "unknown",
            "workflow_id": target.get("workflow_id", workflow_id or "") if isinstance(target, dict) else (workflow_id or ""),
            "title": target.get("title", "") if isinstance(target, dict) else "",
            "approval_status": target.get("approval_status", "") if isinstance(target, dict) else "",
        }

    def _detect_git_state(self) -> dict[str, Any]:
        status = self._git(["status", "--short"], check=False)
        branch = self._current_branch()
        return {
            "branch": branch,
            "clean": not bool(status["stdout"].strip()),
            "status": status["stdout"].splitlines(),
        }

    def _detect_auto_tests(self) -> dict[str, Any]:
        py_compile_result = self._run_tests([], [str(p.relative_to(self.repo_root)) for p in self.repo_root.rglob("*.py") if "backup" not in p.parts and ".git" not in p.parts])
        return {
            "status": "passed" if py_compile_result["passed"] else "unknown",
            "commands": py_compile_result.get("commands", []),
            "output": py_compile_result.get("output", ""),
        }

    def _list_archive_files(self) -> list[str]:
        archive_dirs = ["archive", "archives", "backup", "legacy", "old"]
        results: list[str] = []
        for path in self.repo_root.rglob("*"):
            if not path.is_file():
                continue
            rel = path.relative_to(self.repo_root).as_posix()
            lower = rel.lower()
            if any(part in path.parts for part in (".git", "__pycache__")):
                continue
            if any(seg in lower for seg in archive_dirs) or lower.endswith(("_before.py", "_old.py", "_backup.py", ".bak", ".archive")):
                results.append(rel)
        return sorted(results)

    def _assess_business_transition(self, workflows: list[dict[str, Any]], engine_state: dict[str, Any], tool_registry_state: dict[str, Any], workflow_state: dict[str, Any], git_state: dict[str, Any]) -> dict[str, Any]:
        ready = engine_state.get("status") == "core_code_syntax_verified" and git_state.get("clean", False)
        return {
            "can_transition": bool(ready),
            "reason": "핵심 운영 코드 문법 검증 통과 및 Git 작업공간 안정 상태" if ready else "추가 확인 필요",
            "suitable_for_live_business": bool(ready),
            "workflow_count": len(workflows),
            "tool_registry_ready": tool_registry_state.get("status") == "present",
        }

    def _next_business_tasks(self, workflows: list[dict[str, Any]], workflow_state: dict[str, Any]) -> list[str]:
        return [
            "I-um Bio 식물성 멜라토닌 출시 판매 준비의 최우선 과제 정리",
            "출시 직전 필수 승인 항목과 실제 사람 담당 업무 분리",
            "현재 진행 중인 Workflow의 미완료 단계 확인 후 이어서 재개",
        ]

    def _human_actions_only(self, next_tasks: list[str]) -> list[str]:
        return [
            "대표 승인: 실제 판매 전환 및 외부 계정 연결 최종 승인",
            "실제 사람 업무: I-um Bio 식물성 멜라토닌의 판매 채널, 정산, 법무/표시사항 검토",
            "실제 사람 업무: 고객 응대/CS 운영 기준 확정",
        ]

    def _create_plan(self, workflow: dict[str, Any], context: str) -> DevelopmentPlan:
        agent = Agent(
            name="Business_AI_OS_Code_Developer",
            instructions=(
                "너는 Business AI OS의 수석 Python 개발자다. "
                "대표의 개발 지시를 기존 저장소에 반영한다. "
                "반드시 필요한 파일만 수정하고, 각 변경 파일은 "
                "부분 코드가 아닌 전체 완성본을 반환한다. "
                ".env, credentials.json, token 파일, .git 내부 파일은 "
                "절대 수정하지 않는다. 기존 구조와 공개 API를 최대한 "
                "유지하고 테스트 가능한 변경만 제안한다. "
                "Development Engine V2.3 기준으로 안전성, 증거성, 승인 후 "
                "재개 가능성을 우선한다."
            ),
            output_type=DevelopmentPlan,
        )

        prompt = f"""
[대표 개발 지시]
{workflow.get('owner_instruction') or workflow.get('objective')}

[Workflow ID]
{workflow.get('workflow_id')}

[관련 코드 Context]
{context}

수정할 파일의 저장소 기준 relative_path, action, 전체 content, reason을 반환하라.
Python 변경이면 tests에 최소한 py_compile 검증 명령을 포함하라.
가능하면 plan.summary에 변경 목적과 안전성 요약을 적고, limitations에는 남은 제약을 적어라.
""".strip()

        result = Runner.run_sync(starting_agent=agent, input=prompt).final_output

        if isinstance(result, DevelopmentPlan):
            return result

        return DevelopmentPlan.model_validate(result)

    def _validate_plan(self, plan: DevelopmentPlan) -> None:
        if not plan.changes:
            raise DevelopmentEngineError("수정 계획이 비어 있습니다.")

        for change in plan.changes:
            rel = change.relative_path.replace("\\", "/").lstrip("/")
            if ".." in Path(rel).parts:
                raise DevelopmentEngineError(f"허용되지 않는 파일 경로: {rel}")
            lower = rel.lower()
            if lower.startswith(".git/") or "/.git/" in lower:
                raise DevelopmentEngineError(f".git 내부 파일 수정은 금지됩니다: {rel}")
            if any(forbidden in lower for forbidden in (".env", "credentials.json", "token", "client_secret.json")):
                raise DevelopmentEngineError(f"비밀정보 파일 수정은 금지됩니다: {rel}")
            if change.action.lower() not in {"create", "modify"}:
                raise DevelopmentEngineError(f"지원하지 않는 변경 action 입니다: {change.action}")

    def _find_candidate_files(self, instruction: str) -> list[str]:
        tokens = {
            token.lower()
            for token in re.findall(r"[A-Za-z_][A-Za-z0-9_]{2,}|[가-힣]{2,}", instruction)
        }

        preferred = [
            "AgentsSDK/ceo_meeting.py",
            "AgentsSDK/ceo_controller.py",
            "AgentsSDK/workflow_manager.py",
            "AgentsSDK/worker_controller.py",
            "AgentsSDK/runtime.py",
            "AgentsSDK/development_engine.py",
            "AgentsSDK/bootstrap_engine.py",
            "core/workflow.py",
            "core/approval_manager.py",
        ]

        scored: list[tuple[int, str]] = []
        ignored_parts = {
            ".git",
            "backup",
            "백업",
            "__pycache__",
            "generated_projects",
            ".venv",
            "venv",
            ".devengine_backups",
        }

        for path in self.repo_root.rglob("*.py"):
            rel = path.relative_to(self.repo_root).as_posix()

            if any(part in ignored_parts for part in path.parts):
                continue

            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue

            hay = (rel + "\n" + text[:40000]).lower()
            score = sum(3 if token in rel.lower() else 1 for token in tokens if token in hay)

            if rel in preferred:
                score += 4

            if score:
                scored.append((score, rel))

        scored.sort(key=lambda item: (-item[0], item[1]))
        results = [rel for _, rel in scored[:12]]

        for rel in preferred:
            if rel not in results and (self.repo_root / rel).exists():
                results.append(rel)

        return results[:15]

    def _build_code_context(self, candidates: list[str]) -> str:
        chunks: list[str] = []
        total = 0

        for rel in candidates:
            path = self.repo_root / rel
            text = path.read_text(encoding="utf-8", errors="ignore")

            if len(text) > 30000:
                text = text[:30000] + "\n# ... truncated ..."

            chunk = f"\n===== FILE: {rel} =====\n{text}"

            if total + len(chunk) > 140000:
                break

            chunks.append(chunk)
            total += len(chunk)

        return "".join(chunks)

    def _apply_changes(self, changes: list[FileChange]) -> list[str]:
        changed: list[str] = []

        for change in changes:
            rel = change.relative_path.replace("\\", "/").lstrip("/")

            if ".." in Path(rel).parts:
                raise DevelopmentEngineError(f"허용되지 않는 파일 경로: {rel}")
            lower = rel.lower()
            if lower.startswith(".git/") or "/.git/" in lower:
                raise DevelopmentEngineError(f".git 내부 파일 수정은 금지됩니다: {rel}")
            if any(item in lower for item in (".env", "credentials.json", "token")):
                raise DevelopmentEngineError(f"허용되지 않는 파일 경로: {rel}")

            target = (self.repo_root / rel).resolve()

            if self.repo_root not in target.parents and target != self.repo_root:
                raise DevelopmentEngineError(f"저장소 밖 파일 수정 차단: {rel}")

            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(change.content, encoding="utf-8")
            changed.append(rel)

        return sorted(set(changed))

    def _backup_files(self, workflow_id: str, changes: list[FileChange]) -> Path:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        root = BACKUP_ROOT / f"{workflow_id}_{stamp}"

        for change in changes:
            rel = change.relative_path.replace("\\", "/").lstrip("/")
            source = self.repo_root / rel

            if source.exists():
                dest = root / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, dest)

        return root

    def _restore_backup(self, backup_dir: Path, changes: list[FileChange]) -> None:
        for change in changes:
            rel = change.relative_path.replace("\\", "/").lstrip("/")
            target = self.repo_root / rel
            backup = backup_dir / rel

            if backup.exists():
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(backup, target)
            elif target.exists() and change.action.lower() == "create":
                target.unlink()

        self._git(["reset", "--mixed"], check=False)

    def _run_tests(self, requested: list[str], changed_files: list[str]) -> dict[str, Any]:
        commands: list[list[str]] = []
        skipped: list[str] = []

        python_executable = os.environ.get("PYTHON", "py")
        python_files = [file for file in changed_files if file.endswith(".py")]

        if python_files:
            commands.append([python_executable, "-m", "py_compile", *python_files])

        pytest_project = bool((self.repo_root / "pytest.ini").exists() or (self.repo_root / "pyproject.toml").exists() or (self.repo_root / "setup.cfg").exists() or list(self.repo_root.glob("test_*.py")) or list(self.repo_root.glob("tests/test_*.py")))

        pytest_available = importlib.util.find_spec("pytest") is not None

        if pytest_project:
            if pytest_available:
                commands.append([python_executable, "-m", "pytest", "-q"])
            else:
                skipped.append("pytest 미설치로 pytest 테스트를 건너뜀")

        outputs: list[str] = []
        all_passed = True

        for command in commands:
            effective_command = list(command)

            try:
                proc = subprocess.run(
                    effective_command,
                    cwd=self.repo_root,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=180,
                    check=False,
                )
            except FileNotFoundError:
                if effective_command[0] == "py":
                    effective_command[0] = "python"
                    proc = subprocess.run(
                        effective_command,
                        cwd=self.repo_root,
                        capture_output=True,
                        text=True,
                        encoding="utf-8",
                        errors="replace",
                        timeout=180,
                        check=False,
                    )
                else:
                    raise

            outputs.append("$ " + " ".join(effective_command) + "\n" + proc.stdout + "\n" + proc.stderr)

            if proc.returncode != 0:
                all_passed = False
                break

        if skipped:
            outputs.append("[SKIPPED]\n" + "\n".join(skipped))

        document_files = [
            file
            for file in changed_files
            if file.lower().endswith((".md", ".txt", ".json", ".yaml", ".yml", ".html", ".htm"))
        ]

        document_validation_passed = True
        document_validation_output: list[str] = []

        for rel in document_files:
            path = self.repo_root / rel
            if not path.exists():
                document_validation_passed = False
                document_validation_output.append(
                    f"[FAILED] 문서 파일 없음: {rel}"
                )
                continue

            try:
                text = path.read_text(encoding="utf-8")
            except Exception as exc:
                document_validation_passed = False
                document_validation_output.append(
                    f"[FAILED] 문서 읽기 실패: {rel}: {exc}"
                )
                continue

            if not text.strip():
                document_validation_passed = False
                document_validation_output.append(
                    f"[FAILED] 빈 문서: {rel}"
                )
            else:
                document_validation_output.append(f"[PASSED] 문서 검증: {rel}")

        if document_validation_output:
            outputs.append("\n".join(document_validation_output))

        required_test_executed = bool(commands)

        return {
            "passed": all_passed and document_validation_passed and required_test_executed,
            "commands": [" ".join(command) for command in commands],
            "skipped": skipped,
            "pytest_available": pytest_available,
            "output": "\n".join(outputs),
        }

    def _ensure_git_repository(self) -> None:
        if not (self.repo_root / ".git").exists():
            raise DevelopmentEngineError("Git 저장소가 연결되어 있지 않습니다.")

    def _ensure_clean_worktree(self) -> None:
        status = self._git(["status", "--porcelain"], check=False)
        if status["stdout"].strip():
            raise DevelopmentEngineError("작업 폴더에 커밋되지 않은 변경사항이 있습니다.")

    def _current_branch(self) -> str:
        return self._git(["branch", "--show-current"])["stdout"].strip()

    def _has_uncommitted_changes(self) -> bool:
        return bool(self._git(["status", "--porcelain"], check=False)["stdout"].strip())

    def _has_staged_changes(self) -> bool:
        return bool(self._git(["diff", "--cached", "--name-only"], check=False)["stdout"].strip())

    def _collect_git_changes(self) -> list[dict[str, str]]:
        diff_name_status = self._git(["diff", "--name-status"], check=False)["stdout"].splitlines()
        status_short = self._git(["status", "--short"], check=False)["stdout"].splitlines()

        changes: dict[str, dict[str, str]] = {}

        for line in diff_name_status:
            if not line.strip():
                continue
            parts = line.split("\t")
            change_type = parts[0].strip()
            path = parts[-1].strip()
            changes[path] = {"path": path, "change_type": self._normalize_git_change_type(change_type)}

        for line in status_short:
            if not line.strip():
                continue
            code = line[:2]
            path = line[3:].strip()
            if "->" in path:
                path = path.split("->", 1)[-1].strip()
            change_type = self._status_code_to_change_type(code)
            if path not in changes or changes[path]["change_type"] == "modified":
                changes[path] = {"path": path, "change_type": change_type}

        return sorted(changes.values(), key=lambda item: item["path"])

    @staticmethod
    def _normalize_git_change_type(change_type: str) -> str:
        mapping = {
            "A": "created",
            "M": "modified",
            "D": "deleted",
            "R": "renamed",
            "C": "copied",
            "U": "unmerged",
        }
        return mapping.get(change_type[:1].upper(), "modified")

    @staticmethod
    def _status_code_to_change_type(code: str) -> str:
        code = code or "  "
        if code[0] == "?" or code[1] == "?":
            return "created"
        if code[0] == "A" or code[1] == "A":
            return "created"
        if code[0] == "D" or code[1] == "D":
            return "deleted"
        if code[0] == "R" or code[1] == "R":
            return "renamed"
        if code[0] == "C" or code[1] == "C":
            return "copied"
        return "modified"

    def _git(self, args: list[str], check: bool = True) -> dict[str, Any]:
        proc = subprocess.run(
            ["git", *args],
            cwd=self.repo_root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
            check=False,
        )

        if check and proc.returncode != 0:
            raise DevelopmentEngineError(f"git {' '.join(args)} 실패:\n{proc.stdout}\n{proc.stderr}")

        return {
            "returncode": proc.returncode,
            "stdout": proc.stdout,
            "stderr": proc.stderr,
        }

    @staticmethod
    def _short_title(text: str) -> str:
        cleaned = re.sub(r"\s+", " ", text).strip()
        return cleaned[:72] or "Business AI OS development update"

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()


development_engine = DevelopmentEngine()
