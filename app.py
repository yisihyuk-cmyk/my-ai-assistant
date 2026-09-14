import streamlit as st
import json
from datetime import datetime
import google.generativeai as genai
from google.oauth2 import service_account
from googleapiclient.discovery import build

st.set_page_config(page_title="나만의 AI 비서", page_icon="🤖")
st.title("🤖 2int의 AI 비서 태민")

# 1. 인증 설정
api_key = st.secrets.get("GEMINI_API_KEY")
calendar_id = st.secrets.get("CALENDAR_ID", "primary")
service_account_str = st.secrets.get("GCP_SERVICE_ACCOUNT_JSON")

if not api_key or not service_account_str:
    st.error("API 키 또는 구글 서비스 계정 설정이 필요합니다.")
    st.stop()

genai.configure(api_key=api_key)

# 구글 캘린더 클라이언트 생성
service_account_info = json.loads(service_account_str)
creds = service_account.Credentials.from_service_account_info(
    service_account_info,
    scopes=["https://www.googleapis.com/auth/calendar"]
)
service = build("calendar", "v3", credentials=creds)

# 2. 비서 도구 (일정 등록 / 일정 조회)
def add_calendar_event(summary: str, start_iso: str, end_iso: str, description: str = "") -> str:
    """구글 캘린더에 일정을 등록합니다. 시간은 한국 표준시 ISO 형식(예: 2026-09-15T14:00:00+09:00)이어야 합니다."""
    event = {
        'summary': summary,
        'description': description,
        'start': {'dateTime': start_iso, 'timeZone': 'Asia/Seoul'},
        'end': {'dateTime': end_iso, 'timeZone': 'Asia/Seoul'},
    }
    service.events().insert(calendarId=calendar_id, body=event).execute()
    return f"구글 캘린더 등록 완료: {summary} ({start_iso} ~ {end_iso})"

def get_calendar_events(days: int = 7) -> str:
    """오늘부터 향후 N일 동안의 구글 캘린더 일정을 조회합니다."""
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

tools = [add_calendar_event, get_calendar_events]

# 3. 모델 설정
now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
model = genai.GenerativeModel(
    model_name="models/gemini-1.5-flash",
    tools=tools,
    system_instruction=(
    f"너는 신뢰할 수 있는 전문 일정 총괄 비서야. "
    f"항상 정중하고 간결하게 핵심만 보고하듯 답변해. "
    f"현재 시간은 {now_str} (KST)야. 일정을 등록해달라고 하면 시간을 명확히 계산해 add_calendar_event를 실행하고, "
    f"일정을 물어보면 get_calendar_events로 조회해서 깔끔한 글머리 기호로 요약해줘."
)
)

if "chat" not in st.session_state:
    st.session_state.chat = model.start_chat(enable_automatic_function_calling=True)

if "messages" not in st.session_state:
    st.session_state.messages = []

for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.write(msg["content"])

if user_input := st.chat_input("구글 캘린더 일정이나 할 일을 말씀해주세요..."):
    st.session_state.messages.append({"role": "user", "content": user_input})
    with st.chat_message("user"):
        st.write(user_input)

    with st.chat_message("assistant"):
        response = st.session_state.chat.send_message(user_input)
        st.write(response.text)
        st.session_state.messages.append({"role": "assistant", "content": response.text})
