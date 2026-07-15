from __future__ import annotations

import importlib
import inspect
import json
import subprocess
import sys
import traceback
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from tool_registry import (
    ToolNotFoundError,
    ToolRegistry,
    tool_registry,
)


# =========================================================
# Paths
# =========================================================

BASE_DIR = Path(__file__).resolve().parent
ASSETS_DIR = BASE_DIR / "company_assets"
EXECUTION_LOG_DIR = ASSETS_DIR / "tool_executions"


# =========================================================
# Errors
# =========================================================

class ExecutionToolCoreError(RuntimeError):
    """Base error for Tool execution."""


class ToolExecutionBlockedError(ExecutionToolCoreError):
    """Raised when a Tool is not eligible for execution."""


class ToolEntrypointError(ExecutionToolCoreError):
    """Raised when a Tool entrypoint cannot be loaded."""


class ToolExecutionError(ExecutionToolCoreError):
    """Raised when a Tool execution fails."""


# =========================================================
# Execution Record
# =========================================================

@dataclass
class ToolExecutionRecord:
    execution_id: str
    workflow_id: str
    worker_agent_id: str
    tool_id: str
    tool_version: str
    entrypoint: str
    status: str
    input_data: dict[str, Any]
    output_data: Any
    error: str
    started_at: str
    completed_at: str


# =========================================================
# Execution Tool Core
# =========================================================

