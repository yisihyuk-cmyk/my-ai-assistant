import streamlit as st
import json
import io
import sqlite3
import time
from datetime import datetime
from google import genai
from google.genai import types
from google.oauth2 import service_account
from googleapiclient.discovery import build
from streamlit_mic_recorder import speech_to_text
from gtts import gTTS

st.set_page_config(page_title="2int의 AI 비서 태민", page_icon="🤖", layout="wide")

# 1. DB 초기화
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

# 2. 인증
api_key = st.secrets.get("GEMINI_API_KEY")
calendar_id = st.secrets.get("CALENDAR_ID", "primary")
service_account_str = st.secrets.get("GCP_SERVICE_ACCOUNT_JSON")

if not api_key or not service_account_str:
    st.error("API 키 또는 서비스 계정 설정(Secrets)을 확인해주세요.")
    st.stop()

client = genai.Client(api_key=api_key)

service_account_info = json.loads(service_account_str)
creds = service_account.Credentials.from_service_account_info(
    service_account_info,
    scopes=["https://www.googleapis.com/auth/calendar"]
)
service = build("calendar", "v3", credentials=creds)

# 3. 비서 도구
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
        
        res = [f"- {e.get('summary', '제목 없음')} ({e['start'].get('dateTime', e['start'].get('date'))})" for e in events]
        return "\n".join(res)
    except Exception as e:
        return f"일정 조회 실패: {str(e)}"

def delete_calendar_event(query_title: str) -> str:
    """캘린더 일정을 삭제합니다."""
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
            return f"'{query_title}' 관련 캘린더 일정을 찾지 못했습니다."
        
        target = events[0]
        service.events().delete(calendarId=calendar_id, eventId=target['id']).execute()
        return f"일정 삭제 완료: '{target.get('summary')}' 삭제되었습니다."
    except Exception as e:
        return f"일정 삭제 실패: {str(e)}"

def update_calendar_event(query_title: str, new_summary: str = "", new_start_iso: str = "", new_end_iso: str = "") -> str:
    """캘린더 일정을 수정합니다."""
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
            return f"수정할 '{query_title}' 일정을 찾지 못했습니다."
        
        target = events[0]
        if new_summary:
            target['summary'] = new_summary
        if new_start_iso:
            target['start'] = {'dateTime': new_start_iso, 'timeZone': 'Asia/Seoul'}
        if new_end_iso:
            target['end'] = {'dateTime': new_end_iso, 'timeZone': 'Asia/Seoul'}
            
        service.events().update(calendarId=calendar_id, eventId=target['id'], body=target).execute()
        return f"일정 수정 완료: '{target.get('summary')}' 정보가 수정되었습니다."
    except Exception as e:
        return f"일정 수정 실패: {str(e)}"

def save_archive_note(content: str, category: str = "일반메모") -> str:
    """아이디어, 할 일, 메모를 아카이브에 기록합니다."""
    try:
        conn = sqlite3.connect("assistant_archive.db")
        c = conn.cursor()
        now_time = datetime.now().strftime("%m-%d %H:%M")
        c.execute("INSERT INTO archives (category, content, created_at) VALUES (?, ?, ?)", 
                  (category, content, now_time))
        conn.commit()
        conn.close()
        return f"[{category}] 저장 완료: '{content}'"
    except Exception as e:
        return f"메모 저장 실패: {str(e)}"

def search_archive_notes(category: str = "", keyword: str = "") -> str:
    """저장된 아카이브 메모 및 할 일을 검색합니다."""
    try:
        conn = sqlite3.connect("assistant_archive.db")
        c = conn.cursor()
        query = "SELECT id, category, content, created_at FROM archives WHERE 1=1"
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
        
        res = [f"- [{row[1]} | {row[3]}] {row[2]}" for row in rows]
        return "\n".join(res)
    except Exception as e:
        return f"메모 조회 실패: {str(e)}"

def delete_archive_note(keyword: str) -> str:
    """핵심 키워드를 검색하여 해당하는 아카이브 메모를 삭제합니다."""
    try:
        conn = sqlite3.connect("assistant_archive.db")
        c = conn.cursor()
        # 단어 조각 검색
        clean_key = keyword.replace("관련해서", "").replace("메모", "").replace("삭제해줘", "").strip()
        c.execute("SELECT id, content FROM archives WHERE content LIKE ? ORDER BY id DESC LIMIT 1", (f"%{clean_key}%",))
        target = c.fetchone()
        if not target:
            conn.close()
            return f"'{clean_key}' 관련 메모를 찾지 못했습니다."
        
        note_id, content = target
        c.execute("DELETE FROM archives WHERE id = ?", (note_id,))
        conn.commit()
        conn.close()
        return f"메모 삭제 완료: '{content}' 항목을 삭제했습니다."
    except Exception as e:
        return f"메모 삭제 실패: {str(e)}"

