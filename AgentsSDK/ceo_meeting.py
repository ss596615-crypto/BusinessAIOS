"""
Business AI OS V2
ceo_meeting.py

대표가 AI CEO와 대화하고 업무 지시·진행 확인·승인·반려·보고를 수행하는 운영 회의실.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import streamlit as st

from runtime import runtime
from workflow_manager import workflow_manager


st.set_page_config(
    page_title="Business AI OS - AI CEO 회의실",
    page_icon="🏢",
    layout="wide",
)


def make_project_id(instruction: str) -> str:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    cleaned = "_".join(instruction.strip().split()) or "project"
    return f"{cleaned[:40]}_{timestamp}"


def make_project_title(instruction: str) -> str:
    cleaned = " ".join(instruction.strip().split())
    for ending in (
        "구축하고 출시하라.", "구축하고 출시하라",
        "만들어라.", "만들어라",
        "출시하라.", "출시하라",
        "진행하라.", "진행하라",
        "수정하라.", "수정하라",
        "추가하라.", "추가하라",
    ):
        if cleaned.endswith(ending):
            cleaned = cleaned[:-len(ending)].strip()
            break
    return cleaned or "신규 프로젝트"


def add_chat(role: str, content: str) -> None:
    st.session_state.chat_history.append(
        {
            "role": role,
            "content": content,
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
    )


def get_workflow_safe(workflow_id: str | None) -> dict[str, Any] | None:
    if not workflow_id:
        return None
    try:
        return workflow_manager.require_workflow(workflow_id)
    except Exception:
        return None


def get_progress_safe(workflow_id: str | None) -> dict[str, Any] | None:
    if not workflow_id:
        return None
    try:
        return runtime.progress(workflow_id)
    except Exception:
        return None


def refresh_workflows() -> list[dict[str, Any]]:
    try:
        return workflow_manager.list_workflows(limit=30, newest_first=True)
    except Exception:
        return []


def format_ceo_start_report(result: dict[str, Any]) -> str:
    workflow_id = result["workflow_id"]
    workflow = get_workflow_safe(workflow_id) or {}
    manager = result.get("manager") or {}
    worker_ids = workflow.get("worker_agent_ids", [])
    lines = [
        "업무를 접수했습니다.",
        f"- Workflow: {workflow_id}",
        f"- 업무 유형: {result.get('business_type', '-')}",
        f"- 담당 지점장: {manager.get('role', '-')}",
        f"- 배정 직원: {len(worker_ids)}명",
        f"- 현재 상태: {result.get('status', '-')}",
        f"- 승인 상태: {result.get('approval_status', '-')}",
    ]
    if result.get("analysis_summary"):
        lines.append(f"- CEO 분석: {result['analysis_summary']}")
    return "\n".join(lines)


def format_progress_report(workflow_id: str) -> str:
    workflow = get_workflow_safe(workflow_id)
    progress = get_progress_safe(workflow_id)
    if workflow is None or progress is None:
        return "Workflow 정보를 불러오지 못했습니다."
    return "\n".join(
        [
            f"프로젝트: {workflow.get('title', '-')}",
            f"상태: {progress.get('status', '-')}",
            f"승인 상태: {progress.get('approval_status', '-')}",
            f"진행률: {progress.get('progress_percent', 0)}%",
            f"완료 단계: {progress.get('completed_steps', 0)} / {progress.get('total_steps', 0)}",
            f"결과 요약: {workflow.get('result_summary') or '작성 중'}",
            f"다음 업무: {workflow.get('next_action') or '결정 중'}",
        ]
    )


if "chat_history" not in st.session_state:
    st.session_state.chat_history = []
if "current_workflow_id" not in st.session_state:
    st.session_state.current_workflow_id = None
if "last_instruction" not in st.session_state:
    st.session_state.last_instruction = ""


st.title("🏢 Business AI OS")
st.subheader("대표 ↔ AI CEO 운영 회의실")
st.caption(
    "대표는 목표·아이디어·수정 지시를 입력하고, "
    "AI CEO는 분석·위임·실행·보고·승인 요청을 처리합니다."
)

workflows = refresh_workflows()
current_workflow = get_workflow_safe(st.session_state.current_workflow_id)
current_progress = get_progress_safe(st.session_state.current_workflow_id)

col1, col2, col3, col4 = st.columns(4)
with col1:
    st.metric("전체 Workflow", len(workflows))
with col2:
    st.metric("승인 대기", sum(1 for w in workflows if w.get("status") == "waiting_approval"))
with col3:
    st.metric("진행 중", sum(1 for w in workflows if w.get("status") in {"ready", "running", "paused"}))
with col4:
    st.metric("완료", sum(1 for w in workflows if w.get("status") == "completed"))

st.divider()
st.markdown("### 대표 지시")
instruction = st.text_area(
    "AI CEO에게 지시할 내용을 입력하세요.",
    value=st.session_state.last_instruction,
    height=120,
    placeholder="예: 운영 홈페이지에 승인 요청 화면과 실제 승인·반려 기능을 연결하라.",
)

send_col, clear_col = st.columns(2)
with send_col:
    send_clicked = st.button("AI CEO에게 지시", type="primary", use_container_width=True)
with clear_col:
    clear_clicked = st.button("입력 지우기", use_container_width=True)

if clear_clicked:
    st.session_state.last_instruction = ""
    st.rerun()

if send_clicked:
    cleaned_instruction = instruction.strip()
    if not cleaned_instruction:
        st.warning("대표 지시를 입력하세요.")
    else:
        st.session_state.last_instruction = cleaned_instruction
        add_chat("대표", cleaned_instruction)
        title = make_project_title(cleaned_instruction)
        objective = cleaned_instruction
        project_id = make_project_id(cleaned_instruction)
        try:
            with st.spinner("AI CEO가 지시를 분석하고 조직에 위임하고 있습니다..."):
                result = runtime.process_instruction(
                    title=title,
                    objective=objective,
                    owner_instruction=cleaned_instruction,
                    project_id=project_id,
                )
            workflow_id = result["workflow_id"]
            st.session_state.current_workflow_id = workflow_id
            if result.get("created_new_workflow") is False:
                workflow = result.get("workflow") or get_workflow_safe(workflow_id) or {}
                evidence = result.get("evidence") or result.get("evaluation", {}).get("evidence", {})
                lines = [
                    "기존 Workflow를 신규 생성 없이 처리했습니다.",
                    f"- Workflow: {workflow_id}",
                    f"- 처리: {result.get('existing_workflow_action', '-')}",
                    f"- 상태: {workflow.get('status', '-')}",
                    f"- 신규 Workflow 생성: 아니오",
                ]
                missing = result.get("evaluation", {}).get("missing", [])
                if missing:
                    lines.append(f"- 부족한 증거: {', '.join(missing)}")
                if evidence:
                    lines.append(f"- 산출물 파일: {len(evidence.get('artifact_files', []))}개")
                    lines.append(f"- Worker 결과: {len(evidence.get('worker_result_files', []))}개")
                    lines.append(f"- 테스트 성공: {evidence.get('test_passed', False)}")
                add_chat("AI CEO", "\n".join(lines))
            else:
                add_chat("AI CEO", format_ceo_start_report(result))
            st.success("AI CEO가 업무를 접수했습니다.")
            st.rerun()
        except Exception as error:
            message = f"업무 접수 중 오류가 발생했습니다.\n{type(error).__name__}: {error}"
            add_chat("AI CEO", message)
            st.error(message)

st.divider()
st.markdown("### AI CEO 회의 기록")
if not st.session_state.chat_history:
    st.info("아직 회의 기록이 없습니다.")
else:
    for message in st.session_state.chat_history:
        with st.chat_message("user" if message["role"] == "대표" else "assistant"):
            st.markdown(f"**{message['role']}**")
            st.markdown(message["content"])
            st.caption(message["created_at"])

st.divider()
st.markdown("### 현재 Workflow")
if current_workflow is None:
    st.info("현재 선택된 Workflow가 없습니다.")
else:
    wf_col1, wf_col2 = st.columns([2, 1])
    with wf_col1:
        st.markdown(f"**프로젝트:** {current_workflow.get('title', '-')}")
        st.markdown(f"**목표:** {current_workflow.get('objective', '-')}")
        st.markdown(f"**Workflow ID:** {current_workflow.get('workflow_id', '-')}")
        st.markdown(f"**지점장:** {current_workflow.get('manager_agent_id') or '-'}")
        st.markdown(f"**직원:** {', '.join(current_workflow.get('worker_agent_ids', [])) or '-'}")
        evidence = (current_workflow.get("metadata") or {}).get("evidence") or {}
        if evidence:
            st.markdown("**완료 증거**")
            st.write("산출물:", len(evidence.get("artifact_files", [])), "개")
            st.write("Worker 결과:", len(evidence.get("worker_result_files", [])), "개")
            st.write("테스트 성공:", "예" if evidence.get("test_passed") else "아니오")
    with wf_col2:
        if current_progress:
            st.metric("진행률", f"{current_progress.get('progress_percent', 0)}%")
            st.write("상태:", current_progress.get("status", "-"))
            st.write("승인:", current_progress.get("approval_status", "-"))

st.divider()
st.markdown("### 대표 의사결정")
col_a, col_r, col_s, col_p = st.columns(4)
with col_a:
    approve_clicked = st.button(
        "승인",
        type="primary",
        use_container_width=True,
        disabled=current_workflow is None or current_workflow.get("status") != "waiting_approval",
    )
with col_r:
    reject_clicked = st.button(
        "반려",
        use_container_width=True,
        disabled=current_workflow is None or current_workflow.get("status") != "waiting_approval",
    )
with col_s:
    status_clicked = st.button("상태 확인", use_container_width=True, disabled=current_workflow is None)
with col_p:
    report_clicked = st.button("CEO 보고", use_container_width=True, disabled=current_workflow is None)

rejection_reason = st.text_input("반려 사유", placeholder="반려 시 수정이 필요한 내용을 입력하세요.")

if approve_clicked and current_workflow is not None:
    workflow_id = current_workflow["workflow_id"]
    try:
        with st.spinner("승인 처리 후 업무를 재개하고 있습니다..."):
            approved = runtime.approve(workflow_id)
        final_workflow = approved["workflow"]
        add_chat(
            "AI CEO",
            "대표 승인을 처리했습니다.\n"
            f"- 최종 상태: {final_workflow.get('status', '-')}\n"
            f"- 승인 상태: {final_workflow.get('approval_status', '-')}",
        )
        st.success("승인이 완료되었습니다.")
        st.rerun()
    except Exception as error:
        st.error(f"승인 처리 오류: {error}")

if reject_clicked and current_workflow is not None:
    workflow_id = current_workflow["workflow_id"]
    reason = rejection_reason.strip() or "대표 반려"
    try:
        runtime.reject(workflow_id, reason)
        add_chat("AI CEO", f"대표 반려를 접수했습니다.\n- 반려 사유: {reason}")
        st.success("반려 처리가 완료되었습니다.")
        st.rerun()
    except Exception as error:
        st.error(f"반려 처리 오류: {error}")

if status_clicked and current_workflow is not None:
    add_chat("AI CEO", format_progress_report(current_workflow["workflow_id"]))
    st.rerun()

if report_clicked and current_workflow is not None:
    workflow_id = current_workflow["workflow_id"]
    try:
        report = runtime.report(workflow_id)
        workflow = report["workflow"]
        progress = report["progress"]
        text = "\n".join(
            [
                "AI CEO 운영보고",
                f"- 프로젝트: {workflow.get('title', '-')}",
                f"- 목표: {workflow.get('objective', '-')}",
                f"- 상태: {progress.get('status', '-')}",
                f"- 진행률: {progress.get('progress_percent', 0)}%",
                f"- 완료 단계: {progress.get('completed_steps', 0)} / {progress.get('total_steps', 0)}",
                f"- 결과 요약: {workflow.get('result_summary') or '작성 중'}",
                f"- 다음 업무: {workflow.get('next_action') or '결정 중'}",
            ]
        )
        add_chat("AI CEO", text)
        st.rerun()
    except Exception as error:
        st.error(f"보고서 조회 오류: {error}")

st.divider()
st.markdown("### 최근 Workflow")
if not workflows:
    st.info("저장된 Workflow가 없습니다.")
else:
    for workflow in workflows[:15]:
        workflow_id = str(workflow.get("workflow_id", ""))
        title = workflow.get("title", "제목 없음")
        status = workflow.get("status", "-")
        approval_status = workflow.get("approval_status", "-")
        with st.expander(f"{title} · {status} · 승인 {approval_status}"):
            st.write("Workflow ID:", workflow_id)
            st.write("목표:", workflow.get("objective", "-"))
            st.write("지점장:", workflow.get("manager_agent_id") or "-")
            st.write("직원:", workflow.get("worker_agent_ids", []))
            if st.button("이 Workflow 선택", key=f"select_{workflow_id}"):
                st.session_state.current_workflow_id = workflow_id
                st.rerun()

st.divider()
st.caption(
    "현재 버전은 로컬 Business AI OS Runtime과 직접 연결됩니다. "
    "이후 최종 운영 홈페이지 내부 메뉴로 통합할 수 있습니다."
)
