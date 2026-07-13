"""
Business AI OS Release V2.4

business_ai_hq.py

대표 전용 HQ

Business AI OS 공식 메인 프로그램

대표
    ↓
Business AI HQ
    ↓
Runtime
    ↓
Operating Engine
Development Engine
"""

from __future__ import annotations

import traceback
from datetime import datetime, timezone

import streamlit as st
import streamlit.components.v1 as components

from runtime import runtime


AUTO_REFRESH_SECONDS = 3


st.set_page_config(
    page_title="Business AI OS HQ",
    page_icon="🏢",
    layout="wide",
)


# -------------------------------------------------
# Helpers
# -------------------------------------------------

def append_log(message: str) -> None:
    timestamp = datetime.now(timezone.utc).astimezone().strftime(
        "%Y-%m-%d %H:%M:%S"
    )
    st.session_state.logs.append(f"[{timestamp}] {message}")

    if len(st.session_state.logs) > 200:
        st.session_state.logs = st.session_state.logs[-200:]


def refresh_workflow_state(show_error: bool = False) -> bool:
    workflow_id = st.session_state.workflow_id

    if not workflow_id:
        return False

    try:
        st.session_state.progress = runtime.progress(workflow_id)
        st.session_state.result = runtime.report(workflow_id)
        return True

    except Exception as exc:
        if show_error:
            st.error(traceback.format_exc())
        else:
            st.session_state.last_refresh_error = str(exc)

        return False


def is_waiting_for_approval(result: dict | None) -> bool:
    if not isinstance(result, dict):
        return False

    return (
        result.get("status") == "waiting_approval"
        and result.get("approval_status") == "pending"
    )


def enable_browser_auto_refresh(seconds: int) -> None:
    milliseconds = max(int(seconds), 1) * 1000

    components.html(
        f"""
        <script>
        const refreshKey = "business_ai_hq_auto_refresh";

        if (window.parent[refreshKey]) {{
            clearTimeout(window.parent[refreshKey]);
        }}

        window.parent[refreshKey] = setTimeout(function() {{
            window.parent.location.reload();
        }}, {milliseconds});
        </script>
        """,
        height=0,
        width=0,
    )


# -------------------------------------------------
# Session
# -------------------------------------------------

if "workflow_id" not in st.session_state:
    st.session_state.workflow_id = None

if "result" not in st.session_state:
    st.session_state.result = None

if "progress" not in st.session_state:
    st.session_state.progress = None

if "logs" not in st.session_state:
    st.session_state.logs = []

if "auto_refresh" not in st.session_state:
    st.session_state.auto_refresh = True

if "last_refresh_error" not in st.session_state:
    st.session_state.last_refresh_error = None


# -------------------------------------------------
# Automatic state synchronization
# -------------------------------------------------

if st.session_state.workflow_id:
    refresh_workflow_state(show_error=False)


# -------------------------------------------------
# Header
# -------------------------------------------------

st.title("🏢 Business AI OS HQ")

header_col1, header_col2 = st.columns([5, 1])

with header_col1:
    st.caption("Business AI OS Release V2.4")

with header_col2:
    st.toggle(
        "자동 새로고침",
        key="auto_refresh",
        help=f"{AUTO_REFRESH_SECONDS}초마다 HQ 상태를 자동 갱신합니다.",
    )

st.divider()


# -------------------------------------------------
# 대표 지시
# -------------------------------------------------

instruction = st.text_area(
    "대표 지시",
    height=160,
)

col1, col2 = st.columns([1, 6])

submit = col1.button(
    "업무 접수",
    use_container_width=True,
)

if submit:
    if instruction.strip() == "":
        st.warning("대표 지시를 입력하세요.")

    else:
        try:
            result = runtime.process_instruction(
                title=instruction,
                objective=instruction,
                owner_instruction=instruction,
            )

            st.session_state.result = result
            st.session_state.workflow_id = result.get("workflow_id")
            append_log(f"업무 접수 : {instruction}")
            st.rerun()

        except Exception:
            st.error(traceback.format_exc())

st.divider()


# -------------------------------------------------
# 현재 Workflow
# -------------------------------------------------

st.subheader("현재 Workflow")

if st.session_state.result is None:
    st.info("현재 선택된 Workflow가 없습니다.")

else:
    result = st.session_state.result or {}
    progress = st.session_state.progress or {}

    workflow_id = (
        result.get("workflow_id")
        or progress.get("workflow_id")
        or st.session_state.workflow_id
    )

    if workflow_id and workflow_id != st.session_state.workflow_id:
        st.session_state.workflow_id = workflow_id

    status = (
        result.get("status")
        or progress.get("status")
    )

    approval_status = (
        result.get("approval_status")
        or progress.get("approval_status")
    )

    execution_engine = (
        result.get("execution_engine")
        or progress.get("execution_engine")
    )

    development_mode = (
        result.get("development_mode")
        if result.get("development_mode") is not None
        else progress.get("development_mode")
    )

    engine_status = (
        result.get("engine_status")
        or progress.get("engine_status")
    )

    st.markdown(f"### Workflow : `{workflow_id}`")

    c1, c2 = st.columns(2)

    with c1:
        st.write("업무 유형 :", result.get("business_type"))
        st.write("실행 엔진 :", execution_engine)
        st.write("상태 :", status)
        st.write("승인 :", approval_status)

    with c2:
        manager = result.get("manager") or {}

        st.write("담당 :", manager.get("role"))
        st.write("Development Mode :", development_mode)
        st.write("Engine Status :", engine_status)
        st.write("다음 작업 :", result.get("next_action"))

    st.divider()

    st.subheader("CEO 분석")
    st.write(result.get("analysis_summary", ""))

    st.divider()

    if progress:
        percent = float(progress.get("progress_percent", 0))
        normalized_percent = min(max(percent, 0.0), 100.0)

        st.progress(normalized_percent / 100)
        st.write(f"{normalized_percent:.1f}%")
        st.write(progress)

