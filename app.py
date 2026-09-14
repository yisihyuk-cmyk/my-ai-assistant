import streamlit as st
import json
import io
import sqlite3
import time
import requests
import asyncio
import edge_tts
from datetime import datetime, timedelta
from google import genai
from google.genai import types
from google.oauth2 import service_account
from googleapiclient.discovery import build
from streamlit_mic_recorder import speech_to_text

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

# 2. 다중 API 키 및 구글 캘린더 인증 설정
raw_keys = st.secrets.get("GEMINI_API_KEYS") or st.secrets.get("GEMINI_API_KEY", "")
api_keys = [k.strip() for k in raw_keys.split(",") if k.strip()]
calendar_id = st.secrets.get("CALENDAR_ID", "primary")
service_account_str = st.secrets.get("GCP_SERVICE_ACCOUNT_JSON")

if not api_keys or not service_account_str:
    st.error("API 키(GEMINI_API_KEYS) 또는 서비스 계정 설정(Secrets)을 확인해주세요.")
    st.stop()

service_account_info = json.loads(service_account_str)
creds = service_account.Credentials.from_service_account_info(
    service_account_info,
    scopes=["https://www.googleapis.com/auth/calendar"]
)
service = build("calendar", "v3", credentials=creds)

# 3. 사이드바 설정 (목소리 선택 및 아카이브)
with st.sidebar:
    st.header("🎙️ 비서 목소리 설정")
    voice_map = {
        "인준 (차분한 남성 비서)": "ko-KR-InJoonNeural",
        "선희 (단정한 여성 아나운서)": "ko-KR-SunHiNeural",
        "현수 (다정하고 자연스러운 청년)": "ko-KR-HyunsuNeural",
        "봉진 (신뢰감 있는 중후한 남성)": "ko-KR-BongJinNeural",
        "지민 (밝고 친근한 여성)": "ko-KR-JiMinNeural",
        "서현 (부드럽고 편안한 여성)": "ko-KR-SeoHyeonNeural",
    }
    selected_voice_label = st.selectbox("원하는 목소리를 고르세요", list(voice_map.keys()), index=0)
    current_voice = voice_map[selected_voice_label]

    st.write("---")
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
                if st.button("🗑️ 즉시 삭제", key=f"sidebar_del_{note_id}"):
                    conn = sqlite3.connect("assistant_archive.db")
                    c = conn.cursor()
                    c.execute("DELETE FROM archives WHERE id = ?", (note_id,))
                    conn.commit()
                    conn.close()
                    st.toast("삭제되었습니다!")
    else:
        st.caption("저장된 메모나 아이디어가 없습니다.")

# 4. 비서 도구 및 브리핑 수집 함수들
def get_current_weather(lat: float = 37.3219, lon: float = 126.8309) -> str:
    try:
        url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&current_weather=true&daily=temperature_2m_max,temperature_2m_min,precipitation_probability_max&timezone=Asia%2FSeoul"
        res = requests.get(url, timeout=5).json()
        curr = res.get("current_weather", {})
        daily = res.get("daily", {})
        
        temp = curr.get("temperature", "-")
        max_temp = daily.get("temperature_2m_max", ["-"])[0]
        min_temp = daily.get("temperature_2m_min", ["-"])[0]
        pop = daily.get("precipitation_probability_max", [0])[0]
        
        w_code = curr.get("weathercode", 0)
        desc = "맑음"
        if w_code in [1, 2, 3]: desc = "구름 조금 또는 흐림"
        elif w_code in [45, 48]: desc = "안개"
        elif w_code in [51, 53, 55, 61, 63, 65, 80, 81, 82]: desc = "비"
        elif w_code in [71, 73, 75, 85, 86]: desc = "눈"

        return f"현재 날씨는 {desc}이며, 기온 {temp}도, 오늘 최저 {min_temp}도 / 최고 {max_temp}도, 강수 확률은 {pop}%입니다."
    except Exception:
        return "날씨 정보를 가져오지 못했습니다."

def add_calendar_event(summary: str, start_iso: str, end_iso: str, description: str = "") -> str:
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

