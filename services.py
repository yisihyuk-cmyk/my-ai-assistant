import os
import requests
from datetime import datetime, timedelta
import streamlit as st
import gspread
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

def get_secret(key, default=""):
    if hasattr(st, "secrets") and key in st.secrets:
        return st.secrets[key]
    return os.getenv(key, default)

KAKAO_REST_API_KEY = get_secret("KAKAO_REST_API_KEY")
SPREADSHEET_NAME = get_secret("SPREADSHEET_NAME", "태민이_아카이브")
ELEVENLABS_API_KEY = get_secret("ELEVENLABS_API_KEY")
ELEVENLABS_VOICE_ID = get_secret("ELEVENLABS_VOICE_ID", "gDx7aX4UOQMthJevd64d")
CALENDAR_ID = get_secret("CALENDAR_ID", "yisihyuk@gmail.com")

# --- [1] 안산 실시간 날씨 조회 (Open-Meteo 무료 API) ---
def get_today_weather():
    """안산시 기준 오늘 날씨 요약 (최고/최저 기온, 현재 기온)"""
    try:
        # 안산시 위도/경도: 37.3219, 126.8309
        url = "https://api.open-meteo.com/v1/forecast?latitude=37.3219&longitude=126.8309&current=temperature_2m,precipitation,weather_code&daily=temperature_2m_max,temperature_2m_min&timezone=Asia%2FTokyo"
        res = requests.get(url, timeout=5)
        if res.status_code == 200:
            data = res.json()
            curr_temp = data.get("current", {}).get("temperature_2m", "-")
            precip = data.get("current", {}).get("precipitation", 0)
            daily = data.get("daily", {})
            max_temp = daily.get("temperature_2m_max", ["-"])[0]
            min_temp = daily.get("temperature_2m_min", ["-"])[0]
            
            rain_text = "비 또는 눈 예보가 있으니 우산 챙겨!" if precip > 0 else "비 소식은 없어."
            return f"현재 기온은 {curr_temp}°C, 오늘 낮 최고 {max_temp}°C / 최저 {min_temp}°C야. {rain_text}"
    except Exception as e:
        print(f"날씨 조회 실패: {e}")
    return "오늘도 일교차에 유의하고 옷 따뜻하게 챙겨 입어!"

# --- [2] ElevenLabs TTS 음성 생성 ---
def text_to_speech(text):
    if not ELEVENLABS_API_KEY or not ELEVENLABS_VOICE_ID:
        return None
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{ELEVENLABS_VOICE_ID}"
    headers = {
        "xi-api-key": ELEVENLABS_API_KEY,
        "Content-Type": "application/json"
    }
    payload = {
        "text": text,
        "model_id": "eleven_multilingual_v2",
        "voice_settings": {"stability": 0.5, "similarity_boost": 0.75}
    }
    try:
        res = requests.post(url, headers=headers, json=payload, timeout=20)
        if res.status_code == 200:
            return res.content
    except Exception as e:
        print(f"ElevenLabs 호출 실패: {e}")
    return None

# --- [3] 구글 자격증명 및 캘린더 ---
def get_gcp_credentials():
    scopes = [
        "https://www.googleapis.com/auth/calendar",
        "https://www.googleapis.com/auth/tasks",
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]
    if hasattr(st, "secrets") and "gcp_service_account" in st.secrets:
        return Credentials.from_service_account_info(dict(st.secrets["gcp_service_account"]), scopes=scopes)
    elif hasattr(st, "secrets") and "GCP_SERVICE_ACCOUNT_JSON" in st.secrets:
        import json
        return Credentials.from_service_account_info(json.loads(st.secrets["GCP_SERVICE_ACCOUNT_JSON"]), scopes=scopes)
    elif os.path.exists("credentials.json"):
        return Credentials.from_service_account_file("credentials.json", scopes=scopes)
    return None

def get_calendar_service():
    creds = get_gcp_credentials()
    if not creds:
        return None
    return build("calendar", "v3", credentials=creds)

def fetch_today_events(target_date=None):
    service = get_calendar_service()
    if not service:
        return []
    cal_id = CALENDAR_ID if CALENDAR_ID else "primary"
    
    if target_date is None:
        target_date = datetime.now()
    
    start_of_day = datetime(target_date.year, target_date.month, target_date.day, 0, 0, 0).isoformat() + "+09:00"
    end_of_day = datetime(target_date.year, target_date.month, target_date.day, 23, 59, 59).isoformat() + "+09:00"
    
    try:
        events_result = service.events().list(
            calendarId=cal_id,
            timeMin=start_of_day,
            timeMax=end_of_day,
            singleEvents=True,
            orderBy="startTime"
        ).execute()
        return events_result.get("items", [])
    except Exception as e:
        print(f"Calendar API 조회 오류 ({cal_id}): {e}")
        return []

# --- [4] 구글 Tasks 관리 ---
def get_tasks_service():
    creds = get_gcp_credentials()
    if not creds:
        return None
    return build("tasks", "v1", credentials=creds)

def add_work_task(title, due_datetime=None, notes=""):
    service = get_tasks_service()
    if not service:
        return False, "인증 실패"
    task_body = {"title": f"[할 일] {title}", "notes": notes}
    if due_datetime:
        task_body["due"] = due_datetime.strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        task = service.tasks().insert(tasklist="@default", body=task_body).execute()
        return True, task.get("id")
    except Exception as e:
        return False, str(e)

