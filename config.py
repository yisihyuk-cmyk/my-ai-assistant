import json
import streamlit as st
from google.oauth2 import service_account

# 1. API 키 및 기본 설정
raw_keys = st.secrets.get("GEMINI_API_KEYS") or st.secrets.get("GEMINI_API_KEY", "")
API_KEYS = [k.strip() for k in raw_keys.split(",") if k.strip()]

CALENDAR_ID = st.secrets.get("CALENDAR_ID", "primary")
SPREADSHEET_ID = st.secrets.get("SPREADSHEET_ID", "")
SERVICE_ACCOUNT_STR = st.secrets.get("GCP_SERVICE_ACCOUNT_JSON")

ELEVEN_API_KEY = st.secrets.get("ELEVENLABS_API_KEY", "")
ELEVEN_VOICE_ID = st.secrets.get("ELEVENLABS_VOICE_ID", "gDx7aX4UOQMthJevd64d")
NTFY_TOPIC = st.secrets.get("NTFY_TOPIC", "")

GMAIL_USER = st.secrets.get("GMAIL_USER", "")
GMAIL_PASSWORD = st.secrets.get("GMAIL_APP_PASSWORD", "")

# 2. GCP 인증 (캘린더 + 구글 시트 공용 스코프)
SCOPES = [
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]

if not API_KEYS or not SERVICE_ACCOUNT_STR:
    st.error("API 키 또는 GCP_SERVICE_ACCOUNT_JSON 설정을 확인해주세요.")
    st.stop()

service_account_info = json.loads(SERVICE_ACCOUNT_STR)
CREDS = service_account.Credentials.from_service_account_info(
    service_account_info,
    scopes=SCOPES
)