def get_today_calendar_events_str() -> str:
    try:
        today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).isoformat() + 'Z'
        today_end = (datetime.now().replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)).isoformat() + 'Z'
        
        events_result = service.events().list(
            calendarId=calendar_id,
            timeMin=today_start,
            timeMax=today_end,
            singleEvents=True,
            orderBy='startTime'
        ).execute()
        events = events_result.get('items', [])
        if not events:
            return "오늘 예정된 캘린더 일정은 없습니다."
        
        res = []
        for e in events:
            start_raw = e['start'].get('dateTime', e['start'].get('date'))
            time_part = start_raw.split("T")[1][:5] if "T" in start_raw else "종일"
            res.append(f"- {time_part} : {e.get('summary')}")
        return "\n".join(res)
    except Exception:
        return "캘린더 일정을 확인하지 못했습니다."

def delete_calendar_event(query_title: str) -> str:
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
        return f"캘린더 일정 삭제 완료: '{target.get('summary')}' 일정을 삭제했습니다."
    except Exception as e:
        return f"일정 삭제 실패: {str(e)}"

def save_archive_note(content: str, category: str = "일반메모") -> str:
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

def direct_delete_memo(user_text: str):
    conn = sqlite3.connect("assistant_archive.db")
    c = conn.cursor()
    c.execute("SELECT id, content FROM archives ORDER BY id DESC")
    all_notes = c.fetchall()
    
    if not all_notes:
        conn.close()
        return False, "현재 보관함에 저장된 메모가 없습니다."
    
    stop_words = ["삭제", "지워", "취소", "해줘", "관련", "해서", "메모", "항목", "에서", "좀", "해", "등록", "알려줘"]
    words = [w.strip() for w in user_text.split() if len(w.strip()) > 1 and not any(sw in w for sw in stop_words)]
    
    matched_target = None
    for note_id, content in all_notes:
        if any(word in content for word in words):
            matched_target = (note_id, content)
            break
        if any(part in user_text for part in content.split() if len(part) > 1):
            matched_target = (note_id, content)
            break

    if not matched_target and len(all_notes) == 1:
        matched_target = all_notes[0]

    if matched_target:
        note_id, content = matched_target
        c.execute("DELETE FROM archives WHERE id = ?", (note_id,))
        conn.commit()
        conn.close()
        return True, f"'{content}' 메모를 보관함에서 삭제했습니다."
    
    conn.close()
    return False, "삭제할 해당하는 메모를 찾지 못했습니다."

# 비서 커스텀 도구 목록 (캘린더 + 아카이브)
custom_tools = [add_calendar_event, get_calendar_events, delete_calendar_event, save_archive_note, search_archive_notes]

# 5. Microsoft Edge-TTS 음성 변환 함수
async def generate_edge_tts_audio(text: str, voice: str) -> bytes:
    communicate = edge_tts.Communicate(text, voice)
    audio_data = b""
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            audio_data += chunk["data"]
    return audio_data

# 6. Gemini 다중 키 로테이션 실행기 (텍스트 + 멀티모달 이미지 + 검색 지원)
if "key_index" not in st.session_state:
    st.session_state.key_index = 0

def generate_with_key_rotation(contents, system_prompt, use_tools=True, enable_search=False):
    total = len(api_keys)
    last_error = ""

    for _ in range(total):
        active_key = api_keys[st.session_state.key_index]
        st.session_state.key_index = (st.session_state.key_index + 1) % total

        try:
            temp_client = genai.Client(api_key=active_key)
            tools_payload = []
            if use_tools:
                tools_payload.extend(custom_tools)
            if enable_search:
                tools_payload.append({"google_search": {}})

            cfg = types.GenerateContentConfig(
                tools=tools_payload if tools_payload else None,
                system_instruction=system_prompt,
                temperature=0.3
            )
            response = temp_client.models.generate_content(
                model="gemini-3.6-flash",
                contents=contents,
                config=cfg
            )
            return response.text if response.text else "처리를 완료했습니다."
        except Exception as ex:
            err_msg = str(ex)
            last_error = err_msg
            if "429" in err_msg or "RESOURCE_EXHAUSTED" in err_msg:
                continue
            else:
                return f"오류가 발생했습니다: {err_msg}"

    return "등록된 모든 API 키의 요청 한도가 일시 초과되었습니다. 잠시 후 다시 시도해 주세요."

