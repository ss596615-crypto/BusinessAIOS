from __future__ import annotations

from typing import Any

from development_engine import development_engine


TOOL_ID = "tool_development_engine"
TOOL_NAME = "Development Engine Tool"
TOOL_VERSION = "1.0.0"


class DevelopmentEngineToolError(RuntimeError):
    """Development Engine Tool 실행 오류."""


def run_tool(
    input_data: dict[str, Any],
    execution_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    기존 development_engine.py를 Business AI OS Tool 형식으로 실행한다.

    필수 입력:
    - workflow: dict
    - worker_agent_id: str
    """

    payload = dict(input_data or {})
    workflow = payload.get("workflow")
    worker_agent_id = str(
        payload.get("worker_agent_id")
        or (execution_context or {}).get("worker_agent_id")
        or ""
    ).strip()

    if not isinstance(workflow, dict):
        raise DevelopmentEngineToolError(
            "input_data.workflow는 dict 형식이어야 합니다."
        )

    workflow_id = str(
        workflow.get("workflow_id", "")
    ).strip()

    if not workflow_id:
        raise DevelopmentEngineToolError(
            "workflow에 workflow_id가 없습니다."
        )

    if not worker_agent_id:
        raise DevelopmentEngineToolError(
            "worker_agent_id가 없습니다."
        )

    result = development_engine.execute(
        workflow=workflow,
        worker_agent_id=worker_agent_id,
    )

    return {
        "status": str(result.get("status", "completed")),
        "tool_id": TOOL_ID,
        "tool_name": TOOL_NAME,
        "tool_version": TOOL_VERSION,
        "workflow_id": workflow_id,
        "worker_agent_id": worker_agent_id,
        "development_result": result,
        "execution_context": dict(execution_context or {}),
    }
