from __future__ import annotations

from pathlib import Path

from ceo_meeting import format_progress_report
from runtime import BusinessAIRuntime
from workflow_manager import WorkflowManager


class _DummyWorkflowManager:
    def __init__(self, workflow: dict, progress: dict) -> None:
        self._workflow = workflow
        self._progress = progress

    def require_workflow(self, workflow_id: str) -> dict:
        assert workflow_id == self._workflow["workflow_id"]
        return self._workflow

    def get_workflow_progress(self, workflow_id: str) -> dict:
        assert workflow_id == self._workflow["workflow_id"]
        return self._progress


def test_runtime_report_uses_latest_workflow_state(tmp_path: Path) -> None:
    manager = WorkflowManager(workflow_file=tmp_path / "workflows.json")
    created = manager.create_workflow(
        title="동기화 테스트",
        objective="status 표시 검증",
        owner_instruction="runtime report sync",
        requires_approval=True,
    )["workflow"]
    workflow_id = created["workflow_id"]

    manager._set_workflow_fields(
        workflow_id,
        {
            "status": "running",
            "approval_status": "pending",
            "next_action": "최신 workflow 기준 확인",
            "updated_at": "2026-01-01T00:00:00+00:00",
        },
    )

    runtime = BusinessAIRuntime()
    report = runtime.report(workflow_id)

    assert report["status"] == "running"
    assert report["approval_status"] == "pending"
    assert report["next_action"] == "최신 workflow 기준 확인"
    assert report["workflow"]["workflow_id"] == workflow_id


def test_hq_report_matches_latest_workflow_state(tmp_path: Path) -> None:
    manager = WorkflowManager(workflow_file=tmp_path / "workflows.json")
    created = manager.create_workflow(
        title="HQ 동기화 테스트",
        objective="HQ 표시 검증",
        owner_instruction="hq sync",
        requires_approval=True,
    )["workflow"]
    workflow_id = created["workflow_id"]

    manager._set_workflow_fields(
        workflow_id,
        {
            "status": "waiting_approval",
            "approval_status": "pending",
            "next_action": "대표 승인 대기",
            "updated_at": "2026-01-01T00:00:00+00:00",
        },
    )

    workflow = manager.require_workflow(workflow_id)
    progress = manager.get_workflow_progress(workflow_id)
    report_text = format_progress_report(workflow_id)

    assert workflow["status"] == "waiting_approval"
    assert workflow["approval_status"] == "pending"
    assert workflow["next_action"] == "대표 승인 대기"
    assert "상태: waiting_approval" in report_text
    assert "승인 상태: pending" in report_text
    assert "다음 업무: 대표 승인 대기" in report_text
    assert progress["status"] == "waiting_approval"
