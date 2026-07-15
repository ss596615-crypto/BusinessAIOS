from __future__ import annotations

import importlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tool_registry import ToolRecord, tool_registry


BASE_DIR = Path(__file__).resolve().parent


class CoreToolRegistrationError(RuntimeError):
    """핵심 Tool 등록 오류."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _compile_test(relative_file: str) -> dict[str, Any]:
    file_path = (BASE_DIR / relative_file).resolve()

    if not file_path.exists():
        return {
            "passed": False,
            "returncode": -1,
            "command": "",
            "stdout": "",
            "stderr": f"파일이 없습니다: {file_path}",
        }

    process = subprocess.run(
        [
            sys.executable,
            "-m",
            "py_compile",
            str(file_path),
        ],
        cwd=str(BASE_DIR),
        text=True,
        capture_output=True,
        timeout=120,
    )

    return {
        "passed": process.returncode == 0,
        "returncode": process.returncode,
        "command": (
            f'{sys.executable} -m py_compile "{file_path}"'
        ),
        "stdout": process.stdout,
        "stderr": process.stderr,
    }


def _import_test(
    module_name: str,
    function_name: str,
) -> dict[str, Any]:
    try:
        module = importlib.import_module(module_name)
        target = getattr(module, function_name, None)

        if target is None or not callable(target):
            raise CoreToolRegistrationError(
                f"호출 가능한 함수가 없습니다: "
                f"{module_name}:{function_name}"
            )

        return {
            "passed": True,
            "module": module_name,
            "function": function_name,
        }

    except Exception as exc:
        return {
            "passed": False,
            "module": module_name,
            "function": function_name,
            "error": f"{type(exc).__name__}: {exc}",
        }


def register_development_engine_tool() -> dict[str, Any]:
    compile_result = _compile_test(
        "development_engine_tool.py"
    )
    import_result = _import_test(
        "development_engine_tool",
        "run_tool",
    )

    passed = bool(
        compile_result.get("passed")
        and import_result.get("passed")
    )

    if not passed:
        raise CoreToolRegistrationError(
            "Development Engine Tool 자동 테스트 실패.\n"
            + json.dumps(
                {
                    "compile_test": compile_result,
                    "import_test": import_result,
                },
                ensure_ascii=False,
                indent=2,
            )
        )

    record = ToolRecord(
        tool_id="tool_development_engine",
        name="Development Engine Tool",
        category="development",
        description=(
            "기존 Business AI OS Development Engine을 호출하여 "
            "코드 분석, 전체 파일 수정, 자동 테스트, Git Commit을 "
            "수행하는 공식 실행 Tool"
        ),
        entrypoint="development_engine_tool:run_tool",
        version="1.0.0",
        status="active",
        reusable=True,
        approval_status="approved",
        created_reason=(
            "기존 development_engine.py를 재사용하여 직원이 "
            "Python 코드를 직접 수정하지 않고 공식 Tool을 통해 "
            "개발 업무를 수행하도록 하기 위해 등록"
        ),
        created_by_agent_id="system_core_registration",
        test_status="passed",
        test_command=str(
            compile_result.get("command", "")
        ),
        permissions=[
            "local_files",
            "git",
            "openai_agent",
        ],
        metadata={
            "core_tool": True,
            "adapter_file": "development_engine_tool.py",
            "wrapped_module": "development_engine.py",
            "compile_test": compile_result,
            "import_test": import_result,
            "registered_at": _now(),
        },
        created_at=_now(),
        updated_at=_now(),
    )

    registry_result = tool_registry.register_tool(
        record,
        require_approval=True,
        require_test_passed=True,
    )

    return {
        "status": "completed",
        "tool_id": "tool_development_engine",
        "test_result": {
            "compile_test": compile_result,
            "import_test": import_result,
        },
        "registry_result": registry_result,
        "registered_tool_count": len(
            tool_registry.export_registry().get(
                "tools",
                [],
            )
        ),
    }


def register_all_core_tools() -> dict[str, Any]:
    results = [
        register_development_engine_tool(),
    ]

    return {
        "status": "completed",
        "registered": results,
        "registered_tool_count": len(
            tool_registry.export_registry().get(
                "tools",
                [],
            )
        ),
    }


if __name__ == "__main__":
    print(
        json.dumps(
            register_all_core_tools(),
            ensure_ascii=False,
            indent=2,
        )
    )
