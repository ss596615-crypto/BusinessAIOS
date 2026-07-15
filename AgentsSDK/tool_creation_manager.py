from __future__ import annotations

import json
import re
import subprocess
import sys
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from execution_tool_core import ExecutionToolCore, execution_tool_core
from tool_registry import ToolRecord, ToolRegistry, tool_registry


BASE_DIR = Path(__file__).resolve().parent
ASSETS_DIR = BASE_DIR / "company_assets"
REQUEST_DIR = ASSETS_DIR / "tool_creation_requests"
GENERATED_TOOL_DIR = BASE_DIR / "generated_tools"


class ToolCreationManagerError(RuntimeError):
    pass


class ToolCreationRequestNotFoundError(ToolCreationManagerError):
    pass


class ToolCreationApprovalError(ToolCreationManagerError):
    pass


class ToolGenerationError(ToolCreationManagerError):
    pass


@dataclass
class ToolCreationRequest:
    request_id: str
    workflow_id: str
    worker_agent_id: str
    requested_name: str
    requested_category: str
    requested_description: str
    requested_capability: str
    requested_input_schema: dict[str, Any]
    requested_output_schema: dict[str, Any]
    creation_reason: str
    reuse_search_query: str
    reuse_search_result: list[dict[str, Any]]
    approval_status: str
    status: str
    generated_tool_id: str
    generated_file: str
    test_command: str
    test_status: str
    registry_status: str
    created_at: str
    updated_at: str
    approved_at: str
    completed_at: str
    rejection_reason: str
    metadata: dict[str, Any]