# 7. 데일리 브리핑
def create_daily_briefing() -> str:
    weather_info = get_current_weather()
    today_events = get_today_calendar_events_str()
    
    conn = sqlite3.connect("assistant_archive.db")
    c = conn.cursor()
    c.execute("SELECT content FROM archives WHERE category LIKE '%할일%' OR category LIKE '%할 일%' ORDER BY id DESC LIMIT 5")
    todos = [r[0] for r in c.fetchall()]
    conn.close()
    todo_str = "\n".join([f"- {t}" for t in todos]) if todos else "등록된 주요 할 일이 없습니다."
    
    now_dt = datetime.now()
    weekdays = ["월", "화", "수", "목", "금", "토", "일"]
    date_header = f"{now_dt.year}년 {now_dt.month}월 {now_dt.day}일 {weekdays[now_dt.weekday()]}요일"

    briefing_prompt = f"""
다음 정보들을 바탕으로 개인 전담 비서 '태민'이로서 사용자에게 들려줄 아침 데일리 브리핑 대본을 작성해줘.
음성으로 들었을 때 편안하고 활기차며, 특수문자나 마크다운 기호 없이 자연스러운 존댓말 대화체여야 해.

[기본 정보]
- 오늘 날짜: {date_header}
- 오늘 날씨: {weather_info}
- 오늘의 구글 캘린더 일정:
{today_events}
- 보관된 할 일:
{todo_str}
- 일일 건강 루틴:
아침 식후 약 및 저녁 식후 약 복용 챙기기

[작성 가이드]
1. 따뜻한 아침 인사와 날짜 소개
2. 오늘 날씨 안내 (기온 및 옷차림/우산 조언)
3. 캘린더 일정 및 할 일 요약
4. [건강 루틴 챙김]: 아침 식사 후 잊지 말고 아침 약 꼭 챙겨 드시고, 저녁 약 복용도 잊지 마시라는 다정하고 세심한 조언 포함
5. 기분 좋은 하루를 응원하는 마무리 인사
"""
    system_prompt = "너는 친절하고 똑똑한 전담 비서 '태민'이야. 듣기 편안한 라디오 아침 방송처럼 다정하게 말해줘."
    return generate_with_key_rotation(briefing_prompt, system_prompt, use_tools=False, enable_search=False)

# 8. 메인 UI 구성
st.title("🤖 2int의 AI 비서 태민")

if "messages" not in st.session_state:
    st.session_state.messages = []
if "processed_voice_history" not in st.session_state:
    st.session_state.processed_voice_history = set()

# 상단 브리핑 버튼
col_b1, col_b2 = st.columns([2, 5])
trigger_briefing = False
with col_b1:
    if st.button("☀️ 오늘의 데일리 브리핑 듣기", use_container_width=True):
        trigger_briefing = True

# 대화 히스토리 출력
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.write(msg["content"])
        if "image" in msg and msg["image"]:
            st.image(msg["image"], width=260)
        if "audio" in msg and msg["audio"]:
            st.audio(msg["audio"], format="audio/mp3")

st.write("---")

# 📸 멀티모달 카메라/사진 입력 (접이식 UI로 깔끔하게 배치)
with st.expander("📷 카메라로 사진 찍기 또는 이미지 업로드", expanded=False):
    tab_cam, tab_file = st.tabs(["📸 스마트폰 즉석 촬영", "🖼️ 갤러리 사진 선택"])
    with tab_cam:
        camera_img = st.camera_input("카메라로 식재료, 약 봉투, 서류 등을 찍어보세요")
    with tab_file:
        file_img = st.file_uploader("사진 파일 선택", type=["jpg", "jpeg", "png"])

active_image = camera_img if camera_img else file_img

# 음성 및 텍스트 입력창
col1, col2 = st.columns([1, 4])
with col1:
    voice_input = speech_to_text(language="ko", start_prompt="🎤 말하기", stop_prompt="⏹️ 녹음 완료", key="mic_btn")

text_input = st.chat_input("일정, 질문, 냉장고 추천 등 무엇이든 말씀해주세요...")

