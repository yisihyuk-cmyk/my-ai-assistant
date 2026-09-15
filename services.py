import os
import requests
from datetime import datetime, timedelta
import streamlit as st
import gspread
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

# --- [1] 키 및 환경 설정 로드 ---
def get_secret(key, default=""):
    if hasattr(st, "secrets") and key in st.secrets:
        return st.secrets[key]
    return os.getenv(key, default)

KAKAO_REST_API_KEY = get_secret("KAKAO_REST_API_KEY")
SPREADSHEET_NAME = get_secret("SPREADSHEET_NAME", "태민이_아카이브")

# --- [2] 구글 인증 클라이언트 생성 ---
def get_gcp_credentials():
    scopes = [
        "https://www.googleapis.com/auth/calendar",
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]
    if hasattr(st, "secrets") and "gcp_service_account" in st.secrets:
        creds_dict = dict(st.secrets["gcp_service_account"])
        return Credentials.from_service_account_info(creds_dict, scopes=scopes)
    elif os.path.exists("credentials.json"):
        return Credentials.from_service_account_file("credentials.json", scopes=scopes)
    return None

# --- [3] 구글 시트 메모 관련 함수 (누락 복구) ---
def get_sheet_client():
    creds = get_gcp_credentials()
    if not creds:
        return None
    return gspread.authorize(creds)

def get_all_notes(limit=25):
    """구글 시트에서 최신 메모 목록을 가져옵니다."""
    try:
        gc = get_sheet_client()
        if not gc:
            return []
        
        sh = gc.open(SPREADSHEET_NAME)
        worksheet = sh.sheet1
        records = worksheet.get_all_records()
        
        # 최신 순으로 정렬 후 limit 개수 반환
        if records:
            records.reverse()
            return records[:limit]
        return []
    except Exception as e:
        print(f"구글 시트 읽기 오류: {e}")
        return []

def save_note(category, content):
    """구글 시트에 새 메모/할 일/영감을 저장합니다."""
    try:
        gc = get_sheet_client()
        if not gc:
            return False
        
        sh = gc.open(SPREADSHEET_NAME)
        worksheet = sh.sheet1
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        worksheet.append_row([now_str, category, content])
        return True
    except Exception as e:
        print(f"구글 시트 저장 오류: {e}")
        return False

# --- [4] 구글 캘린더 서비스 관련 함수 ---
def get_calendar_service():
    creds = get_gcp_credentials()
    if not creds:
        return None
    return build("calendar", "v3", credentials=creds)

def fetch_today_events(target_date=None):
    """지정한 날짜의 캘린더 일정을 가져옵니다."""
    service = get_calendar_service()
    if not service:
        return []
        
    if target_date is None:
        target_date = datetime.now()
        
    start_of_day = datetime(target_date.year, target_date.month, target_date.day, 0, 0, 0).isoformat() + "Z"
    end_of_day = datetime(target_date.year, target_date.month, target_date.day, 23, 59, 59).isoformat() + "Z"
    
    try:
        events_result = service.events().list(
            calendarId="primary",
            timeMin=start_of_day,
            timeMax=end_of_day,
            singleEvents=True,
            orderBy="startTime"
        ).execute()
        return events_result.get("items", [])
    except Exception as e:
        print(f"Calendar API 오류: {e}")
        return []

# --- [5] 카카오 기반 길찾기 및 출발 시각 계산 모듈 ---
def get_coordinates(address_or_keyword):
    """지명 또는 주소를 위경도 좌표로 변환"""
    if not KAKAO_REST_API_KEY:
        return None, None
        
    headers = {"Authorization": f"KakaoAK {KAKAO_REST_API_KEY}"}
    url = "https://dapi.kakao.com/v2/local/search/keyword.json"
    params = {"query": address_or_keyword}
    
    try:
        res = requests.get(url, headers=headers, params=params, timeout=5)
        if res.status_code == 200:
            docs = res.json().get("documents", [])
            if docs:
                return float(docs[0]["x"]), float(docs[0]["y"])
    except Exception as e:
        print(f"좌표 검색 실패: {e}")
    return None, None

def calculate_travel_duration(start_place, end_place, travel_mode="car"):
    """자가용 또는 대중교통 이동 소요 시간(분) 산출"""
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
        params = {
            "origin": f"{start_x},{start_y}",
            "destination": f"{end_x},{end_y}",
            "priority": "RECOMMEND"
        }
        try:
            res = requests.get(url, headers=headers, params=params, timeout=5)
            if res.status_code == 200:
                routes = res.json().get("routes", [])
                if routes and "summary" in routes[0]:
                    duration_sec = routes[0]["summary"]["duration"]
                    return int(duration_sec / 60)
        except Exception as e:
            print(f"내비 경로 실패: {e}")
        return 50
    else:
        # 대중교통: 자차 경로 기반 가중치(환승 및 도보) 환산
        car_mins = calculate_travel_duration(start_place, end_place, travel_mode="car")
        if car_mins:
            return int(car_mins * 1.3 + 15)
        return 75

def get_departure_guidance(event_title, event_location, event_start_dt, default_start="안산"):
    """일정명과 장소를 판별하여 권장 출발 시각 문자열 반환"""
    title_lower = event_title.lower()
    loc_lower = event_location.lower()
    
    # 1) 관극/문화생활 패턴 -> 대중교통
    transit_keywords = ["연극", "뮤지컬", "관극", "대학로", "예술", "아트센터", "극장", "공연", "티켓"]
    # 2) 출장/컨설팅 패턴 -> 자차
    drive_keywords = ["컨설팅", "강의", "출장", "연수", "자문", "출강", "워크숍", "교육청", "학교"]
    
    if any(k in title_lower or k in loc_lower for k in transit_keywords):
        mode = "transit"
        mode_text = "대중교통"
        buffer_mins = 15  # 티켓 발권 및 대기 여유
    elif any(k in title_lower or k in loc_lower for k in drive_keywords):
        mode = "car"
        mode_text = "자차 운전"
        buffer_mins = 20  # 주차 및 세팅 여유
    else:
        mode = "car"
        mode_text = "이동"
        buffer_mins = 10

    duration = calculate_travel_duration(default_start, event_location, travel_mode=mode)
    if not duration:
        return f"📍 **[{event_title}]** 장소({event_location}) 경로를 특정하지 못했습니다. 여유 있게 출발을 권장합니다."

    total_need_mins = duration + buffer_mins
    departure_time = event_start_dt - timedelta(minutes=total_need_mins)
    
    return (
        f"🚗 **이동 안내 ({mode_text})**: '{event_title}'\n"
        f"- 목적지: {event_location}\n"
        f"- 이동 예상: 약 {duration}분 (여유 {buffer_mins}분 포함 총 {total_need_mins}분 소요)\n"
        f"- **권장 출발 시각: {departure_time.strftime('%H시 %M분')}**"
    )