st.divider()


# -------------------------------------------------
# 대표 승인
# -------------------------------------------------

st.subheader("대표 의사결정")

current_result = st.session_state.result or {}
current_progress = st.session_state.progress or {}

approval_pending = (
    (
        current_result.get("status")
        or current_progress.get("status")
    ) == "waiting_approval"
    and
    (
        current_result.get("approval_status")
        or current_progress.get("approval_status")
    ) == "pending"
)
if st.session_state.workflow_id and not approval_pending:
    st.info("현재 Workflow는 승인 대기 상태가 아닙니다.")

approve_col, reject_col = st.columns(2)

approve = approve_col.button(
    "승인",
    use_container_width=True,
    disabled=not approval_pending,
)

reject_reason = st.text_input(
    "반려 사유",
    disabled=not approval_pending,
)

reject = reject_col.button(
    "반려",
    use_container_width=True,
    disabled=not approval_pending,
)


# -------------------------------------------------
# 승인
# -------------------------------------------------

if approve:
    workflow_id = st.session_state.workflow_id

    if workflow_id is None:
        st.warning("선택된 Workflow가 없습니다.")

    elif not approval_pending:
        refresh_workflow_state(show_error=False)
        st.warning("현재 Workflow는 승인 대기 상태가 아닙니다.")

    else:
        try:
            runtime.approve(workflow_id)
            refresh_workflow_state(show_error=True)
            append_log("대표 승인")
            st.success("승인이 완료되었습니다.")
            st.rerun()

        except Exception as exc:
            refresh_workflow_state(show_error=False)
            append_log(f"승인 처리 확인 : {exc}")
            st.warning(
                "승인 상태가 이미 변경되었거나 승인 대기 상태가 아닙니다. "
                "최신 상태로 자동 갱신했습니다."
            )


# -------------------------------------------------
# 반려
# -------------------------------------------------

if reject:
    workflow_id = st.session_state.workflow_id

    if workflow_id is None:
        st.warning("선택된 Workflow가 없습니다.")

    elif not reject_reason.strip():
        st.warning("반려 사유를 입력하세요.")

    elif not approval_pending:
        refresh_workflow_state(show_error=False)
        st.warning("현재 Workflow는 승인 대기 상태가 아닙니다.")

    else:
        try:
            runtime.reject(
                workflow_id,
                reject_reason.strip(),
            )

            refresh_workflow_state(show_error=True)
            append_log(f"대표 반려 : {reject_reason.strip()}")
            st.success("반려 처리가 완료되었습니다.")
            st.rerun()

        except Exception as exc:
            refresh_workflow_state(show_error=False)
            append_log(f"반려 처리 확인 : {exc}")
            st.warning(
                "Workflow 상태가 이미 변경되었거나 승인 대기 상태가 아닙니다. "
                "최신 상태로 자동 갱신했습니다."
            )


st.divider()


# -------------------------------------------------
# Workflow 새로고침
# -------------------------------------------------

refresh = st.button(
    "지금 새로고침",
    use_container_width=True,
)

if refresh:
    if st.session_state.workflow_id:
        if refresh_workflow_state(show_error=True):
            append_log("Workflow 수동 새로고침")
            st.rerun()
    else:
        st.warning("선택된 Workflow가 없습니다.")


st.divider()


# -------------------------------------------------
# 실행 로그
# -------------------------------------------------

st.subheader("실행 로그")

if len(st.session_state.logs) == 0:
    st.info("로그가 없습니다.")

else:
    for log in reversed(st.session_state.logs):
        st.write("•", log)


# -------------------------------------------------
# Runtime Monitor
# -------------------------------------------------

st.divider()

st.subheader("Runtime Monitor")

if st.session_state.result:
    r = st.session_state.result

    monitor = {
        "Workflow": st.session_state.workflow_id,
        "Business Type": r.get("business_type"),
        "Execution Engine": r.get("execution_engine"),
        "Development Mode": r.get("development_mode"),
        "Status": r.get("status"),
        "Approval": r.get("approval_status"),
        "Engine Status": r.get("engine_status"),
        "Next Action": r.get("next_action"),
    }

    st.json(monitor)

else:
    st.info("실행 중인 Workflow가 없습니다.")


# -------------------------------------------------
# Development Result
# -------------------------------------------------

if st.session_state.result:
    development_result = st.session_state.result.get("development_result")

    if development_result:
        st.divider()
        st.subheader("Development Engine")
        st.json(development_result)


# -------------------------------------------------
# Push Result
# -------------------------------------------------

if st.session_state.result:
    push_result = st.session_state.result.get("push_result")

    if push_result:
        st.divider()
        st.subheader("Git Push")
        st.json(push_result)


# -------------------------------------------------
# Footer
# -------------------------------------------------

st.divider()

st.caption("Business AI OS Release V2.4")
st.caption("Official Headquarters")

if st.session_state.auto_refresh:
    st.caption(f"자동 새로고침 : {AUTO_REFRESH_SECONDS}초")
    enable_browser_auto_refresh(AUTO_REFRESH_SECONDS)
