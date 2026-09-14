import smtplib
import requests
import gspread
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timedelta
from googleapiclient.discovery import build
from elevenlabs.client import ElevenLabs
from config import (
    CREDS, CALENDAR_ID, SPREADSHEET_ID, ELEVEN_API_KEY, 
    ELEVEN_VOICE_ID, NTFY_TOPIC, GMAIL_USER, GMAIL_PASSWORD
)

# 1. 서비스 클라이언트 초기화
calendar_service = build("calendar", "v3", credentials=CREDS)

def get_sheet():
    """구글 시트 워크시트 객체 반환"""
    gc = gspread.authorize(CREDS)
    sh = gc.open_by_key(SPREADSHEET_ID)
    return sh.sheet1

# 2. 구글 시트 영구 저장소 함수 (SQLite 대체)
def save_archive_note(content: str, category: str = "일반메모") -> str:
    try:
        sheet = get_sheet()
        now_time = datetime.now().strftime("%m-%d %H:%M")
        sheet.append_row([category, content, now_time])
        return f"보관 완료: [{category}] {content}"
    except Exception as e:
        return f"메모 저장 실패: {str(e)}"

def get_all_notes(limit: int = 30):
    """최근 메모 가져오기 (역순)"""
    try:
        sheet = get_sheet()
        rows = sheet.get_all_values()
        if len(rows) <= 1:
            return []
        data = rows[1:]  # 헤더 제외
        # (행 인덱스, category, content, created_at)
        indexed_data = [(i + 2, r[0], r[1], r[2] if len(r) > 2 else "") for i, r in enumerate(data)]
        return list(reversed(indexed_data))[:limit]
    except Exception:
        return []

def delete_sheet_row(row_idx: int):
    try:
        sheet = get_sheet()
        sheet.delete_rows(row_idx)
        return True
    except Exception:
        return False

# 3. 캘린더 & 할일 자동 정리
def add_calendar_event(summary: str, start_iso: str, end_iso: str, description: str = "") -> str:
    try:
        final_summary = summary if summary.startswith("[할일]") else f"[할일] {summary}"
        event = {
            'summary': final_summary,
            'description': "auto_delete_todo" if not description else f"auto_delete_todo | {description}",
            'start': {'dateTime': start_iso, 'timeZone': 'Asia/Seoul'},
            'end': {'dateTime': end_iso, 'timeZone': 'Asia/Seoul'},
        }
        calendar_service.events().insert(calendarId=CALENDAR_ID, body=event).execute()
        return f"할 일 등록 완료: '{final_summary}' ({start_iso} ~ {end_iso})"
    except Exception as e:
        return f"일정 등록 실패: {str(e)}"

def cleanup_past_todo_events():
    try:
        now_dt = datetime.now()
        now_iso = now_dt.isoformat() + 'Z'
        past_limit_iso = (now_dt - timedelta(days=7)).isoformat() + 'Z'
        
        events_result = calendar_service.events().list(
            calendarId=CALENDAR_ID,
            timeMin=past_limit_iso,
            timeMax=now_iso,
            singleEvents=True
        ).execute()
        for e in events_result.get('items', []):
            summary = e.get('summary', '')
            desc = e.get('description', '')
            if "[할일]" in summary or "[TODO]" in summary or desc == "auto_delete_todo":
                calendar_service.events().delete(calendarId=CALENDAR_ID, eventId=e['id']).execute()
    except Exception:
        pass

def get_day_events_str(target_date: datetime) -> str:
    try:
        day_start = target_date.replace(hour=0, minute=0, second=0, microsecond=0).isoformat() + 'Z'
        day_end = (target_date.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)).isoformat() + 'Z'
        events_result = calendar_service.events().list(
            calendarId=CALENDAR_ID, timeMin=day_start, timeMax=day_end, singleEvents=True, orderBy='startTime'
        ).execute()
        items = events_result.get('items', [])
        if not items: return "잡힌 일정 없음"
        res = []
        for e in items:
            raw = e['start'].get('dateTime', e['start'].get('date'))
            t = raw.split("T")[1][:5] if "T" in raw else "종일"
            res.append(f"{t} {e.get('summary')}")
        return ", ".join(res)
    except Exception:
        return "일정 확인 불가"

