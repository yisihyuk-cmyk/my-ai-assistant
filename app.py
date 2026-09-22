import streamlit as st
from datetime import datetime
from streamlit_mic_recorder import speech_to_text  # <-- 이 줄 추가
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
    st.session_state.input_mode = "text"

# [추가] 무한 루프 방지용 이전 음성 텍스트 추적
if "last_voice_input" not in st.session_state:
    st.session_state.last_voice_input = None

# --- 4. 사이드바 (서재 & 아카이브) ---
with st.sidebar:
    st.title("📁 태민 서재 & 아카이브")
    if st.button("🔄 시트 새로고침", use_container_width=True):
        st.cache_data.clear()  # <-- 이 줄을 추가해서 저장된 캐시를 즉시 비워줌
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
        st.caption("기록된 메모가 없거나 시트 연결을 확인 중이야.")

# --- 5. 본문 상단 헤더 & 브리핑 버튼 ---
st.title("✨ 안녕, 태민이야!")

col_morning, col_evening = st.columns(2)

with col_morning:
    if st.button("🌅 오늘 아침 브리핑", use_container_width=True):
        with st.spinner("오늘 일정, 할 일, 이동 시간을 정리하고 있어..."):
            briefing = generate_daily_briefing()
            audio_bytes = services.text_to_speech(briefing)
            st.session_state.messages.append({
                "role": "assistant",
                "content": briefing,
                "audio": audio_bytes
            })
            st.rerun()

with col_evening:
    if st.button("🌙 저녁 마무리 브리핑", use_container_width=True):
        with st.spinner("오늘 하루 정리와 목소리를 준비하고 있어..."):
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
        if msg.get("audio"):
            st.audio(msg["audio"], format="audio/mp3", autoplay=True)

# --- 7. 하단 고정 커스텀 입력바 ---
def handle_text_submit():
    text = st.session_state.get("custom_text_input", "").strip()
    if text:
        st.session_state.messages.append({"role": "user", "content": text})
        st.session_state.submitted_prompt = text
        st.session_state.input_mode = "text"
        st.session_state.custom_text_input = ""

st.markdown('<div class="fixed-bottom-bar">', unsafe_allow_html=True)

col_form, col_mic = st.columns([0.82, 0.18])

with col_form:
    with st.form(key="chat_bottom_form", clear_on_submit=False):
        c_in, c_btn = st.columns([0.8, 0.2])
        with c_in:
            st.text_input(
                "메시지 입력",
                key="custom_text_input",
                placeholder="태민이에게 편하게 물어봐...",
                label_visibility="collapsed"
            )
        with c_btn:
            st.form_submit_button("전송", on_click=handle_text_submit)

with col_mic:
    voice_input = speech_to_text(
        language="ko",
        start_prompt="🎤",
        stop_prompt="⏹️",
        key="bottom_mic_recorder",
        use_container_width=True
    )

st.markdown('</div>', unsafe_allow_html=True)

# --- 8. 마이크 음성 인식 처리 (무한 루프 차단) ---
if voice_input and voice_input.strip():
    clean_voice = voice_input.strip()
    # 이전에 처리했던 동일한 음성 결과가 아닐 때만 최초 1회 실행
    if clean_voice != st.session_state.last_voice_input:
        st.session_state.last_voice_input = clean_voice
        st.session_state.messages.append({"role": "user", "content": clean_voice})
        st.session_state.submitted_prompt = clean_voice
        st.session_state.input_mode = "voice"
        # 여기서 rerun()을 호출하지 않아야 아래 9번 답변 생성으로 바로 넘어감!

# --- 9. 태민이 답변 생성 ---
if st.session_state.submitted_prompt:
    current_prompt = st.session_state.submitted_prompt
    mode = st.session_state.input_mode
    st.session_state.submitted_prompt = ""
    
    with st.chat_message("assistant"):
        with st.spinner("확인하고 있어..."):
            reply = chat_with_taemin(current_prompt)
            st.markdown(reply)
            
            # 텍스트 입력 시 무음(토큰 절약), 음성 대화 시에만 목소리 재생
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
            
    st.session_state.input_mode = "text"
    st.rerun()