current_user_prompt = None
if trigger_briefing:
    current_user_prompt = "오늘 데일리 브리핑 시작해줘"
elif voice_input:
    if voice_input not in st.session_state.processed_voice_history:
        st.session_state.processed_voice_history.add(voice_input)
        current_user_prompt = voice_input
elif text_input:
    current_user_prompt = text_input
elif active_image and not st.session_state.get("image_processed", False):
    # 사진만 올리고 말을 안 했을 때 기본 질문 부여
    current_user_prompt = "이 사진을 보고 무엇이 있는지, 식재료라면 추천 메뉴나 활용법을 친절하게 알려줘."

# 9. 요청 처리 및 응답
if current_user_prompt:
    user_msg_entry = {"role": "user", "content": current_user_prompt}
    img_bytes = None
    if active_image:
        img_bytes = active_image.getvalue()
        user_msg_entry["image"] = img_bytes
        st.session_state.image_processed = True
    else:
        st.session_state.image_processed = False

    st.session_state.messages.append(user_msg_entry)
    with st.chat_message("user"):
        st.write(current_user_prompt)
        if img_bytes:
            st.image(img_bytes, width=260)

    # 1) 브리핑 여부
    is_briefing_cmd = any(k in current_user_prompt for k in ["브리핑", "오늘 요약", "아침 브리핑", "일정 브리핑"])
    # 2) 로컬 직접 메모 삭제 여부
    is_delete_cmd = any(k in current_user_prompt for k in ["삭제", "지워", "취소"]) and any(k in current_user_prompt for k in ["메모", "할일", "보관"])

    with st.chat_message("assistant"):
        with st.spinner("태민이가 확인하고 있습니다..."):
            if is_briefing_cmd:
                reply_text = create_daily_briefing()
            elif is_delete_cmd:
                _, reply_text = direct_delete_memo(current_user_prompt)
            else:
                now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                system_prompt = (
                    f"너의 이름은 '태민'이야. 든든하고 똑똑한 개인 전담 AI 비서야. "
                    f"사용자가 '태민아'라고 부르면 비서답게 친절하고 자연스럽게 화답해줘. "
                    f"음성으로 들을 때 편하도록 특수문자나 마크다운 기호를 최소화하고 정중하고 다정한 대화체로 답해줘. "
                    f"현재 시간은 {now_str} (한국 표준시)야. "
                    f"- 특정 약속/일정 등록 및 조회, 취소/삭제: 구글 캘린더 도구 사용 "
                    f"- 아이디어/메모/할 일 저장: save_archive_note 사용 "
                    f"- 메모/할 일 조회: search_archive_notes 사용 "
                    f"- 최신 뉴스, 실시간 검색, 추천 맛집 등 외부 정보: 구글 검색 도구 활용 "
                    f"- 사진(이미지)이 주어지면: 식재료 식별 및 부담 없는 건강 레시피 제안, 유통기한/문서 핵심 요약 등을 세심하게 분석"
                )

                # 요청 컨텐츠 구성 (멀티모달 이미지 포함 여부)
                if img_bytes:
                    mime_type = "image/png" if getattr(active_image, "type", "") == "image/png" else "image/jpeg"
                    contents_payload = [
                        types.Part.from_bytes(data=img_bytes, mime_type=mime_type),
                        current_user_prompt
                    ]
                    # 이미지 분석 시에는 커스텀 툴 대신 시각 이해와 웹 검색에 집중
                    reply_text = generate_with_key_rotation(contents_payload, system_prompt, use_tools=False, enable_search=True)
                else:
                    # 일반 텍스트/음성 질문: 캘린더 도구 + 구글 실시간 검색 동시 활성화
                    reply_text = generate_with_key_rotation(current_user_prompt, system_prompt, use_tools=True, enable_search=True)

            st.write(reply_text)

            try:
                audio_bytes = asyncio.run(generate_edge_tts_audio(reply_text, voice=current_voice))
                st.audio(audio_bytes, format="audio/mp3", autoplay=True)
                st.session_state.messages.append({"role": "assistant", "content": reply_text, "audio": audio_bytes})
            except Exception:
                st.session_state.messages.append({"role": "assistant", "content": reply_text})
