import streamlit as st
from dotenv import load_dotenv

load_dotenv()

st.set_page_config(
    page_title="Business AI OS",
    page_icon="🤖",
    layout="wide"
)

st.sidebar.title("Business AI OS")

menu = st.sidebar.radio(
    "메뉴",
    [
        "🏠 대시보드",
        "🤖 AI CEO",
        "📁 회사 자산",
        "👥 AI 직원",
        "📂 프로젝트",
        "📋 운영보고",
        "⚙ 설정"
    ]
)

st.title(menu)

if menu == "🏠 대시보드":

    st.subheader("회사 상태")

    col1, col2, col3, col4 = st.columns(4)

    col1.metric("AI CEO", "정상")
    col2.metric("회사 자산", "확인 필요")
    col3.metric("승인 요청", "0건")
    col4.metric("운영 상태", "개발 중")

    st.divider()

    st.subheader("연결 상태")

    st.write("🟢 OpenAI")
    st.write("🟢 Google Drive")
    st.write("⚪ Google Docs")
    st.write("⚪ Google Sheets")
    st.write("⚪ Gmail")
    st.write("⚪ GitHub")
    st.write("⚪ Zapier")


elif menu == "🤖 AI CEO":

    st.subheader("대표 지시")

    command = st.text_area("", height=180)

    uploaded_files = st.file_uploader(
        "파일 첨부",
        accept_multiple_files=True
    )

    if st.button("AI CEO 실행"):

        from core.ai_brain import AIBrain

        brain = AIBrain()

        files = [f.name for f in uploaded_files] if uploaded_files else []

        result = brain.analyze(
            command,
            assets=f"첨부파일 : {files}"
        )

        st.markdown("## AI CEO 결과")
        st.write(result)


elif menu == "📁 회사 자산":

    st.subheader("회사 자산")

    st.markdown("### Google Drive 주요 자산")

    try:
        from core.asset_manager import AssetManager

        asset_manager = AssetManager()
        drive_assets = asset_manager.search("")

        if drive_assets:
            for asset in drive_assets:
                st.write(f"📁 {asset}")
        else:
            st.warning("확인된 회사 자산이 없습니다.")

    except Exception as e:
        st.error(f"회사 자산을 불러오는 중 오류가 발생했습니다: {e}")

    st.divider()

    if st.button("AI CEO 자산 점검"):

        from core.ai_brain import AIBrain

        brain = AIBrain()

        result = brain.analyze(
            """
현재 회사 자산 목록을 기준으로 자산 상태를 점검하라.

기존 자산을 먼저 활용하고,
부족한 자산만 보고하라.
"""
        )

        st.markdown("## AI CEO 자산 점검 보고")
        st.write(result)

elif menu == "👥 AI 직원":

    st.subheader("AI 직원")


elif menu == "📂 프로젝트":

    st.subheader("프로젝트")


elif menu == "📋 운영보고":

    st.subheader("운영보고")


elif menu == "⚙ 설정":

    st.subheader("Business AI OS 설정")

    st.markdown("### 연결 상태")

    st.checkbox("OpenAI", value=True, disabled=True)
    st.checkbox("Google Drive", value=True, disabled=True)
    st.checkbox("Google Docs", value=False, disabled=True)
    st.checkbox("Google Sheets", value=False, disabled=True)
    st.checkbox("Gmail", value=False, disabled=True)
    st.checkbox("GitHub", value=False, disabled=True)
    st.checkbox("Zapier", value=False, disabled=True)

    st.divider()

    if st.button("AI CEO 연결 상태 점검"):

        from core.ai_brain import AIBrain

        brain = AIBrain()

        result = brain.analyze(
            """
현재 Business AI OS 연결 상태를 점검하라.

OpenAI : 연결
Google Drive : 연결
Google Docs : 미연결
Google Sheets : 미연결
Gmail : 미연결
GitHub : 미연결
Zapier : 미연결

대표 승인 없이 연결 가능한 것은 스스로 연결 계획을 수립하고,
대표 승인이 필요한 것만 승인 요청서를 작성하라.
"""
        )

        st.markdown("## AI CEO 보고")
        st.write(result)