tools = [
    add_calendar_event, get_calendar_events, delete_calendar_event, update_calendar_event,
    save_archive_note, search_archive_notes, delete_archive_note
]

# 4. 사이드바: 아카이브 보관함 & 즉시 삭제
with st.sidebar:
    st.header("🗂️ 아카이브 보관함")
    conn = sqlite3.connect("assistant_archive.db")
    c = conn.cursor()
    c.execute("SELECT id, category, content, created_at FROM archives ORDER BY id DESC LIMIT 20")
    recent_notes = c.fetchall()
    conn.close()
    
    if recent_notes:
        for note_id, cat, content, date_str in recent_notes:
            with st.expander(f"[{cat}] {content[:10]}... ({date_str})"):
                st.write(f"**카테고리:** {cat}")
                st.write(f"**내용:** {content}")
                st.caption(f"기록 시간: {date_str}")
                if st.button("🗑️ 즉시 삭제", key=f"del_{note_id}"):
                    conn = sqlite3.connect("assistant_archive.db")
                    c = conn.cursor()
                    c.execute("DELETE FROM archives WHERE id = ?", (note_id,))
                    conn.commit()
                    conn.close()
                    st.toast("메모가 삭제되었습니다!")
                    st.rerun()
    else:
        st.caption("저장된 메모나 아이디어가 없습니다.")

# 5. 메인 화면 UI
st.title("🤖 2int의 AI 비서 태민")

if "messages" not in st.session_state:
    st.session_state.messages = []
if "last_voice_processed" not in st.session_state:
    st.session_state.last_voice_processed = ""

for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.write(msg["content"])
        if "audio" in msg and msg["audio"]:
            st.audio(msg["audio"], format="audio/mp3")

st.write("---")
col1, col2 = st.columns([1, 4])
with col1:
    voice_input = speech_to_text(language="ko", start_prompt="🎤 말하기", stop_prompt="⏹️ 녹음 완료", key="STT")

text_input = st.chat_input("일정, 할 일, 메모를 말씀해주세요...")

current_user_prompt = None
if voice_input and voice_input != st.session_state.last_voice_processed:
    current_user_prompt = voice_input
    st.session_state.last_voice_processed = voice_input
elif text_input:
    current_user_prompt = text_input

# 6. 질문 처리 및 AI 응답
if current_user_prompt:
    st.session_state.messages.append({"role": "user", "content": current_user_prompt})
    with st.chat_message("user"):
        st.write(current_user_prompt)

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    system_prompt = (
        f"너의 이름은 '태민'이야. 개인 전담 AI 비서야. "
        f"음성 재생에 알맞도록 특수문자를 최소화하고 친절하고 간결한 대화체로 답해줘. "
        f"현재 시간은 {now_str} (한국 표준시)야. "
        f"- 특정 약속/일정: 구글 캘린더 도구 사용 "
        f"- 아이디어/메모/할 일 저장: save_archive_note 사용 "
        f"- 메모/할 일 조회: search_archive_notes 사용 "
        f"- 메모/할 일 삭제 요청 시: 사용자의 긴 문장에서 대상 키워드(예: '흥국생명')만 추출해 delete_archive_note를 반드시 실행해줘."
    )

    with st.chat_message("assistant"):
        with st.spinner("태민이가 확인하고 있습니다..."):
            reply_text = ""
            for attempt in range(2):
                try:
                    response = client.models.generate_content(
                        model="gemini-3.6-flash",
                        contents=current_user_prompt,
                        config=types.GenerateContentConfig(
                            tools=tools,
                            system_instruction=system_prompt,
                            temperature=0.1
                        )
                    )
                    reply_text = response.text if response.text else "처리를 완료했습니다."
                    break
                except Exception as ex:
                    err_str = str(ex)
                    if "429" in err_str or "RESOURCE_EXHAUSTED" in err_str:
                        if attempt == 0:
                            time.sleep(3)  # 3초 대기 후 1회 자동 재시도
                            continue
                        reply_text = "요청이 잠시 몰렸습니다. 10~20초 뒤에 다시 시도해 주세요."
                    else:
                        reply_text = f"오류가 발생했습니다: {err_str}"

            st.write(reply_text)

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