class ExecutionToolCore:
    """
    Business AI OS Execution Tool Core.

    Standard flow:
    1. Worker requests a Tool.
    2. Search Tool Registry first.
    3. Validate status, approval, test and reuse conditions.
    4. Execute the registered Tool.
    5. Save execution evidence.
    6. Return structured execution result.

    Supported entrypoint formats:
    - Python callable: module_name:function_name
    - Python callable: package.module:function_name
    - Python script: script:path/to/file.py
    """

    def __init__(
        self,
        *,
        registry: ToolRegistry | None = None,
        execution_log_dir: Path = EXECUTION_LOG_DIR,
        base_dir: Path = BASE_DIR,
    ) -> None:
        self.registry = registry or tool_registry
        self.execution_log_dir = Path(execution_log_dir)
        self.base_dir = Path(base_dir).resolve()

        self.execution_log_dir.mkdir(
            parents=True,
            exist_ok=True,
        )

    # =====================================================
    # Tool Search
    # =====================================================

    def find_tool(
        self,
        *,
        tool_id: str | None = None,
        name: str | None = None,
        category: str | None = None,
        query: str | None = None,
    ) -> dict[str, Any] | None:
        if tool_id or name or category:
            found = self.registry.find_tool(
                tool_id=tool_id,
                name=name,
                category=category,
                status="active",
                approval_status="approved",
                test_status="passed",
                reusable_only=True,
            )

            if found:
                return found

        if query:
            results = self.registry.search_tools(
                query,
                category=category,
            )

            for tool in results:
                if self._is_executable_tool(tool):
                    return tool

        return None

    def require_tool(
        self,
        *,
        tool_id: str | None = None,
        name: str | None = None,
        category: str | None = None,
        query: str | None = None,
    ) -> dict[str, Any]:
        tool = self.find_tool(
            tool_id=tool_id,
            name=name,
            category=category,
            query=query,
        )

        if tool is None:
            requested = tool_id or name or query or category or "unknown"
            raise ToolNotFoundError(
                f"실행 가능한 기존 Tool이 없습니다: {requested}"
            )

        return tool

    # =====================================================
    # Execution
    # =====================================================

    def execute(
        self,
        *,
        workflow_id: str,
        worker_agent_id: str,
        tool_id: str | None = None,
        tool_name: str | None = None,
        category: str | None = None,
        query: str | None = None,
        input_data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Find and execute a registered Tool.
        """

        if not str(workflow_id or "").strip():
            raise ToolExecutionError(
                "workflow_id가 없습니다."
            )

        if not str(worker_agent_id or "").strip():
            raise ToolExecutionError(
                "worker_agent_id가 없습니다."
            )

        tool = self.require_tool(
            tool_id=tool_id,
            name=tool_name,
            category=category,
            query=query,
        )

        return self.execute_registered_tool(
            workflow_id=workflow_id,
            worker_agent_id=worker_agent_id,
            tool=tool,
            input_data=input_data or {},
        )

    def execute_registered_tool(
        self,
        *,
        workflow_id: str,
        worker_agent_id: str,
        tool: dict[str, Any],
        input_data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Execute a Tool record already loaded from Tool Registry.
        """

        self._validate_execution_permission(tool)

        execution_id = f"texec_{uuid.uuid4().hex[:16]}"
        started_at = self._now()
        payload = dict(input_data or {})

        record = ToolExecutionRecord(
            execution_id=execution_id,
            workflow_id=str(workflow_id),
            worker_agent_id=str(worker_agent_id),
            tool_id=str(tool.get("tool_id", "")),
            tool_version=str(tool.get("version", "")),
            entrypoint=str(tool.get("entrypoint", "")),
            status="running",
            input_data=self._json_safe(payload),
            output_data=None,
            error="",
            started_at=started_at,
            completed_at="",
        )

        self._save_record(record)

        try:
            output = self._dispatch(
                entrypoint=record.entrypoint,
                input_data=payload,
                execution_context={
                    "execution_id": execution_id,
                    "workflow_id": workflow_id,
                    "worker_agent_id": worker_agent_id,
                    "tool_id": record.tool_id,
                    "tool_version": record.tool_version,
                },
            )

            record.status = "completed"
            record.output_data = self._json_safe(output)
            record.completed_at = self._now()
            self._save_record(record)

            return {
                "execution_id": execution_id,
                "workflow_id": workflow_id,
                "worker_agent_id": worker_agent_id,
                "tool_id": record.tool_id,
                "tool_version": record.tool_version,
                "status": "completed",
                "result": record.output_data,
                "evidence_file": str(
                    self._record_file(execution_id)
                ),
                "started_at": record.started_at,
                "completed_at": record.completed_at,
            }

        except Exception as exc:
            record.status = "failed"
            record.error = (
                f"{type(exc).__name__}: {exc}\n"
                f"{traceback.format_exc()}"
            )
            record.completed_at = self._now()
            self._save_record(record)

            raise ToolExecutionError(
                f"Tool 실행 실패: {record.tool_id}\n{exc}"
            ) from exc

    # =====================================================
    # Dispatch
    # =====================================================

    def _dispatch(
        self,
        *,
        entrypoint: str,
        input_data: dict[str, Any],
        execution_context: dict[str, Any],
    ) -> Any:
        normalized = str(entrypoint or "").strip()

        if not normalized:
            raise ToolEntrypointError(
                "Tool entrypoint가 없습니다."
            )

        if normalized.startswith("script:"):
            return self._execute_script(
                script_path=normalized.split(":", 1)[1],
                input_data=input_data,
                execution_context=execution_context,
            )

        return self._execute_callable(
            entrypoint=normalized,
            input_data=input_data,
            execution_context=execution_context,
        )

    def _execute_callable(
        self,
        *,
        entrypoint: str,
        input_data: dict[str, Any],
        execution_context: dict[str, Any],
    ) -> Any:
        if ":" not in entrypoint:
            raise ToolEntrypointError(
                "Python Tool entrypoint는 "
                "'module:function' 형식이어야 합니다."
            )

        module_name, function_name = entrypoint.split(":", 1)
        module_name = module_name.strip()
        function_name = function_name.strip()

        if not module_name or not function_name:
            raise ToolEntrypointError(
                "Tool module 또는 function 이름이 없습니다."
            )

        try:
            module = importlib.import_module(module_name)
        except Exception as exc:
            raise ToolEntrypointError(
                f"Tool module을 불러올 수 없습니다: {module_name}"
            ) from exc

        target = getattr(module, function_name, None)

        if target is None or not callable(target):
            raise ToolEntrypointError(
                f"호출 가능한 Tool function이 없습니다: {entrypoint}"
            )

        return self._call_function(
            target,
            input_data=input_data,
            execution_context=execution_context,
        )

    def _call_function(
        self,
        target: Callable[..., Any],
        *,
        input_data: dict[str, Any],
        execution_context: dict[str, Any],
    ) -> Any:
        """
        Supported function signatures:
        - function(**input_data)
        - function(input_data)
        - function(input_data, execution_context)
        - function()
        """

        signature = inspect.signature(target)
        parameters = list(signature.parameters.values())

        if any(
            parameter.kind == inspect.Parameter.VAR_KEYWORD
            for parameter in parameters
        ):
            kwargs = dict(input_data)
            kwargs.setdefault(
                "execution_context",
                execution_context,
            )
            return target(**kwargs)

        parameter_names = {
            parameter.name
            for parameter in parameters
        }

        if "input_data" in parameter_names:
            kwargs: dict[str, Any] = {
                "input_data": input_data,
            }

            if "execution_context" in parameter_names:
                kwargs["execution_context"] = execution_context

            return target(**kwargs)

        if not parameters:
            return target()

        accepted_kwargs = {
            key: value
            for key, value in input_data.items()
            if key in parameter_names
        }

        if "execution_context" in parameter_names:
            accepted_kwargs["execution_context"] = execution_context

        missing_required = [
            parameter.name
            for parameter in parameters
            if parameter.default is inspect.Parameter.empty
            and parameter.kind
            in {
                inspect.Parameter.POSITIONAL_OR_KEYWORD,
                inspect.Parameter.KEYWORD_ONLY,
            }
            and parameter.name not in accepted_kwargs
        ]

        if missing_required:
            if len(parameters) == 1:
                return target(input_data)

            if (
                len(parameters) == 2
                and parameters[0].name not in accepted_kwargs
                and parameters[1].name not in accepted_kwargs
            ):
                return target(
                    input_data,
                    execution_context,
                )

            raise ToolExecutionError(
                "Tool 입력값이 부족합니다: "
                + ", ".join(missing_required)
            )

        return target(**accepted_kwargs)

    def _execute_script(
        self,
        *,
        script_path: str,
        input_data: dict[str, Any],
        execution_context: dict[str, Any],
    ) -> dict[str, Any]:
        path = self._resolve_script_path(script_path)

        payload = {
            "input_data": input_data,
            "execution_context": execution_context,
        }

        process = subprocess.run(
            [sys.executable, str(path)],
            input=json.dumps(
                payload,
                ensure_ascii=False,
            ),
            text=True,
            capture_output=True,
            cwd=str(self.base_dir),
            timeout=300,
        )

        result = {
            "returncode": process.returncode,
            "stdout": process.stdout,
            "stderr": process.stderr,
        }

        if process.returncode != 0:
            raise ToolExecutionError(
                "Python script Tool 실행 실패.\n"
                + process.stdout
                + process.stderr
            )

        parsed_output: Any = process.stdout

        try:
            parsed_output = json.loads(process.stdout)
        except json.JSONDecodeError:
            pass

        result["parsed_output"] = parsed_output
        return result

    # =====================================================
    # Validation
    # =====================================================

    def _validate_execution_permission(
        self,
        tool: dict[str, Any],
    ) -> None:
        tool_id = str(tool.get("tool_id", "unknown"))

        if tool.get("status") != "active":
            raise ToolExecutionBlockedError(
                f"비활성 Tool은 실행할 수 없습니다: {tool_id}"
            )

        if tool.get("approval_status") != "approved":
            raise ToolExecutionBlockedError(
                f"대표 승인 전 Tool은 실행할 수 없습니다: {tool_id}"
            )

        if tool.get("test_status") != "passed":
            raise ToolExecutionBlockedError(
                f"자동 테스트 미통과 Tool은 실행할 수 없습니다: {tool_id}"
            )

        if not bool(tool.get("reusable", False)):
            raise ToolExecutionBlockedError(
                f"재사용 허용되지 않은 Tool입니다: {tool_id}"
            )

    @staticmethod
    def _is_executable_tool(
        tool: dict[str, Any],
    ) -> bool:
        return (
            tool.get("status") == "active"
            and tool.get("approval_status") == "approved"
            and tool.get("test_status") == "passed"
            and bool(tool.get("reusable", False))
        )

    # =====================================================
    # Evidence
    # =====================================================

    def get_execution(
        self,
        execution_id: str,
    ) -> dict[str, Any] | None:
        file_path = self._record_file(execution_id)

        if not file_path.exists():
            return None

        try:
            return json.loads(
                file_path.read_text(encoding="utf-8")
            )
        except (json.JSONDecodeError, OSError):
            return None

    def list_executions(
        self,
        *,
        workflow_id: str | None = None,
        tool_id: str | None = None,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []

        for file_path in sorted(
            self.execution_log_dir.glob("texec_*.json")
        ):
            try:
                record = json.loads(
                    file_path.read_text(encoding="utf-8")
                )
            except (json.JSONDecodeError, OSError):
                continue

            if (
                workflow_id
                and record.get("workflow_id") != workflow_id
            ):
                continue

            if tool_id and record.get("tool_id") != tool_id:
                continue

            if status and record.get("status") != status:
                continue

            records.append(record)

        records.sort(
            key=lambda item: item.get("started_at", ""),
            reverse=True,
        )
        return records

    def _save_record(
        self,
        record: ToolExecutionRecord,
    ) -> None:
        file_path = self._record_file(
            record.execution_id
        )
        temporary_file = file_path.with_suffix(".json.tmp")

        temporary_file.write_text(
            json.dumps(
                asdict(record),
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        temporary_file.replace(file_path)

    def _record_file(
        self,
        execution_id: str,
    ) -> Path:
        safe_id = "".join(
            character
            for character in str(execution_id)
            if character.isalnum() or character in {"_", "-"}
        )

        if not safe_id:
            raise ToolExecutionError(
                "유효하지 않은 execution_id입니다."
            )

        return self.execution_log_dir / f"{safe_id}.json"

    # =====================================================
    # Helpers
    # =====================================================

    def _resolve_script_path(
        self,
        script_path: str,
    ) -> Path:
        candidate = Path(script_path)

        if not candidate.is_absolute():
            candidate = self.base_dir / candidate

        resolved = candidate.resolve()

        try:
            resolved.relative_to(self.base_dir)
        except ValueError as exc:
            raise ToolEntrypointError(
                "Tool script는 AgentsSDK 폴더 내부에 있어야 합니다."
            ) from exc

        if not resolved.exists() or not resolved.is_file():
            raise ToolEntrypointError(
                f"Tool script 파일이 없습니다: {resolved}"
            )

        if resolved.suffix.lower() != ".py":
            raise ToolEntrypointError(
                "현재 script Tool은 Python 파일만 지원합니다."
            )

        return resolved

    @classmethod
    def _json_safe(cls, value: Any) -> Any:
        if value is None:
            return None

        if isinstance(
            value,
            (str, int, float, bool),
        ):
            return value

        if isinstance(value, Path):
            return str(value)

        if isinstance(value, dict):
            return {
                str(key): cls._json_safe(item)
                for key, item in value.items()
            }

        if isinstance(value, (list, tuple, set)):
            return [
                cls._json_safe(item)
                for item in value
            ]

        if hasattr(value, "model_dump"):
            return cls._json_safe(
                value.model_dump()
            )

        if hasattr(value, "__dict__"):
            return cls._json_safe(
                vars(value)
            )

        return str(value)

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()


# =========================================================
# Shared Instance
# =========================================================

execution_tool_core = ExecutionToolCore()


if __name__ == "__main__":
    print(
        json.dumps(
            {
                "status": "ready",
                "registered_tools": len(
                    tool_registry.export_registry().get(
                        "tools",
                        [],
                    )
                ),
                "execution_log_dir": str(
                    EXECUTION_LOG_DIR
                ),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
