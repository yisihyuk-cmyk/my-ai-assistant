import json
import os
import streamlit as st
from google.oauth2 import service_account

# 1. Gemini API 키 풀 로드
raw_keys = (
    st.secrets.get("GEMINI_API_KEYS")
    or st.secrets.get("GEMINI_API_KEY")
    or os.environ.get("GEMINI_API_KEY", "")
)
API_KEYS = [k.strip().strip("'").strip('"') for k in str(raw_keys).split(",") if k.strip()]

# 2. 구글 서비스 설정
CALENDAR_ID = st.secrets.get("CALENDAR_ID") or os.environ.get("CALENDAR_ID", "primary")
SPREADSHEET_NAME = st.secrets.get("SPREADSHEET_NAME", "태민이_아카이브")
SPREADSHEET_ID = st.secrets.get("SPREADSHEET_ID", "")
SERVICE_ACCOUNT_DATA = st.secrets.get("GCP_SERVICE_ACCOUNT_JSON") or os.environ.get("GCP_SERVICE_ACCOUNT_JSON")

# 3. 외부 API (음성, 카카오, 알림, 메일)
ELEVEN_API_KEY = st.secrets.get("ELEVENLABS_API_KEY", "")
ELEVEN_VOICE_ID = st.secrets.get("ELEVENLABS_VOICE_ID", "gDx7aX4UOQMthJevd64d")
KAKAO_REST_API_KEY = st.secrets.get("KAKAO_REST_API_KEY", "")
NTFY_TOPIC = st.secrets.get("NTFY_TOPIC", "")
GMAIL_USER = st.secrets.get("GMAIL_USER", "")
GMAIL_PASSWORD = st.secrets.get("GMAIL_APP_PASSWORD", "")

# 4. GCP 인증 (캘린더 + 시트 + 드라이브 통합 스코프)
SCOPES = [
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]

CREDS = None

if not API_KEYS or not SERVICE_ACCOUNT_DATA:
    st.error("API 키 또는 GCP_SERVICE_ACCOUNT_JSON 설정을 확인해주세요.")
    st.stop()

# 딕셔너리와 JSON 문자열 형태를 모두 안전하게 수용
try:
    if isinstance(SERVICE_ACCOUNT_DATA, dict):
        service_account_info = SERVICE_ACCOUNT_DATA
    else:
        service_account_info = json.loads(SERVICE_ACCOUNT_DATA)
        
    CREDS = service_account.Credentials.from_service_account_info(
        service_account_info,
        scopes=SCOPES
    )
except Exception as e:
    st.error(f"GCP 서비스 계정 인증 정보 파싱 오류: {e}")
    st.stop()
