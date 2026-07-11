from __future__ import annotations

import argparse
import json
import re
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from openai import OpenAI


ROOT = Path(r"C:\DevelopmentEngine")
MODEL = os.getenv("OPENAI_MODEL", "gpt-5.2")
MAX_FILE_BYTES = 120_000
MAX_CONTEXT_CHARS = 180_000

ALLOWED_SUFFIXES = {
    ".py", ".md", ".txt", ".json", ".yaml", ".yml", ".toml",
    ".html", ".css", ".js", ".jsx", ".ts", ".tsx", ".ini", ".cfg",
}

EXCLUDED_DIRS = {
    ".git", ".venv", "venv", "__pycache__", ".pytest_cache",
    ".mypy_cache", ".ruff_cache", "node_modules", "dist", "build",
    ".devengine_backups",
}

BLOCKED_NAMES = {
    ".env", "credentials.json", "client_secret.json",
}

BLOCKED_NAME_FRAGMENTS = {
    "token", "secret", "credential", ".pem", ".key", ".p12", ".pickle",
}


@dataclass
class CommandResult:
    command: str
    returncode: int
    stdout: str
    stderr: str


def run_command(command: list[str], cwd: Path, timeout: int = 300) -> CommandResult:
    completed = subprocess.run(
        command,
        cwd=str(cwd),
        text=True,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )
    return CommandResult(
        command=" ".join(command),
        returncode=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
    )


def is_blocked(path: Path) -> bool:
    name = path.name.lower()
    if name in BLOCKED_NAMES:
        return True
    return any(fragment in name for fragment in BLOCKED_NAME_FRAGMENTS)


def is_allowed_file(path: Path) -> bool:
    if not path.is_file():
        return False
    if path.suffix.lower() not in ALLOWED_SUFFIXES:
        return False
    if is_blocked(path):
        return False
    if path.stat().st_size > MAX_FILE_BYTES:
        return False
    return True


def collect_repository_context(root: Path) -> str:
    chunks: list[str] = []
    total = 0

    for path in sorted(root.rglob("*")):
        if any(part in EXCLUDED_DIRS for part in path.parts):
            continue
        if not is_allowed_file(path):
            continue

        rel = path.relative_to(root).as_posix()
        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue

        block = f"\n--- FILE: {rel} ---\n{content}\n"
        if total + len(block) > MAX_CONTEXT_CHARS:
            break
        chunks.append(block)
        total += len(block)

    return "".join(chunks)


def ensure_repository_ready(root: Path) -> None:
    if not root.exists():
        raise RuntimeError(f"프로젝트 폴더가 없습니다: {root}")
    if not (root / ".git").exists():
        raise RuntimeError(f"Git 저장소가 아닙니다: {root}")

    branch = run_command(["git", "branch", "--show-current"], root)
    if branch.returncode != 0:
        raise RuntimeError(branch.stderr.strip() or "현재 Git 브랜치를 확인할 수 없습니다.")

    current_branch = branch.stdout.strip()
    if current_branch != "ai-ceo-dev":
        raise RuntimeError(
            f"현재 브랜치는 '{current_branch}'입니다. "
            "안전을 위해 ai-ceo-dev 브랜치에서만 실행할 수 있습니다."
        )

    status = run_command(["git", "status", "--porcelain"], root)
    if status.returncode != 0:
        raise RuntimeError(status.stderr.strip() or "Git 상태를 확인할 수 없습니다.")

    if status.stdout.strip():
        raise RuntimeError(
            "작업 폴더에 커밋되지 않은 변경사항이 있습니다.\n"
            "먼저 커밋하거나 되돌린 뒤 다시 실행하세요.\n\n"
            + status.stdout
        )