def get_calendar_events(days: int = 14) -> str:
    try:
        now = (datetime.now() - timedelta(days=1)).isoformat() + 'Z'
        events_result = calendar_service.events().list(
            calendarId=CALENDAR_ID, timeMin=now, maxResults=30, singleEvents=True, orderBy='startTime'
        ).execute()
        items = events_result.get('items', [])
        if not items: return "예정된 일정이 없습니다."
        res = [f"- {e.get('summary')} | {e['start'].get('dateTime', e['start'].get('date'))}" for e in items]
        return "\n".join(res)
    except Exception as e:
        return f"일정 조회 실패: {str(e)}"

def delete_calendar_event(query_title: str) -> str:
    try:
        now = (datetime.now() - timedelta(days=1)).isoformat() + 'Z'
        events_result = calendar_service.events().list(
            calendarId=CALENDAR_ID, timeMin=now, q=query_title, maxResults=5, singleEvents=True
        ).execute()
        items = events_result.get('items', [])
        if not items: return f"'{query_title}' 관련 일정을 찾지 못했어."
        calendar_service.events().delete(calendarId=CALENDAR_ID, eventId=items[0]['id']).execute()
        return f"'{items[0].get('summary')}' 일정을 삭제했어!"
    except Exception as e:
        return f"삭제 실패: {str(e)}"

# 4. 날씨 & 외부 전송 유틸리티
def get_current_weather(lat: float = 37.3219, lon: float = 126.8309) -> str:
    try:
        url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&current_weather=true&daily=temperature_2m_max,temperature_2m_min,precipitation_probability_max&timezone=Asia%2FSeoul"
        res = requests.get(url, timeout=5).json()
        curr, daily = res.get("current_weather", {}), res.get("daily", {})
        temp = curr.get("temperature", "-")
        max_t, min_t = daily.get("temperature_2m_max", ["-"])[0], daily.get("temperature_2m_min", ["-"])[0]
        pop = daily.get("precipitation_probability_max", [0])[0]
        w_code = curr.get("weathercode", 0)
        desc = "비/눈" if w_code in [51, 61, 71, 80] else ("흐림" if w_code in [1, 2, 3] else "맑음")
        return f"{desc}, 기온 {temp}도(최저 {min_t}도/최고 {max_t}도), 강수확률 {pop}%"
    except Exception:
        return "날씨 정보 확인 불가"

def send_push_notification(title: str, message: str):
    if not NTFY_TOPIC: return
    try:
        requests.post(f"https://ntfy.sh/{NTFY_TOPIC}", data=message.encode("utf-8"),
                      headers={"Title": title.encode("utf-8").decode("latin-1"), "Priority": "high"}, timeout=5)
    except Exception: pass

def send_email_to_self(subject: str, body: str) -> bool:
    if not GMAIL_USER or not GMAIL_PASSWORD: return False
    try:
        msg = MIMEMultipart()
        msg['From'], msg['To'], msg['Subject'] = GMAIL_USER, GMAIL_USER, f"[태민 비서] {subject}"
        msg.attach(MIMEText(body, 'plain', 'utf-8'))
        server = smtplib.SMTP_SSL('smtp.gmail.com', 465, timeout=10)
        server.login(GMAIL_USER, GMAIL_PASSWORD)
        server.send_message(msg)
        server.quit()
        return True
    except Exception: return False

def generate_elevenlabs_audio(text: str) -> bytes:
    if not ELEVEN_API_KEY: return b""
    try:
        for wrong in ["정숙", "영수", "진수", "정서", "점수"]:
            text = text.replace(wrong, "정수")
        el = ElevenLabs(api_key=ELEVEN_API_KEY)
        gen = el.text_to_speech.convert(voice_id=ELEVEN_VOICE_ID, text=text, model_id="eleven_multilingual_v2")
        return b"".join(gen)
    except Exception: return b""