def get_active_tasks():
    service = get_tasks_service()
    if not service:
        return []
    try:
        res = service.tasks().list(tasklist="@default", showCompleted=False).execute()
        return res.get("items", [])
    except Exception as e:
        return []

def complete_or_delete_task(keyword):
    service = get_tasks_service()
    if not service:
        return False, "구글 서비스 연결 실패"
    try:
        clean_keyword = keyword.replace("[할 일]", "").strip()
        items = get_active_tasks()
        target_items = [it for it in items if clean_keyword in it.get("title", "")]
        if not target_items:
            return False, f"'{clean_keyword}' 관련 미완료 할 일을 찾지 못했어."
        deleted_names = []
        for item in target_items:
            service.tasks().delete(tasklist="@default", task=item["id"]).execute()
            deleted_names.append(item["title"])
        return True, f"'{', '.join(deleted_names)}' 작업을 완료 처리하고 목록에서 지웠어!"
    except Exception as e:
        return False, f"작업 처리 오류: {e}"

def clean_expired_tasks(hours_limit=24):
    service = get_tasks_service()
    if not service:
        return 0
    cleaned_count = 0
    now = datetime.utcnow()
    try:
        items = get_active_tasks()
        for item in items:
            due_str = item.get("due")
            if due_str:
                due_dt = datetime.strptime(due_str.split(".")[0], "%Y-%m-%dT%H:%M:%SZ")
                if now - due_dt > timedelta(hours=hours_limit):
                    service.tasks().delete(tasklist="@default", task=item["id"]).execute()
                    cleaned_count += 1
        return cleaned_count
    except Exception:
        return 0

# --- [5] 구글 시트 메모 ---
def get_sheet_client():
    creds = get_gcp_credentials()
    if not creds:
        return None
    return gspread.authorize(creds)

def get_all_notes(limit=25):
    try:
        gc = get_sheet_client()
        if not gc:
            return []
        sh = gc.open(SPREADSHEET_NAME)
        records = sh.sheet1.get_all_records()
        if records:
            records.reverse()
            return records[:limit]
        return []
    except Exception:
        return []

def save_note(category, content):
    try:
        gc = get_sheet_client()
        if not gc:
            return False
        sh = gc.open(SPREADSHEET_NAME)
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        sh.sheet1.append_row([now_str, category, content])
        return True
    except Exception:
        return False

# --- [6] 카카오 내비 길찾기 ---
def get_coordinates(address_or_keyword):
    if not KAKAO_REST_API_KEY:
        return None, None
    headers = {"Authorization": f"KakaoAK {KAKAO_REST_API_KEY}"}
    url = "https://dapi.kakao.com/v2/local/search/keyword.json"
    try:
        res = requests.get(url, headers=headers, params={"query": address_or_keyword}, timeout=5)
        if res.status_code == 200:
            docs = res.json().get("documents", [])
            if docs:
                return float(docs[0]["x"]), float(docs[0]["y"])
    except Exception:
        pass
    return None, None

def calculate_travel_duration(start_place, end_place, travel_mode="car"):
    start_x, start_y = get_coordinates(start_place)
    end_x, end_y = get_coordinates(end_place)
    if not start_x or not end_x:
        return None
    if travel_mode == "car":
        url = "https://apis-navi.kakaomobility.com/v1/directions"
        headers = {
            "Authorization": f"KakaoAK {KAKAO_REST_API_KEY}",
            "Content-Type": "application/json"
        }
        params = {"origin": f"{start_x},{start_y}", "destination": f"{end_x},{end_y}", "priority": "RECOMMEND"}
        try:
            res = requests.get(url, headers=headers, params=params, timeout=5)
            if res.status_code == 200:
                routes = res.json().get("routes", [])
                if routes and "summary" in routes[0]:
                    return int(routes[0]["summary"]["duration"] / 60)
        except Exception:
            pass
        return 50
    else:
        car_mins = calculate_travel_duration(start_place, end_place, travel_mode="car")
        return int(car_mins * 1.3 + 15) if car_mins else 75

def get_departure_guidance(event_title, event_location, event_start_dt, default_start="안산"):
    title_lower = event_title.lower()
    loc_lower = event_location.lower()
    transit_keywords = ["연극", "뮤지컬", "관극", "대학로", "예술", "극장", "공연", "티켓"]
    drive_keywords = ["컨설팅", "강의", "출장", "연수", "자문", "출강", "워크숍", "교육청", "학교"]
    
    if any(k in title_lower or k in loc_lower for k in transit_keywords):
        mode = "transit"
        mode_text = "대중교통"
        buffer_mins = 15
    elif any(k in title_lower or k in loc_lower for k in drive_keywords):
        mode = "car"
        mode_text = "자차 운전"
        buffer_mins = 20
    else:
        mode = "car"
        mode_text = "이동"
        buffer_mins = 10

    duration = calculate_travel_duration(default_start, event_location, travel_mode=mode)
    if not duration:
        return f"📍 **[{event_title}]** 목적지: {event_location} (여유 있게 이동 권장)"

    total_need = duration + buffer_mins
    departure_time = event_start_dt - timedelta(minutes=total_need)
    return (
        f"🚗 **이동 안내 ({mode_text})**: '{event_title}'\n"
        f"- 목적지: {event_location}\n"
        f"- 이동 소요: 약 {duration}분 (여유 {buffer_mins}분 포함 총 {total_need}분 소요)\n"
        f"- **권장 출발 시각: {departure_time.strftime('%H시 %M분')}**"
    )
