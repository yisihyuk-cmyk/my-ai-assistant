import streamlit as st
import json
import io
from datetime import datetime
from google import genai
from google.genai import types
from google.oauth2 import service_account
from googleapiclient.discovery import build
from streamlit_mic_recorder import speech_to_text
from gtts import gTTS

st.set_page_config(page_title="2int의 AI 비서 태민", page_icon="🤖")
st.title("🤖 2int의 AI 비서 태민")

# 1. 인증 정보 확인
api_key = st.secrets.get("GEMINI_API_KEY")
calendar_id = st.secrets.get("CALENDAR_ID", "primary")
service_account_str = st.secrets.get("GCP_SERVICE_ACCOUNT_JSON")

if not api_key or not service_account_str:
    st.error("API 키 또는 서비스 계정 설정(Secrets)을 확인해주세요.")
    st.stop()

client = genai.Client(api_key=api_key)

# 구글 캘린더 클라이언트 준비
service_account_info = json.loads(service_account_str)
creds = service_account.Credentials.from_service_account_info(
    service_account_info,
    scopes=["https://www.googleapis.com/auth/calendar"]
)
service = build("calendar", "v3", credentials=creds)

# 2. 비서 도구 (일정 등록 / 일정 조회)
def add_calendar_event(summary: str, start_iso: str, end_iso: str, description: str = "") -> str:
    """구글 캘린더에 일정을 등록합니다. 시간은 한국 표준시 ISO 형식(예: 2026-09-15T14:00:00+09:00)이어야 합니다."""
    try:
        event = {
            'summary': summary,
            'description': description,
            'start': {'dateTime': start_iso, 'timeZone': 'Asia/Seoul'},
            'end': {'dateTime': end_iso, 'timeZone': 'Asia/Seoul'},
        }
        service.events().insert(calendarId=calendar_id, body=event).execute()
        return f"일정 등록 완료: '{summary}' ({start_iso} ~ {end_iso})"
    except Exception as e:
        return f"일정 등록 실패: {str(e)}"

def get_calendar_events(days: int = 7) -> str:
    """오늘부터 향후 N일 동안의 구글 캘린더 일정을 조회합니다."""
    try:
        now = datetime.utcnow().isoformat() + 'Z'
        events_result = service.events().list(
            calendarId=calendar_id,
            timeMin=now,
            maxResults=15,
            singleEvents=True,
            orderBy='startTime'
        ).execute()
        events = events_result.get('items', [])
        if not events:
            return "예정된 일정이 없습니다."
        
        res = []
        for e in events:
            start = e['start'].get('dateTime', e['start'].get('date'))
            res.append(f"- {e.get('summary', '제목 없음')} ({start})")
        return "\n".join(res)
    except Exception as e:
        return f"일정 조회 실패: {str(e)}"

tools = [add_calendar_event, get_calendar_events]

# 3. 대화 세션 관리
if "messages" not in st.session_state:
    st.session_state.messages = []

# 이전 대화 내역 출력
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.write(msg["content"])
        if "audio" in msg and msg["audio"]:
            st.audio(msg["audio"], format="audio/mp3")

# 4. 음성 인식(STT) 마이크 버튼 & 텍스트 입력 처리
st.write("---")
col1, col2 = st.columns([1, 4])
with col1:
    # 한국어 음성 인식 마이크 버튼
    voice_prompt = speech_to_text(language="ko", start_prompt="🎤 말하기", stop_prompt="⏹️ 녹음 완료", key="STT")

# 사용자 입력 결정 (음성 입력 또는 텍스트 입력)
text_prompt = st.chat_input("태민이에게 일정이나 할 일을 말씀해주세요...")
user_input = voice_prompt if voice_prompt else text_prompt

# 5. 질문 처리 및 AI 응답
if user_input:
    st.session_state.messages.append({"role": "user", "content": user_input})
    with st.chat_message("user"):
        st.write(user_input)

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    system_prompt = (
        f"너의 이름은 '태민'이야. 사용자를 든든하고 똑똑하게 돕는 개인 전담 AI 비서야. "
        f"답변은 음성으로 읽어줄 때 자연스럽도록 특수문자를 너무 많이 쓰지 말고, 정중하고 친절하게 대화체로 답해줘. "
        f"현재 시간은 {now_str} (한국 표준시)야. "
        f"일정 등록 요청 시에는 시간을 계산해 add_calendar_event 도구를 사용하고, "
        f"일정 질문이 오면 get_calendar_events 도구를 호출해 확인한 뒤 알려줘."
    )

    with st.chat_message("assistant"):
        with st.spinner("태민이가 확인하고 있습니다..."):
            try:
                response = client.models.generate_content(
                    model="gemini-3.6-flash",
                    contents=user_input,
                    config=types.GenerateContentConfig(
                        tools=tools,
                        system_instruction=system_prompt,
                        temperature=0.2
                    )
                )
                reply_text = response.text if response.text else "네, 처리를 완료했습니다."
            except Exception as ex:
                reply_text = f"오류가 발생했습니다: {str(ex)}"

            st.write(reply_text)

            # 음성 생성 (TTS)
            try:
                tts = gTTS(text=reply_text, lang='ko')
                audio_fp = io.BytesIO()
                tts.write_to_fp(audio_fp)
                audio_fp.seek(0)
                audio_bytes = audio_fp.read()
                st.audio(audio_bytes, format="audio/mp3", autoplay=True)
                st.session_state.messages.append({"role": "assistant", "content": reply_text, "audio": audio_bytes})
            except Exception:
                # TTS 오류 시 텍스트만 저장
                st.session_state.messages.append({"role": "assistant", "content": reply_text})