class ToolCreationManager:
    VALID_APPROVAL_STATUSES = {"pending", "approved", "rejected"}
    VALID_STATUSES = {
        "waiting_approval",
        "approved",
        "generating",
        "testing",
        "registering",
        "completed",
        "rejected",
        "failed",
    }

    def __init__(
        self,
        *,
        registry: ToolRegistry | None = None,
        execution_core: ExecutionToolCore | None = None,
        request_dir: Path = REQUEST_DIR,
        generated_tool_dir: Path = GENERATED_TOOL_DIR,
    ) -> None:
        self.registry = registry or tool_registry
        self.execution_core = execution_core or execution_tool_core
        self.request_dir = Path(request_dir)
        self.generated_tool_dir = Path(generated_tool_dir)
        self.request_dir.mkdir(parents=True, exist_ok=True)
        self.generated_tool_dir.mkdir(parents=True, exist_ok=True)
        init_file = self.generated_tool_dir / "__init__.py"
        if not init_file.exists():
            init_file.write_text("", encoding="utf-8")

    def search_or_request(
        self,
        *,
        workflow_id: str,
        worker_agent_id: str,
        requested_name: str,
        requested_category: str,
        requested_description: str,
        requested_capability: str,
        creation_reason: str,
        requested_input_schema: dict[str, Any] | None = None,
        requested_output_schema: dict[str, Any] | None = None,
        reuse_search_query: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self._validate_required(
            workflow_id=workflow_id,
            worker_agent_id=worker_agent_id,
            requested_name=requested_name,
            requested_category=requested_category,
            requested_description=requested_description,
            requested_capability=requested_capability,
            creation_reason=creation_reason,
        )

        query = (reuse_search_query or requested_name or requested_capability).strip()
        results = self.registry.search_tools(
            query,
            category=requested_category or None,
        )

        reusable = [
            tool
            for tool in results
            if tool.get("status") == "active"
            and tool.get("approval_status") == "approved"
            and tool.get("test_status") == "passed"
            and bool(tool.get("reusable", False))
        ]

        if reusable:
            return {
                "status": "existing_tool_found",
                "reused": True,
                "tool": reusable[0],
                "search_results": reusable,
                "next_action": "기존 Tool 즉시 사용",
            }

        existing = self.find_open_request(
            workflow_id=workflow_id,
            requested_name=requested_name,
            requested_category=requested_category,
        )

        if existing:
            return {
                "status": existing.get("status", "waiting_approval"),
                "reused": False,
                "request_created": False,
                "reason": "same_open_request_exists",
                "request": existing,
                "next_action": self._next_action(existing),
            }

        request = self._create_request(
            workflow_id=workflow_id,
            worker_agent_id=worker_agent_id,
            requested_name=requested_name,
            requested_category=requested_category,
            requested_description=requested_description,
            requested_capability=requested_capability,
            requested_input_schema=requested_input_schema or {},
            requested_output_schema=requested_output_schema or {},
            creation_reason=creation_reason,
            reuse_search_query=query,
            reuse_search_result=results,
            metadata=metadata or {},
        )

        return {
            "status": "waiting_approval",
            "reused": False,
            "request_created": True,
            "request": request,
            "next_action": "대표 승인 대기",
        }

    def approve(
        self,
        request_id: str,
        *,
        approved_by: str = "owner",
    ) -> dict[str, Any]:
        request = self.require_request(request_id)

        if request.get("status") == "completed":
            return {
                "approved": False,
                "reason": "already_completed",
                "request": request,
            }

        if request.get("approval_status") == "rejected":
            raise ToolCreationApprovalError("이미 반려된 요청입니다.")

        if request.get("approval_status") == "approved":
            return {
                "approved": False,
                "reason": "already_approved",
                "request": request,
            }

        request["approval_status"] = "approved"
        request["status"] = "approved"
        request["approved_at"] = self._now()
        metadata = dict(request.get("metadata") or {})
        metadata["approved_by"] = approved_by
        request["metadata"] = metadata
        self._save_request(request)

        return {
            "approved": True,
            "request": request,
            "next_action": "Tool 자동 생성 및 테스트",
        }

    def reject(
        self,
        request_id: str,
        reason: str,
    ) -> dict[str, Any]:
        request = self.require_request(request_id)

        if request.get("status") == "completed":
            raise ToolCreationApprovalError(
                "완료된 요청은 반려할 수 없습니다."
            )

        request["approval_status"] = "rejected"
        request["status"] = "rejected"
        request["rejection_reason"] = str(reason or "").strip()
        self._save_request(request)

        return {
            "rejected": True,
            "request": request,
            "next_action": "업무 중단 또는 기존 Tool 재검토",
        }

    def execute_approved_request(
        self,
        request_id: str,
        *,
        generated_source: str | None = None,
        generated_entrypoint: str | None = None,
    ) -> dict[str, Any]:
        request = self.require_request(request_id)

        if request.get("approval_status") != "approved":
            raise ToolCreationApprovalError(
                "대표 승인 완료 후에만 Tool을 생성할 수 있습니다."
            )

        if request.get("status") == "completed":
            tool_id = str(request.get("generated_tool_id", ""))
            return {
                "status": "completed",
                "reused_result": True,
                "request": request,
                "tool": self.registry.get_tool_by_id(tool_id),
            }

        try:
            request["status"] = "generating"
            self._save_request(request)

            tool_id = self._build_tool_id(
                str(request.get("requested_name", ""))
            )
            output_file = self.generated_tool_dir / f"{tool_id}.py"
            source = (
                generated_source
                if generated_source is not None
                else self._build_default_source(request)
            )

            self._validate_generated_source(source)
            output_file.write_text(source, encoding="utf-8")

            entrypoint = (
                generated_entrypoint
                or f"generated_tools.{tool_id}:run_tool"
            )

            request["generated_tool_id"] = tool_id
            request["generated_file"] = str(output_file)
            request["status"] = "testing"
            request["test_command"] = (
                f'{sys.executable} -m py_compile "{output_file}"'
            )
            self._save_request(request)

            test_result = self._run_test(output_file)
            request["test_status"] = (
                "passed" if test_result["passed"] else "failed"
            )
            metadata = dict(request.get("metadata") or {})
            metadata["test_result"] = test_result
            request["metadata"] = metadata
            self._save_request(request)

            if not test_result["passed"]:
                request["status"] = "failed"
                self._save_request(request)
                raise ToolGenerationError(
                    "자동 테스트에 실패했습니다.\n"
                    + test_result["output"]
                )

            request["status"] = "registering"
            self._save_request(request)

            record = ToolRecord(
                tool_id=tool_id,
                name=str(request.get("requested_name", "")).strip(),
                category=str(request.get("requested_category", "")).strip(),
                description=str(
                    request.get("requested_description", "")
                ).strip(),
                entrypoint=entrypoint,
                version="1.0.0",
                status="active",
                reusable=True,
                approval_status="approved",
                created_reason=str(request.get("creation_reason", "")),
                created_by_agent_id=str(
                    request.get("worker_agent_id", "")
                ),
                test_status="passed",
                test_command=request["test_command"],
                permissions=[],
                metadata={
                    "request_id": request_id,
                    "workflow_id": request.get("workflow_id"),
                    "requested_capability": request.get(
                        "requested_capability"
                    ),
                    "requested_input_schema": request.get(
                        "requested_input_schema"
                    ),
                    "requested_output_schema": request.get(
                        "requested_output_schema"
                    ),
                    "generated_file": str(output_file),
                    "auto_generated": True,
                },
                created_at=self._now(),
                updated_at=self._now(),
            )

            registry_result = self.registry.register_tool(
                record,
                require_approval=True,
                require_test_passed=True,
            )

            request["registry_status"] = str(
                registry_result.get("reason", "")
            )
            request["status"] = "completed"
            request["completed_at"] = self._now()
            self._save_request(request)

            return {
                "status": "completed",
                "request": request,
                "test_result": test_result,
                "registry_result": registry_result,
                "tool": registry_result.get("tool"),
                "next_action": "새 Tool 즉시 재사용 가능",
            }

        except Exception:
            latest = self.require_request(request_id)
            if latest.get("status") != "completed":
                latest["status"] = "failed"
                self._save_request(latest)
            raise

    def execute_created_tool(
        self,
        request_id: str,
        *,
        input_data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        request = self.require_request(request_id)

        if request.get("status") != "completed":
            raise ToolCreationManagerError(
                "Tool 생성과 등록이 완료되지 않았습니다."
            )

        return self.execution_core.execute(
            workflow_id=str(request.get("workflow_id", "")),
            worker_agent_id=str(request.get("worker_agent_id", "")),
            tool_id=str(request.get("generated_tool_id", "")),
            input_data=input_data or {},
        )

    def get_request(
        self,
        request_id: str,
    ) -> dict[str, Any] | None:
        file_path = self._request_file(request_id)
        if not file_path.exists():
            return None

        try:
            return json.loads(file_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None

    def require_request(
        self,
        request_id: str,
    ) -> dict[str, Any]:
        request = self.get_request(request_id)
        if request is None:
            raise ToolCreationRequestNotFoundError(
                f"Tool 생성 요청이 없습니다: {request_id}"
            )
        return request

    def list_requests(
        self,
        *,
        workflow_id: str | None = None,
        status: str | None = None,
        approval_status: str | None = None,
    ) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []

        for file_path in sorted(
            self.request_dir.glob("tcreq_*.json")
        ):
            try:
                request = json.loads(
                    file_path.read_text(encoding="utf-8")
                )
            except (json.JSONDecodeError, OSError):
                continue

            if workflow_id and request.get("workflow_id") != workflow_id:
                continue
            if status and request.get("status") != status:
                continue
            if (
                approval_status
                and request.get("approval_status") != approval_status
            ):
                continue

            results.append(request)

        results.sort(
            key=lambda item: item.get("created_at", ""),
            reverse=True,
        )
        return results

    def find_open_request(
        self,
        *,
        workflow_id: str,
        requested_name: str,
        requested_category: str,
    ) -> dict[str, Any] | None:
        name = self._normalize(requested_name)
        category = self._normalize(requested_category)

        for request in self.list_requests(workflow_id=workflow_id):
            if request.get("status") in {
                "completed",
                "rejected",
                "failed",
            }:
                continue

            if self._normalize(
                request.get("requested_name", "")
            ) != name:
                continue

            if self._normalize(
                request.get("requested_category", "")
            ) != category:
                continue

            return request

        return None

    def _create_request(
        self,
        *,
        workflow_id: str,
        worker_agent_id: str,
        requested_name: str,
        requested_category: str,
        requested_description: str,
        requested_capability: str,
        requested_input_schema: dict[str, Any],
        requested_output_schema: dict[str, Any],
        creation_reason: str,
        reuse_search_query: str,
        reuse_search_result: list[dict[str, Any]],
        metadata: dict[str, Any],
    ) -> dict[str, Any]:
        now = self._now()

        request = ToolCreationRequest(
            request_id=f"tcreq_{uuid.uuid4().hex[:16]}",
            workflow_id=str(workflow_id).strip(),
            worker_agent_id=str(worker_agent_id).strip(),
            requested_name=str(requested_name).strip(),
            requested_category=str(requested_category).strip(),
            requested_description=str(requested_description).strip(),
            requested_capability=str(requested_capability).strip(),
            requested_input_schema=dict(requested_input_schema),
            requested_output_schema=dict(requested_output_schema),
            creation_reason=str(creation_reason).strip(),
            reuse_search_query=str(reuse_search_query).strip(),
            reuse_search_result=list(reuse_search_result),
            approval_status="pending",
            status="waiting_approval",
            generated_tool_id="",
            generated_file="",
            test_command="",
            test_status="pending",
            registry_status="pending",
            created_at=now,
            updated_at=now,
            approved_at="",
            completed_at="",
            rejection_reason="",
            metadata=dict(metadata),
        )

        data = asdict(request)
        self._save_request(data)
        return data

    def _save_request(
        self,
        request: dict[str, Any],
    ) -> None:
        request["updated_at"] = self._now()

        if request.get("status") not in self.VALID_STATUSES:
            raise ToolCreationManagerError(
                f"허용되지 않은 요청 상태입니다: {request.get('status')}"
            )

        if (
            request.get("approval_status")
            not in self.VALID_APPROVAL_STATUSES
        ):
            raise ToolCreationManagerError(
                "허용되지 않은 승인 상태입니다: "
                f"{request.get('approval_status')}"
            )

        file_path = self._request_file(
            str(request.get("request_id", ""))
        )
        temp_file = file_path.with_suffix(".json.tmp")
        temp_file.write_text(
            json.dumps(request, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temp_file.replace(file_path)

    def _request_file(
        self,
        request_id: str,
    ) -> Path:
        safe_id = re.sub(
            r"[^A-Za-z0-9_-]+",
            "",
            str(request_id or ""),
        )

        if not safe_id:
            raise ToolCreationManagerError(
                "유효하지 않은 request_id입니다."
            )

        return self.request_dir / f"{safe_id}.json"

    def _build_default_source(
        self,
        request: dict[str, Any],
    ) -> str:
        name = repr(str(request.get("requested_name", "Generated Tool")))
        description = repr(
            str(request.get("requested_description", ""))
        )
        capability = repr(
            str(request.get("requested_capability", ""))
        )

        lines = [
            "from __future__ import annotations",
            "",
            "from typing import Any",
            "",
            f"TOOL_NAME = {name}",
            f"TOOL_DESCRIPTION = {description}",
            f"TOOL_CAPABILITY = {capability}",
            "",
            "",
            "def run_tool(",
            "    input_data: dict[str, Any],",
            "    execution_context: dict[str, Any] | None = None,",
            ") -> dict[str, Any]:",
            "    return {",
            '        "status": "completed",',
            '        "tool_name": TOOL_NAME,',
            '        "description": TOOL_DESCRIPTION,',
            '        "capability": TOOL_CAPABILITY,',
            '        "input_data": dict(input_data or {}),',
            '        "execution_context": dict(execution_context or {}),',
            '        "message": "자동 생성 Tool이 정상 실행되었습니다.",',
            "    }",
            "",
        ]

        return "\n".join(lines)

    def _run_test(
        self,
        output_file: Path,
    ) -> dict[str, Any]:
        process = subprocess.run(
            [
                sys.executable,
                "-m",
                "py_compile",
                str(output_file),
            ],
            cwd=str(BASE_DIR),
            text=True,
            capture_output=True,
            timeout=120,
        )

        output = process.stdout + process.stderr

        return {
            "passed": process.returncode == 0,
            "returncode": process.returncode,
            "command": (
                f'{sys.executable} -m py_compile "{output_file}"'
            ),
            "stdout": process.stdout,
            "stderr": process.stderr,
            "output": output,
        }

    def _validate_generated_source(
        self,
        source: str,
    ) -> None:
        if not str(source or "").strip():
            raise ToolGenerationError(
                "생성된 Tool 코드가 비어 있습니다."
            )

        forbidden_patterns = (
            r"\bos\.system\s*\(",
            r"\bsubprocess\.Popen\s*\(",
            r"\beval\s*\(",
            r"\bexec\s*\(",
            r"shutil\.rmtree\s*\(",
        )

        for pattern in forbidden_patterns:
            if re.search(pattern, source):
                raise ToolGenerationError(
                    "안전하지 않은 코드 패턴이 감지되었습니다: "
                    + pattern
                )

        if "def run_tool" not in source:
            raise ToolGenerationError(
                "생성 Tool에는 run_tool 함수가 필요합니다."
            )

    @staticmethod
    def _build_tool_id(
        requested_name: str,
    ) -> str:
        normalized = str(
            requested_name or "generated_tool"
        ).strip().lower()
        normalized = re.sub(r"[^a-z0-9]+", "_", normalized)
        normalized = re.sub(r"_+", "_", normalized).strip("_")

        if not normalized:
            normalized = "generated_" + uuid.uuid4().hex[:8]

        if not normalized.startswith("tool_"):
            normalized = "tool_" + normalized

        return normalized[:100]

    @staticmethod
    def _normalize(value: Any) -> str:
        return re.sub(
            r"\s+",
            " ",
            str(value or "").strip().lower(),
        )

    @staticmethod
    def _next_action(
        request: dict[str, Any],
    ) -> str:
        mapping = {
            "waiting_approval": "대표 승인 대기",
            "approved": "Tool 자동 생성 및 테스트",
            "generating": "Tool 생성 중",
            "testing": "자동 테스트 중",
            "registering": "Tool Registry 등록 중",
            "completed": "Tool 재사용 가능",
            "rejected": "요청 반려",
            "failed": "실패 원인 검토",
        }
        return mapping.get(
            str(request.get("status")),
            "상태 확인 필요",
        )

    @staticmethod
    def _validate_required(**fields: str) -> None:
        missing = [
            name
            for name, value in fields.items()
            if not str(value or "").strip()
        ]

        if missing:
            raise ToolCreationManagerError(
                "필수 Tool 생성 요청 정보가 없습니다: "
                + ", ".join(missing)
            )

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()


tool_creation_manager = ToolCreationManager()


if __name__ == "__main__":
    print(
        json.dumps(
            {
                "status": "ready",
                "request_dir": str(REQUEST_DIR),
                "generated_tool_dir": str(GENERATED_TOOL_DIR),
                "registered_tools": len(
                    tool_registry.export_registry().get(
                        "tools",
                        [],
                    )
                ),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
