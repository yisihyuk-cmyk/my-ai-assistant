import streamlit as st
from datetime import datetime
import services
from ai_engine import generate_daily_briefing, generate_evening_briefing, chat_with_taemin

# --- 1. 기본 페이지 설정 ---
st.set_page_config(
    page_title="태민이 - 나만의 AI 비서",
    page_icon="✨",
    layout="wide",
    initial_sidebar_state="auto"
)

# --- 2. 커스텀 CSS (모바일 반응형 & 하단 입력바 고정) ---
st.markdown("""
<style>
.main .block-container {
    padding-top: 1.5rem;
    padding-bottom: 110px !important;
    max-width: 800px;
}

/* 상단 브리핑 버튼 스타일 */
.stButton button {
    border-radius: 12px;
    font-weight: 600;
}

/* 하단 고정 입력 바 컨테이너 */
.fixed-bottom-bar {
    position: fixed;
    bottom: 0;
    left: 0;
    right: 0;
    background-color: var(--background-color, #ffffff);
    padding: 10px 16px 20px 16px;
    border-top: 1px solid rgba(128, 128, 128, 0.2);
    z-index: 999;
}

div[data-testid="stForm"] button {
    height: 44px;
    width: 100%;
    border-radius: 10px;
    padding: 0;
}
div[data-testid="stTextInput"] input {
    height: 44px;
    border-radius: 10px;
}
</style>
""", unsafe_allow_html=True)

# --- 3. 세션 상태 초기화 ---
if "messages" not in st.session_state:
    st.session_state.messages = []

if "submitted_prompt" not in st.session_state:
    st.session_state.submitted_prompt = ""

# --- 4. 사이드바 (시트 아카이브 및 관리) ---
with st.sidebar:
    st.title("📁 태민이 서재 & 아카이브")
    
    if st.button("🔄 시트 새로고침", use_container_width=True):
        st.rerun()
        
    notes = services.get_all_notes(limit=20)
    if notes:
        for row in notes:
            time_val = row.get("시간", row.get("일시", ""))
            category = row.get("분류", row.get("카테고리", "메모"))
            content = row.get("내용", "")
            with st.expander(f"[{category}] {content[:15]}..."):
                st.caption(f"🕒 {time_val}")
                st.write(content)
    else:
        st.caption("기록된 메모가 없거나 시트 연결을 확인 중입니다.")

# --- 5. 본문 상단 헤더 & 브리핑 버튼 (원래 자리 복구) ---
st.title("✨ 나만의 AI 비서, 태민이")

# 아침 브리핑 & 저녁 브리핑 본문 상단 나란히 배치
col_morning, col_evening = st.columns(2)

with col_morning:
    if st.button("🌅 오늘 아침 브리핑", use_container_width=True):
        with st.spinner("오늘 일정, 할 일, 이동 시간을 분석하고 있어요..."):
            briefing = generate_daily_briefing()
            st.session_state.messages.append({"role": "assistant", "content": briefing})
            st.rerun()

with col_evening:
    if st.button("🌙 저녁 마무리 브리핑", use_container_width=True):
        with st.spinner("오늘 하루 정리와 미완료 할 일을 체크하고 있어요..."):
            evening_msg = generate_evening_briefing()
            st.session_state.messages.append({"role": "assistant", "content": evening_msg})
            st.rerun()

st.markdown("---")

# --- 6. 대화 히스토리 출력 ---
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

# --- 7. 하단 고정 커스텀 입력바 ---
def handle_submit():
    text = st.session_state.get("custom_text_input", "").strip()
    if text:
        st.session_state.messages.append({"role": "user", "content": text})
        st.session_state.submitted_prompt = text
        st.session_state.custom_text_input = ""

st.markdown('<div class="fixed-bottom-bar">', unsafe_allow_html=True)

with st.form(key="chat_bottom_form", clear_on_submit=False):
    col_input, col_mic, col_submit = st.columns([0.74, 0.13, 0.13])
    
    with col_input:
        st.text_input(
            "메시지 입력",
            key="custom_text_input",
            placeholder="태민이에게 질문이나 할 일을 남겨보세요...",
            label_visibility="collapsed"
        )
    with col_mic:
        mic_clicked = st.form_submit_button("🎤", help="음성으로 말하기")
    with col_submit:
        send_clicked = st.form_submit_button("전송", on_click=handle_submit)

st.markdown('</div>', unsafe_allow_html=True)

# --- 8. 이벤트 및 비서 응답 처리 ---
if mic_clicked:
    st.info("🎙️ 마이크가 활성화되었습니다. (브라우저 마이크 접근 권한을 확인해주세요)")

if st.session_state.submitted_prompt:
    current_prompt = st.session_state.submitted_prompt
    st.session_state.submitted_prompt = ""
    
    with st.chat_message("assistant"):
        with st.spinner("태민이가 확인하고 있어요..."):
            reply = chat_with_taemin(current_prompt)
            st.markdown(reply)
            st.session_state.messages.append({"role": "assistant", "content": reply})
    st.rerun()