def parse_json_response(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[1]
        cleaned = cleaned.rsplit("```", 1)[0]
    data = json.loads(cleaned)

    if not isinstance(data, dict):
        raise ValueError("AI 응답이 JSON 객체가 아닙니다.")
    if "files" not in data or not isinstance(data["files"], list):
        raise ValueError("AI 응답에 files 목록이 없습니다.")
    return data


def request_change_plan(
    client: OpenAI,
    instruction: str,
    repo_context: str,
    previous_error: str | None = None,
) -> dict[str, Any]:
    error_section = ""
    if previous_error:
        error_section = f"""
이전 실행은 아래 오류로 실패했다.
오류를 해결하도록 수정안을 다시 작성하라.

{previous_error}
"""

    prompt = f"""
당신은 로컬 Git 저장소를 수정하는 수석 Python 개발자다.

사용자 지시:
{instruction}

규칙:
1. 기존 구조를 우선 재사용한다.
2. 필요한 파일만 수정한다.
3. 비밀정보 파일(.env, credentials, token, pickle, key)은 절대 수정하지 않는다.
4. 파일 경로는 저장소 루트 기준 상대 경로만 사용한다.
5. 응답은 설명 없이 JSON 하나만 출력한다.
6. 파일을 수정할 때는 변경 후 전체 파일 내용을 content에 넣는다.
7. 새 파일 생성도 허용한다.
8. 파일 삭제는 금지한다.
9. README 같은 단순 작업도 실제 파일 수정으로 수행한다.
10. 사용자가 파일명을 명시하면 그 파일만 수정한다.
11. 요청과 무관한 *_old.py, 백업 파일, 레거시 파일은 절대 수정하지 않는다.
12. test_commands는 참고용이며 실제 테스트는 엔진이 변경 파일 기준으로 결정한다.

응답 형식:
{{
  "summary": "수정 요약",
  "files": [
    {{
      "path": "README.md",
      "content": "변경 후 전체 파일 내용"
    }}
  ],
  "test_commands": [
    ["py", "-m", "compileall", "."]
  ],
  "commit_message": "짧고 명확한 영문 또는 한글 커밋 메시지"
}}

{error_section}

현재 저장소 파일:
{repo_context}
"""

    response = client.responses.create(
        model=MODEL,
        input=prompt,
    )
    return parse_json_response(response.output_text)


def extract_explicit_paths(instruction: str) -> set[str]:
    matches = re.findall(
        r"(?i)(?:[A-Za-z0-9_.-]+/)*[A-Za-z0-9_.-]+\.(?:py|md|txt|json|yaml|yml|toml|html|css|js|jsx|ts|tsx|ini|cfg)",
        instruction,
    )
    return {item.replace("\\", "/") for item in matches}


def validate_plan(plan: dict[str, Any], root: Path, instruction: str) -> None:
    if not plan["files"]:
        raise ValueError("수정 대상 파일이 없습니다.")

    explicit_paths = extract_explicit_paths(instruction)

    for item in plan["files"]:
        if not isinstance(item, dict):
            raise ValueError("files 항목 형식이 잘못되었습니다.")
        rel = item.get("path")
        content = item.get("content")
        if not isinstance(rel, str) or not rel.strip():
            raise ValueError("파일 경로가 비어 있습니다.")
        if not isinstance(content, str):
            raise ValueError(f"{rel}: content가 문자열이 아닙니다.")

        normalized_rel = rel.replace("\\", "/")
        if explicit_paths and normalized_rel not in explicit_paths:
            raise ValueError(
                f"지시에 명시되지 않은 파일 수정은 허용하지 않습니다: {normalized_rel}. "
                f"허용 파일: {sorted(explicit_paths)}"
            )

        target = (root / rel).resolve()
        try:
            target.relative_to(root.resolve())
        except ValueError as exc:
            raise ValueError(f"저장소 밖의 파일은 수정할 수 없습니다: {rel}") from exc

        if is_blocked(target):
            raise ValueError(f"보안상 수정할 수 없는 파일입니다: {rel}")

def apply_plan(plan: dict[str, Any], root: Path) -> tuple[Path, list[str]]:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_root = root / ".devengine_backups" / timestamp
    backup_root.mkdir(parents=True, exist_ok=True)

    changed: list[str] = []

    for item in plan["files"]:
        rel = Path(item["path"])
        target = root / rel
        backup = backup_root / rel

        if target.exists():
            backup.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(target, backup)

        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(item["content"], encoding="utf-8")
        changed.append(rel.as_posix())

    return backup_root, changed


def rollback(root: Path, backup_root: Path, changed: list[str]) -> None:
    for rel_str in changed:
        rel = Path(rel_str)
        target = root / rel
        backup = backup_root / rel
        if backup.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(backup, target)
        elif target.exists():
            target.unlink()


def run_tests(plan: dict[str, Any], root: Path, changed: list[str]) -> list[CommandResult]:
    results: list[CommandResult] = []

    python_files = [item for item in changed if item.lower().endswith(".py")]
    for rel in python_files:
        result = run_command(["py", "-m", "py_compile", rel], root, timeout=120)
        results.append(result)
        if result.returncode != 0:
            return results

    # 비코드 파일만 수정한 경우에는 저장·diff 검증을 테스트로 사용합니다.
    if not python_files:
        diff = run_command(["git", "diff", "--check"], root, timeout=120)
        results.append(diff)
        if diff.returncode != 0:
            return results

        for rel in changed:
            target = root / rel
            if not target.exists():
                results.append(
                    CommandResult(
                        command=f"verify {rel}",
                        returncode=1,
                        stdout="",
                        stderr=f"수정 대상 파일이 존재하지 않습니다: {rel}",
                    )
                )
                return results

    return results

def commit_changes(plan: dict[str, Any], root: Path) -> str:
    add = run_command(["git", "add", "."], root)
    if add.returncode != 0:
        raise RuntimeError(add.stderr.strip() or "git add 실패")

    diff = run_command(["git", "diff", "--cached", "--quiet"], root)
    if diff.returncode == 0:
        raise RuntimeError("실제 변경사항이 없어 커밋하지 않았습니다.")

    message = str(plan.get("commit_message") or "Development Engine automated update").strip()
    commit = run_command(["git", "commit", "-m", message], root)
    if commit.returncode != 0:
        raise RuntimeError(commit.stderr.strip() or commit.stdout.strip() or "git commit 실패")

    sha = run_command(["git", "rev-parse", "HEAD"], root)
    if sha.returncode != 0:
        raise RuntimeError(sha.stderr.strip() or "commit hash 확인 실패")
    return sha.stdout.strip()


def write_evidence(
    root: Path,
    instruction: str,
    plan: dict[str, Any],
    changed: list[str],
    test_results: list[CommandResult],
    commit_hash: str,
) -> Path:
    evidence_dir = root / "development_evidence"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    filename = datetime.now().strftime("%Y%m%d_%H%M%S") + "_evidence.json"
    path = evidence_dir / filename

    payload = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "instruction": instruction,
        "model": MODEL,
        "summary": plan.get("summary", ""),
        "changed_files": changed,
        "tests": [
            {
                "command": item.command,
                "returncode": item.returncode,
                "stdout": item.stdout[-8000:],
                "stderr": item.stderr[-8000:],
            }
            for item in test_results
        ],
        "commit_hash": commit_hash,
        "push_performed": False,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description="Development Engine MVP V1")
    parser.add_argument("instruction", nargs="*", help="수행할 개발 지시")
    args = parser.parse_args()

    instruction = " ".join(args.instruction).strip()
    if not instruction:
        instruction = input("개발 지시를 입력하세요: ").strip()
    if not instruction:
        print("[실패] 개발 지시가 비어 있습니다.")
        return 1

    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        print("[실패] OPENAI_API_KEY 환경변수가 없습니다.")
        print("C:\\DevelopmentEngine\\.env 또는 Windows 환경변수에 API Key를 설정하세요.")
        return 1

    try:
        ensure_repository_ready(ROOT)
        client = OpenAI(api_key=api_key)
        repo_context = collect_repository_context(ROOT)
        if not repo_context.strip():
            raise RuntimeError("분석할 저장소 파일이 없습니다.")

        previous_error: str | None = None

        for attempt in range(1, 4):
            print(f"[{attempt}/3] AI 수정안 생성 중...")
            plan = request_change_plan(client, instruction, repo_context, previous_error)
            validate_plan(plan, ROOT, instruction)

            backup_root, changed = apply_plan(plan, ROOT)
            print("[수정]", ", ".join(changed))

            test_results = run_tests(plan, ROOT, changed)
            failed = next((r for r in test_results if r.returncode != 0), None)

            if failed is None:
                commit_hash = commit_changes(plan, ROOT)
                evidence = write_evidence(
                    ROOT, instruction, plan, changed, test_results, commit_hash
                )
                print("[성공] 자동 수정 및 Git commit 완료")
                print("[수정 파일]", ", ".join(changed))
                print("[Commit]", commit_hash)
                print("[Evidence]", evidence)
                print("[안내] 이 MVP는 안전을 위해 git push를 자동 실행하지 않습니다.")
                return 0

            previous_error = (
                f"명령: {failed.command}\n"
                f"종료코드: {failed.returncode}\n"
                f"표준출력:\n{failed.stdout}\n"
                f"표준오류:\n{failed.stderr}"
            )
            print("[테스트 실패] 자동 복구 후 재시도합니다.")
            rollback(ROOT, backup_root, changed)
            run_command(["git", "reset", "--hard", "HEAD"], ROOT)
            time.sleep(1)

        print("[실패] 자동 수정 3회 후에도 테스트를 통과하지 못했습니다.")
        return 2

    except Exception as exc:
        print(f"[실패] {type(exc).__name__}: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
