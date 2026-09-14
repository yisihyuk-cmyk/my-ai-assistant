import streamlit as st
from datetime import datetime
from google.genai import types
from streamlit_mic_recorder import speech_to_text
import services
import ai_engine

st.set_page_config(page_title="2int의 AI 비서 태민", page_icon="🤖", layout="wide")

# 사이드바: 영구 구글 시트 아카이브 및 도구
with st.sidebar:
    st.header("🗂️ 구글 시트 아카이브")
    notes = services.get_all_notes(limit=25)
    
    # 창작 메모 다운로드
    creative_texts = [f"[{r[3]}] {r[2]}" for r in notes if r[1] == "영감창작"]
    if creative_texts:
        st.download_button("📝 창작 노트 다운로드 (.txt)", "\n".join(creative_texts), "creative_notes.txt", use_container_width=True)

    for row_idx, cat, content, created_at in notes:
        with st.expander(f"[{cat}] {content[:10]}... ({created_at})"):
            st.write(f"**내용:** {content}")
            c1, c2 = st.columns(2)
            with c1:
                if st.button("✉️ 메일", key=f"m_{row_idx}"):
                    if services.send_email_to_self(f"[{cat}] 메모", content):
                        st.toast("메일 전송 완료!")
            with c2:
                if st.button("🗑️ 삭제", key=f"d_{row_idx}"):
                    services.delete_sheet_row(row_idx)
                    st.toast("시트에서 삭제됨!")
                    st.rerun()
            if cat == "영감창작":
                if st.button("💡 아이디어 발전", key=f"dev_{row_idx}", use_container_width=True):
                    with st.spinner("생각 발전 중..."):
                        st.info(ai_engine.develop_creative_idea(content))

st.markdown("### 🤖 2int의 AI 비서 태민")

# 상단 버튼 & 음소거 토글
b1, b2, b3 = st.columns([2, 2, 2])
trig_m = b1.button("☀️ 아침 브리핑", use_container_width=True)
trig_e = b2.button("🌙 저녁 마무리", use_container_width=True)
mute_mode = b3.toggle("🔇 텍스트만 (음성 끄기)", value=False)

if "messages" not in st.session_state:
    st.session_state.messages = []

for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.write(msg["content"])
        if msg.get("audio"): st.audio(msg["audio"], format="audio/mp3")

# 입력 컨트롤
c_mic, c_space = st.columns([1, 4])
with c_mic:
    voice_in = speech_to_text(language="ko", start_prompt="🎤 말하기", stop_prompt="⏹️ 완료", key="mic")
text_in = st.chat_input("무엇이든 물어보거나 부탁해...")

prompt, is_typed = None, False
if trig_m: prompt = "오늘 아침 브리핑 시작해줘"
elif trig_e: prompt = "오늘 저녁 마무리 브리핑 시작해줘"
elif text_in: prompt, is_typed = text_in, True
elif voice_in: prompt = voice_in

if prompt:
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"): st.write(prompt)

    ai_engine.auto_detect_and_remember(prompt)

    with st.chat_message("assistant"):
        with st.spinner("태민이가 확인하고 있어..."):
            if trig_m: reply = ai_engine.get_briefing(is_morning=True)
            elif trig_e: reply = ai_engine.get_briefing(is_morning=False)
            else:
                sys_p = f"너는 정수의 전담 비서 태민이야. 다정한 반말로 명확하게 답해. 일정/할일은 add_calendar_event 도구 사용. 현재: {datetime.now()}"
                reply = ai_engine.generate_with_key_rotation(prompt, sys_p, use_tools=True)

            st.write(reply)
            
            # 음성 조건 (음소거 off + 타이핑 아님 또는 브리핑)
            audio_bytes = None
            if not mute_mode and (not is_typed or trig_m or trig_e):
                audio_bytes = services.generate_elevenlabs_audio(reply)
                if audio_bytes: st.audio(audio_bytes, format="audio/mp3", autoplay=True)

            st.session_state.messages.append({"role": "assistant", "content": reply, "audio": audio_bytes})
