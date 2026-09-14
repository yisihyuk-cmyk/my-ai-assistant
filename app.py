import streamlit as st
import json
import io
import sqlite3
from datetime import datetime
from google import genai
from google.genai import types
from google.oauth2 import service_account
from googleapiclient.discovery import build
from streamlit_mic_recorder import speech_to_text
from gtts import gTTS

st.set_page_config(page_title="2int의 AI 비서 태민", page_icon="🤖", layout="wide")

# 1. 로컬 데이터베이스 초기화 (메모 및 아카이브용)
def init_db():
    conn = sqlite3.connect("assistant_archive.db")
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS archives (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            category TEXT,
            content TEXT,
            created_at TEXT
        )
    """)
    conn.commit()
    conn.close()

init_db()

# 2. 인증 정보 확인
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

# 3. 비서 도구 (캘린더 + 아카이브 도구 모음)

# [캘린더 도구]
def add_calendar_event(summary: str, start_iso: str, end_iso: str, description: str = "") -> str:
    """구글 캘린더에 새 일정을 등록합니다."""
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

def get_calendar_events(days: int = 14) -> str:
    """향후 구글 캘린더 일정을 조회합니다."""
    try:
        now = datetime.utcnow().isoformat() + 'Z'
        events_result = service.events().list(
            calendarId=calendar_id,
            timeMin=now,
            maxResults=20,
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

def delete_calendar_event(query_title: str) -> str:
    """캘린더 일정을 검색하여 삭제합니다."""
    try:
        now = datetime.utcnow().isoformat() + 'Z'
        events_result = service.events().list(
            calendarId=calendar_id,
            timeMin=now,
            q=query_title,
            maxResults=5,
            singleEvents=True
        ).execute()
        events = events_result.get('items', [])
        if not events:
            return f"'{query_title}' 관련 일정을 찾을 수 없어 삭제하지 못했습니다."
        
        target = events[0]
        service.events().delete(calendarId=calendar_id, eventId=target['id']).execute()
        return f"일정 삭제 완료: '{target.get('summary')}' 일정을 삭제했습니다."
    except Exception as e:
        return f"일정 삭제 실패: {str(e)}"

def update_calendar_event(query_title: str, new_summary: str = "", new_start_iso: str = "", new_end_iso: str = "") -> str:
    """기존 일정의 제목이나 시간을 수정합니다."""
    try:
        now = datetime.utcnow().isoformat() + 'Z'
        events_result = service.events().list(
            calendarId=calendar_id,
            timeMin=now,
            q=query_title,
            maxResults=5,
            singleEvents=True
        ).execute()
        events = events_result.get('items', [])
        if not events:
            return f"수정할 '{query_title}' 관련 일정을 찾지 못했습니다."
        
        target = events[0]
        if new_summary:
            target['summary'] = new_summary
        if new_start_iso:
            target['start'] = {'dateTime': new_start_iso, 'timeZone': 'Asia/Seoul'}
        if new_end_iso:
            target['end'] = {'dateTime': new_end_iso, 'timeZone': 'Asia/Seoul'}
            
        service.events().update(calendarId=calendar_id, eventId=target['id'], body=target).execute()
        return f"일정 수정 완료: '{target.get('summary')}' 정보가 업데이트되었습니다."
    except Exception as e:
        return f"일정 수정 실패: {str(e)}"

# [아카이브/메모 도구]
def save_archive_note(content: str, category: str = "일반메모") -> str:
    """아이디어, 할 일(To-Do), 생각, 중요 메모를 카테고리별로 아카이브에 기록합니다. (category는 '아이디어', '할일', '창작', '일반메모' 중 선택)"""
    try:
        conn = sqlite3.connect("assistant_archive.db")
        c = conn.cursor()
        now_time = datetime.now().strftime("%m-%d %H:%M")
        c.execute("INSERT INTO archives (category, content, created_at) VALUES (?, ?, ?)", 
                  (category, content, now_time))
        conn.commit()
        conn.close()
        return f"[{category}] 아카이빙 완료: '{content}'"
    except Exception as e:
        return f"메모 저장 실패: {str(e)}"

def search_archive_notes(category: str = "", keyword: str = "") -> str:
    """저장된 아카이브 메모 및 할 일을 검색하거나 조회합니다."""
    try:
        conn = sqlite3.connect("assistant_archive.db")
        c = conn.cursor()
        query = "SELECT category, content, created_at FROM archives WHERE 1=1"
        params = []
        if category:
            query += " AND category LIKE ?"
            params.append(f"%{category}%")
        if keyword:
            query += " AND content LIKE ?"
            params.append(f"%{keyword}%")
        query += " ORDER BY id DESC LIMIT 10"
        
        c.execute(query, params)
        rows = c.fetchall()
        conn.close()
        
        if not rows:
            return "해당하는 메모나 기록이 없습니다."
        
        res = [f"- [{cat} | {time}] {text}" for cat, text, time in rows]
        return "\n".join(res)
    except Exception as e:
        return f"메모 조회 실패: {str(e)}"

tools = [
    add_calendar_event, get_calendar_events, delete_calendar_event, update_calendar_event,
    save_archive_note, search_archive_notes
]

# 4. 사이드바: 아카이브된 메모 모아보기
with st.sidebar:
    st.header("🗂️ 아카이브 보관함")
    conn = sqlite3.connect("assistant_archive.db")
    c = conn.cursor()
    c.execute("SELECT category, content, created_at FROM archives ORDER BY id DESC LIMIT 15")
    recent_notes = c.fetchall()
    conn.close()
    
    if recent_notes:
        for cat, content, date_str in recent_notes:
            with st.expander(f"[{cat}] {content[:15]}... ({date_str})"):
                st.write(f"**카테고리:** {cat}")
                st.write(f"**내용:** {content}")
                st.caption(f"기록 시간: {date_str}")
    else:
        st.caption("아직 기록된 메모나 아이디어가 없습니다.")

# 5. 메인 화면 및 대화 영역
st.title("🤖 2int의 AI 비서 태민")

if "messages" not in st.session_state:
    st.session_state.messages = []

for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.write(msg["content"])
        if "audio" in msg and msg["audio"]:
            st.audio(msg["audio"], format="audio/mp3")

# 음성 및 텍스트 입력 UI
st.write("---")
col1, col2 = st.columns([1, 4])
with col1:
    voice_prompt = speech_to_text(language="ko", start_prompt="🎤 말하기", stop_prompt="⏹️ 녹음 완료", key="STT")

text_prompt = st.chat_input("일정, 할 일, 떠오른 아이디어를 말씀해주세요...")
user_input = voice_prompt if voice_prompt else text_prompt

# 6. 질문 처리 및 AI 실행
if user_input:
    st.session_state.messages.append({"role": "user", "content": user_input})
    with st.chat_message("user"):
        st.write(user_input)

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    system_prompt = (
        f"너의 이름은 '태민'이야. 사용자의 일정, 할 일, 영감과 아이디어를 종합 관리하는 든든한 개인 AI 비서야. "
        f"음성으로 들을 때 부드럽고 자연스럽도록 특수문자를 남발하지 말고 정중하고 명확한 대화체로 답해줘. "
        f"현재 시간은 {now_str} (한국 표준시)야. "
        f"- 특정 시간/날짜가 정해진 약속/일정은 구글 캘린더 도구(add/get/delete/update_calendar_event)를 사용해. "
        f"- 날짜/시간 약속이 아닌 생각, 아이디어, 글감, 체크리스트, 할 일 기록은 save_archive_note 도구를 사용해 적절한 카테고리('아이디어', '할일', '창작', '일반메모')로 보관해줘. "
        f"- 메모나 할 일 조회를 요청하면 search_archive_notes 도구를 사용해 찾아 알려줘."
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

            # 음성 생성
            try:
                tts = gTTS(text=reply_text, lang='ko')
                audio_fp = io.BytesIO()
                tts.write_to_fp(audio_fp)
                audio_fp.seek(0)
                audio_bytes = audio_fp.read()
                st.audio(audio_bytes, format="audio/mp3", autoplay=True)
                st.session_state.messages.append({"role": "assistant", "content": reply_text, "audio": audio_bytes})
            except Exception:
                st.session_state.messages.append({"role": "assistant", "content": reply_text})

            # 사이드바 메모 목록 실시간 갱신을 위해 새로고침
            st.rerun()
