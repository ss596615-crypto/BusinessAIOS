from __future__ import annotations

import ast
import hashlib
import json
import os
import re
import shutil
import subprocess
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


class DevelopmentEngine:
    """AI CEO 개발 업무를 실제 로컬 저장소에서 수행하는 엔진."""

    DEV_KEYWORDS = (
        "오류", "버그", "수정", "기능 추가", "기능 생성", "새 기능",
        "개발", "코드", "python", "dashboard", "workflow", "release",
        "development engine", "development_os", "devops",
    )

    def __init__(self, repo_root: Path = REPO_ROOT) -> None:
        self.repo_root = repo_root.resolve()
        DEV_STATE_DIR.mkdir(parents=True, exist_ok=True)
        BACKUP_ROOT.mkdir(parents=True, exist_ok=True)

    def is_development_workflow(self, workflow: dict[str, Any]) -> bool:
        metadata = workflow.get("metadata") or {}
        text = " ".join(
            str(x or "") for x in (
                workflow.get("title"), workflow.get("objective"),
                workflow.get("owner_instruction"), metadata.get("business_type"),
            )
        ).lower()
        return any(keyword.lower() in text for keyword in self.DEV_KEYWORDS)

    def execute(self, workflow: dict[str, Any], worker_agent_id: str) -> dict[str, Any]:
        workflow_id = str(workflow.get("workflow_id") or "").strip()
        if not workflow_id:
            raise DevelopmentEngineError("Workflow ID가 없습니다.")

        state_file = DEV_STATE_DIR / f"{workflow_id}.json"
        if state_file.exists():
            previous = json.loads(state_file.read_text(encoding="utf-8"))
            previous["reused_by_worker"] = worker_agent_id
            return previous

        self._ensure_git_repository()
        branch = self._current_branch()
        if branch != "ai-ceo-dev":
            raise DevelopmentEngineError(
                f"AI 개발은 ai-ceo-dev 브랜치에서만 허용됩니다. 현재 브랜치: {branch}"
            )

        if self._has_uncommitted_changes():
            raise DevelopmentEngineError(
                "커밋되지 않은 기존 변경사항이 있습니다. 먼저 commit 또는 stash 후 다시 실행하세요."
            )

        instruction = str(workflow.get("owner_instruction") or workflow.get("objective") or "")
        candidates = self._find_candidate_files(instruction)
        context = self._build_code_context(candidates)
        plan = self._create_plan(workflow, context)
        if not plan.changes:
            raise DevelopmentEngineError("AI 개발자가 수정 파일을 결정하지 못했습니다.")

        backup_dir = self._backup_files(workflow_id, plan.changes)
        changed_files: list[str] = []
        try:
            changed_files = self._apply_changes(plan.changes)
            test_result = self._run_tests(plan.tests, changed_files)
            if not test_result["passed"]:
                self._restore_backup(backup_dir, plan.changes)
                raise DevelopmentEngineError(
                    "자동 테스트 실패로 변경사항을 복구했습니다.\n" + test_result["output"][-4000:]
                )

            diff = self._git(["diff", "--", *changed_files], check=False)["stdout"]
            if not diff.strip():
                raise DevelopmentEngineError("실제 Git 변경사항이 생성되지 않았습니다.")

            self._git(["add", "--", *changed_files])
            commit_message = f"AI CEO: {self._short_title(instruction)}"
            commit_result = self._git(["commit", "-m", commit_message])
            commit_hash = self._git(["rev-parse", "HEAD"])["stdout"].strip()

            result = {
                "workflow_id": workflow_id,
                "worker_agent_id": worker_agent_id,
                "status": "completed",
                "work_summary": "AI CEO Development Engine이 실제 코드를 수정하고 테스트 및 Git commit을 완료했습니다.",
                "result_summary": plan.summary,
                "saved_files": changed_files,
                "permission_requests": [{
                    "service": "GitHub",
                    "reason": "대표 승인 후 ai-ceo-dev 브랜치로 push하기 위해 필요합니다.",
                    "requested_scope": "git push origin ai-ceo-dev",
                    "resume_action": "대표 승인 즉시 GitHub push",
                }],
                "next_action": "대표 승인 후 GitHub push",
                "limitations": plan.limitations,
                "development_evidence": {
                    "branch": branch,
                    "candidate_files": candidates,
                    "changed_files": changed_files,
                    "backup_dir": str(backup_dir),
                    "tests": test_result,
                    "git_diff": diff,
                    "git_commit": commit_hash,
                    "git_commit_output": commit_result["stdout"],
                    "pending_push": True,
                    "created_at": self._now(),
                },
            }
            state_file.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
            return result
        except Exception:
            if changed_files and not self._has_staged_changes():
                self._restore_backup(backup_dir, plan.changes)
            raise

    def push_after_approval(self, workflow_id: str) -> dict[str, Any]:
        state_file = DEV_STATE_DIR / f"{workflow_id}.json"
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
        evidence["push_output"] = pushed["stdout"] + pushed["stderr"]
        evidence["pushed_at"] = self._now()
        state["development_evidence"] = evidence
        state["next_action"] = "GitHub push 완료"
        state_file.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        return {"pushed": True, "workflow_id": workflow_id, "evidence": evidence}

    def _create_plan(self, workflow: dict[str, Any], context: str) -> DevelopmentPlan:
        agent = Agent(
            name="Business_AI_OS_Code_Developer",
            instructions=(
                "너는 Business AI OS의 수석 Python 개발자다. 대표의 개발 지시를 기존 저장소에 반영한다. "
                "반드시 필요한 파일만 수정하고, 각 변경 파일은 일부 코드가 아니라 전체 완성본을 반환한다. "
                "절대 .env, credentials.json, token 파일, .git 내부 파일을 수정하지 않는다. "
                "기존 구조와 공개 API를 최대한 유지한다. 테스트 가능한 변경만 제안한다."
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
""".strip()
        result = Runner.run_sync(starting_agent=agent, input=prompt).final_output
        return result if isinstance(result, DevelopmentPlan) else DevelopmentPlan.model_validate(result)

    def _find_candidate_files(self, instruction: str) -> list[str]:
        tokens = {t.lower() for t in re.findall(r"[A-Za-z_][A-Za-z0-9_]{2,}|[가-힣]{2,}", instruction)}
        preferred = [
            "AgentsSDK/ceo_meeting.py", "AgentsSDK/ceo_controller.py",
            "AgentsSDK/workflow_manager.py", "AgentsSDK/worker_controller.py",
            "AgentsSDK/runtime.py", "core/workflow.py", "core/approval_manager.py",
        ]
        scored: list[tuple[int, str]] = []
        ignored_parts = {".git", "backup", "백업", "__pycache__", "generated_projects", ".venv", "venv"}
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
        forbidden = (".env", "credentials.json", "token", ".git/")
        for change in changes:
            rel = change.relative_path.replace("\\", "/").lstrip("/")
            if ".." in Path(rel).parts or any(x in rel.lower() for x in forbidden):
                raise DevelopmentEngineError(f"허용되지 않는 파일 경로: {rel}")
            target = (self.repo_root / rel).resolve()
            if self.repo_root not in target.parents:
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
        python_files = [f for f in changed_files if f.endswith(".py")]
        if python_files:
            commands.append([os.environ.get("PYTHON", "py"), "-m", "py_compile", *python_files])
        if (self.repo_root / "pytest.ini").exists() or list(self.repo_root.glob("test_*.py")):
            commands.append([os.environ.get("PYTHON", "py"), "-m", "pytest", "-q"])

        outputs: list[str] = []
        all_passed = True
        for command in commands:
            try:
                proc = subprocess.run(
                    command, cwd=self.repo_root, capture_output=True, text=True,
                    encoding="utf-8", errors="replace", timeout=180, check=False,
                )
            except FileNotFoundError:
                if command[0] == "py":
                    command[0] = "python"
                    proc = subprocess.run(command, cwd=self.repo_root, capture_output=True, text=True, timeout=180, check=False)
                else:
                    raise
            outputs.append(f"$ {' '.join(command)}\n{proc.stdout}\n{proc.stderr}")
            if proc.returncode != 0:
                all_passed = False
                break
        return {"passed": all_passed and bool(commands), "commands": [" ".join(c) for c in commands], "output": "\n".join(outputs)}

    def _ensure_git_repository(self) -> None:
        if not (self.repo_root / ".git").exists():
            raise DevelopmentEngineError("Git 저장소가 연결되어 있지 않습니다.")

    def _current_branch(self) -> str:
        return self._git(["branch", "--show-current"])["stdout"].strip()

    def _has_uncommitted_changes(self) -> bool:
        return bool(self._git(["status", "--porcelain"], check=False)["stdout"].strip())

    def _has_staged_changes(self) -> bool:
        return bool(self._git(["diff", "--cached", "--name-only"], check=False)["stdout"].strip())

    def _git(self, args: list[str], check: bool = True) -> dict[str, Any]:
        proc = subprocess.run(["git", *args], cwd=self.repo_root, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120, check=False)
        if check and proc.returncode != 0:
            raise DevelopmentEngineError(f"git {' '.join(args)} 실패:\n{proc.stdout}\n{proc.stderr}")
        return {"returncode": proc.returncode, "stdout": proc.stdout, "stderr": proc.stderr}

    @staticmethod
    def _short_title(text: str) -> str:
        cleaned = re.sub(r"\s+", " ", text).strip()
        return cleaned[:72] or "Business AI OS development update"

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()


development_engine = DevelopmentEngine()
