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

.stButton button {
    border-radius: 12px;
    font-weight: 600;
}

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

if "input_mode" not in st.session_state:
    st.session_state.input_mode = "text"  # 'text' 또는 'voice'

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

# --- 5. 본문 상단 헤더 & 브리핑 버튼 ---
st.title("✨ 나만의 AI 비서, 태민이")

col_morning, col_evening = st.columns(2)

with col_morning:
    if st.button("🌅 오늘 아침 브리핑", use_container_width=True):
        with st.spinner("오늘 일정, 할 일, 이동 시간을 정리하고 있어요..."):
            briefing = generate_daily_briefing()
            # 브리핑은 음성으로도 함께 전달
            audio_bytes = services.text_to_speech(briefing)
            st.session_state.messages.append({
                "role": "assistant",
                "content": briefing,
                "audio": audio_bytes
            })
            st.rerun()

with col_evening:
    if st.button("🌙 저녁 마무리 브리핑", use_container_width=True):
        with st.spinner("오늘 하루 정리와 목소리를 준비하고 있어요..."):
            evening_msg = generate_evening_briefing()
            audio_bytes = services.text_to_speech(evening_msg)
            st.session_state.messages.append({
                "role": "assistant",
                "content": evening_msg,
                "audio": audio_bytes
            })
            st.rerun()

st.markdown("---")

# --- 6. 대화 히스토리 및 음성 출력 ---
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])
        # 음성 데이터가 첨부되어 있을 때만 오디오 플레이어 출력
        if msg.get("audio"):
            st.audio(msg["audio"], format="audio/mp3", autoplay=True)

# --- 7. 하단 고정 커스텀 입력바 ---
def handle_text_submit():
    text = st.session_state.get("custom_text_input", "").strip()
    if text:
        st.session_state.messages.append({"role": "user", "content": text})
        st.session_state.submitted_prompt = text
        st.session_state.input_mode = "text"  # 텍스트 입력 플래그
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
        send_clicked = st.form_submit_button("전송", on_click=handle_text_submit)

st.markdown('</div>', unsafe_allow_html=True)

# --- 8. 마이크 클릭 시 음성 모드 입력 처리 ---
if mic_clicked:
    # 브라우저 음성 인식 컴포넌트 호출 또는 음성 프롬프트 트리거
    st.session_state.input_mode = "voice"
    st.info("🎙️ 마이크를 통해 듣고 있습니다. (음성 질문 시 태민이가 목소리로 답변합니다)")

# --- 9. 태민이 답변 생성 (모드별 목소리 분기) ---
if st.session_state.submitted_prompt:
    current_prompt = st.session_state.submitted_prompt
    mode = st.session_state.input_mode
    st.session_state.submitted_prompt = ""
    
    with st.chat_message("assistant"):
        with st.spinner("태민이가 확인하고 있어요..."):
            reply = chat_with_taemin(current_prompt)
            st.markdown(reply)
            
            # 음성으로 불렀을 때만 ElevenLabs TTS 생성 (텍스트 입력 시엔 토큰 절약 & 무음)
            audio_bytes = None
            if mode == "voice":
                audio_bytes = services.text_to_speech(reply)
                if audio_bytes:
                    st.audio(audio_bytes, format="audio/mp3", autoplay=True)
            
            st.session_state.messages.append({
                "role": "assistant",
                "content": reply,
                "audio": audio_bytes
            })
            
    # 기본 텍스트 모드로 복귀
    st.session_state.input_mode = "text"
    st.rerun()
