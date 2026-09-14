import streamlit as st
import json
import io
import os
import base64
import sqlite3
import time
import requests
from datetime import datetime, timedelta
from google import genai
from google.genai import types
from google.oauth2 import service_account
from googleapiclient.discovery import build
from streamlit_mic_recorder import speech_to_text
from elevenlabs.client import ElevenLabs

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

# 2. API 키 및 서비스 설정
raw_keys = st.secrets.get("GEMINI_API_KEYS") or st.secrets.get("GEMINI_API_KEY", "")
api_keys = [k.strip() for k in raw_keys.split(",") if k.strip()]
calendar_id = st.secrets.get("CALENDAR_ID", "primary")
service_account_str = st.secrets.get("GCP_SERVICE_ACCOUNT_JSON")

# ElevenLabs & 알림 설정
eleven_api_key = st.secrets.get("ELEVENLABS_API_KEY", "")
eleven_voice_id = st.secrets.get("ELEVENLABS_VOICE_ID", "gDx7aX4UOQMthJevd64d")
ntfy_topic = st.secrets.get("NTFY_TOPIC", "")

if not api_keys or not service_account_str:
    st.error("API 키(GEMINI_API_KEYS) 또는 서비스 계정 설정을 확인해주세요.")
    st.stop()

service_account_info = json.loads(service_account_str)
creds = service_account.Credentials.from_service_account_info(
    service_account_info,
    scopes=["https://www.googleapis.com/auth/calendar"]
)
service = build("calendar", "v3", credentials=creds)

# 3. ElevenLabs 실시간 음성 생성 함수
def generate_elevenlabs_audio(text: str) -> bytes:
    if not eleven_api_key:
        return b""
    try:
        el_client = ElevenLabs(api_key=eleven_api_key)
        audio_generator = el_client.text_to_speech.convert(
            voice_id=eleven_voice_id,
            text=text,
            model_id="eleven_multilingual_v2",
            voice_settings={
                "stability": 0.5,
                "similarity_boost": 0.85,
                "style": 0.0,
                "use_speaker_boost": True
            }
        )
        audio_bytes = b"".join(audio_generator)
        return audio_bytes
    except Exception as e:
        st.error(f"음성 생성 실패: {str(e)}")
        return b""

# 4. 스마트폰 푸시 알림 전송 함수 (ntfy)
def send_push_notification(title: str, message: str):
    if not ntfy_topic:
        return
    try:
        requests.post(
            f"https://ntfy.sh/{ntfy_topic}",
            data=message.encode("utf-8"),
            headers={
                "Title": title.encode("utf-8").decode("latin-1"),
                "Priority": "high",
                "Tags": "robot,speaking_head"
            },
            timeout=5
        )
    except Exception:
        pass

# 5. 비서 도구 함수들
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

        return f"{desc}, 현재 기온 {temp}도(최저 {min_temp}도 / 최고 {max_temp}도), 강수확률 {pop}%"
    except Exception:
        return "날씨 정보 확인 불가"

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
            return "예정된 일정 없음"
        
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
            return "오늘 잡힌 일정 없음"
        
        res = []
        for e in events:
            start_raw = e['start'].get('dateTime', e['start'].get('date'))
            time_part = start_raw.split("T")[1][:5] if "T" in start_raw else "종일"
            res.append(f"{time_part} {e.get('summary')}")
        return ", ".join(res)
    except Exception:
        return "일정 확인 불가"

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
            return f"'{query_title}' 관련 일정을 찾지 못했어."
        
        target = events[0]
        service.events().delete(calendarId=calendar_id, eventId=target['id']).execute()
        return f"'{target.get('summary')}' 일정 캘린더에서 깔끔하게 삭제했어!"
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
        return f"보관 완료: [{category}] {content}"
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
            return "저장된 기록이 없어."
        
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
        return False, "보관함에 저장된 메모가 없어."
    
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
        return True, f"'{content}' 메모 보관함에서 지웠어!"
    
    conn.close()
    return False, "어떤 메모를 지워야 할지 못 찾겠어. 다시 말해줘!"

# 6. 대화 속 자동 기억 분석기 (대화 메모 고도화)
def auto_detect_and_remember(user_prompt: str):
    if len(user_prompt.strip()) < 5:
        return
    trigger_ignore = ["브리핑", "날씨", "몇 시", "삭제", "지워", "안녕"]
    if any(k in user_prompt for k in trigger_ignore):
        return

    classify_prompt = f"""
사용자의 말에서 기억해둘 만한 [할 일, 약속, 장보기, 창작 아이디어, 영감, 건강/기억할 일상]이 있는지 판단해줘.
사용자 발화: "{user_prompt}"

기억할 가치가 있다면 반드시 아래 형식의 JSON으로만 답해. 기억할 가치가 없다면 NONE 이라고만 답해.
{{"should_save": true, "category": "할일 또는 아이디어 또는 일상기록", "summary": "간결하게 정리된 핵심 내용"}}
"""
    try:
        active_key = api_keys[st.session_state.get("key_index", 0)]
        temp_client = genai.Client(api_key=active_key)
        res = temp_client.models.generate_content(
            model="gemini-3.6-flash",
            contents=classify_prompt
        )
        ans = res.text.strip()
        if "{" in ans and "should_save" in ans:
            clean_json = ans[ans.find("{"):ans.rfind("}")+1]
            data = json.loads(clean_json)
            if data.get("should_save"):
                save_archive_note(data.get("summary"), data.get("category", "일상기록"))
    except Exception:
        pass

custom_tools = [add_calendar_event, get_calendar_events, delete_calendar_event, save_archive_note, search_archive_notes]

# 7. Gemini 로테이션
if "key_index" not in st.session_state:
    st.session_state.key_index = 0

def generate_with_key_rotation(contents, system_prompt, use_tools=True, enable_search=False):
    total = len(api_keys)
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
            return response.text if response.text else "처리를 완료했어."
        except Exception as ex:
            if "429" in str(ex) or "RESOURCE_EXHAUSTED" in str(ex):
                continue
            return f"오류 발생: {str(ex)}"

    return "API 사용량이 일시적으로 찼어. 잠시만 이따가 다시 불러줘!"

# 8. 초고속 데일리 브리핑 (맥락 기억 + 푸시 발송)
def create_daily_briefing() -> str:
    weather_info = get_current_weather()
    today_events = get_today_calendar_events_str()
    
    conn = sqlite3.connect("assistant_archive.db")
    c = conn.cursor()
    c.execute("SELECT category, content FROM archives ORDER BY id DESC LIMIT 5")
    recent_memories = [f"[{r[0]}] {r[1]}" for r in c.fetchall()]
    conn.close()
    recent_mem_str = ", ".join(recent_memories) if recent_memories else "남은 주요 할 일 없음"
    
    now_dt = datetime.now()
    weekdays = ["월", "화", "수", "목", "금", "토", "일"]
    date_header = f"{now_dt.month}월 {now_dt.day}일 {weekdays[now_dt.weekday()]}요일"

    briefing_prompt = f"""
너는 가장 친한 친구이자 든든한 전담 비서 '태민'이야.
아래 정보를 보고 [친근하고 다정한 반말]로 딱 3~4문장 이내로 핵심만 요약 브리핑해줘.
특수문자나 마크다운 기호 없이 자연스럽게 이어지는 대화체여야 해.

- 오늘: {date_header}
- 날씨: {weather_info}
- 오늘 캘린더 일정: {today_events}
- 최근 메모/할 일/단상: {recent_mem_str}

[필수 구성: 딱 3~4문장]
1. 다정한 아침 인사와 오늘 날씨/옷차림 팁
2. 오늘 잡힌 주요 일정과 최근 남겨둔 생각/할 일 짧게 짚어주기
3. 아침 식사 후 약 챙겨 먹고 저녁 약도 잊지 말라는 건강 당부와 활기찬 응원
"""
    system_prompt = "너는 친근하고 따뜻한 비서 태민이야. 편안한 반말로 군더더기 없이 짧고 다정하게 말해줘."
    briefing_text = generate_with_key_rotation(briefing_prompt, system_prompt, use_tools=False, enable_search=False)
    
    # 스마트폰 팝업 푸시 발송
    send_push_notification("☀️ 태민이의 오늘 아침 브리핑", briefing_text)
    
    return briefing_text

# 9. 사이드바 설정 (음성 안내, 푸시 테스트, 아카이브)
with st.sidebar:
    st.header("🎙️ 비서 목소리")
    st.success("✨ 맞춤 복제 보이스(태민) 연결됨")

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

# 10. 모바일 반응형 헤더
def get_image_base64(path):
    if os.path.exists(path):
        with open(path, "rb") as f:
            return base64.b64encode(f.read()).decode()
    return ""

img_base64 = get_image_base64("profile.jpg")
if not img_base64:
    img_base64 = get_image_base64("profile.png")

if img_base64:
    header_html = f"""
    <div style="display: flex; align-items: center; gap: 12px; margin-bottom: 24px;">
        <img src="data:image/jpeg;base64,{img_base64}" 
             style="width: 44px; height: 44px; border-radius: 50%; object-fit: cover; flex-shrink: 0; box-shadow: 0 2px 6px rgba(0,0,0,0.15);" />
        <span style="font-size: 1.6rem; font-weight: 700; white-space: nowrap; letter-spacing: -0.5px;">2int의 AI 비서 태민</span>
    </div>
    """
else:
    header_html = """
    <div style="display: flex; align-items: center; gap: 10px; margin-bottom: 24px;">
        <span style="font-size: 2rem;">🤖</span>
        <span style="font-size: 1.6rem; font-weight: 700; white-space: nowrap; letter-spacing: -0.5px;">2int의 AI 비서 태민</span>
    </div>
    """

st.markdown(header_html, unsafe_allow_html=True)

if "messages" not in st.session_state:
    st.session_state.messages = []
if "processed_voice_history" not in st.session_state:
    st.session_state.processed_voice_history = set()

# 상단 빠른 브리핑 버튼
col_b1, col_b2 = st.columns([2, 5])
trigger_briefing = False
with col_b1:
    if st.button("☀️ 오늘의 데일리 브리핑 듣기", use_container_width=True):
        trigger_briefing = True

# 대화 내용 출력
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.write(msg["content"])
        if "image" in msg and msg["image"]:
            st.image(msg["image"], width=260)
        if "audio" in msg and msg["audio"]:
            st.audio(msg["audio"], format="audio/mp3")

st.write("---")

# 📷 카메라 / 사진 업로드
with st.expander("📷 카메라로 사진 찍기 또는 이미지 업로드", expanded=False):
    tab_cam, tab_file = st.tabs(["📸 스마트폰 즉석 촬영", "🖼️ 갤러리 사진 선택"])
    with tab_cam:
        camera_img = st.camera_input("냉장고, 영수증, 서류, 약 봉투 등을 찍어봐")
    with tab_file:
        file_img = st.file_uploader("사진 파일 선택", type=["jpg", "jpeg", "png"])

active_image = camera_img if camera_img else file_img

# 음성 및 텍스트 입력창
col1, col2 = st.columns([1, 4])
with col1:
    voice_input = speech_to_text(language="ko", start_prompt="🎤 말하기", stop_prompt="⏹️ 녹음 완료", key="mic_btn")

text_input = st.chat_input("일정, 질문, 냉장고 추천 등 무엇이든 편하게 말해줘...")

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
    current_user_prompt = "이 사진 보고 어떤 게 있는지, 식재료라면 가볍게 해먹을 수 있는 요리 추천해줘!"

# 11. 요청 처리 및 ElevenLabs 음성 출력
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

    is_briefing_cmd = any(k in current_user_prompt for k in ["브리핑", "오늘 요약", "아침 브리핑", "일정 브리핑"])
    is_delete_cmd = any(k in current_user_prompt for k in ["삭제", "지워", "취소"]) and any(k in current_user_prompt for k in ["메모", "할일", "보관"])

    # 백그라운드 대화 메모 자동 추출 동작
    if not is_briefing_cmd and not is_delete_cmd:
        auto_detect_and_remember(current_user_prompt)

    with st.chat_message("assistant"):
        with st.spinner("태민이가 목소리로 준비하고 있어..."):
            if is_briefing_cmd:
                reply_text = create_daily_briefing()
            elif is_delete_cmd:
                _, reply_text = direct_delete_memo(current_user_prompt)
            else:
                now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                system_prompt = (
                    f"너의 이름은 '태민'이야. 가장 친한 친구이자 든든한 개인 전담 AI 비서야. "
                    f"존댓말 쓰지 말고, 편안하고 다정한 친구 같은 반말로 자연스럽게 답해줘. "
                    f"음성으로 들을 때 편하도록 특수문자나 마크다운 기호는 쓰지 말고 짧고 간결하게 말해줘. "
                    f"현재 시간은 {now_str} (한국 표준시)야. "
                    f"- 일정 등록/조회/삭제: 구글 캘린더 도구 사용 "
                    f"- 메모/할 일 저장 및 조회: archive 도구 사용 "
                    f"- 최신 뉴스, 실시간 검색, 외부 정보: 구글 검색 도구 활용 "
                    f"- 사진이 주어지면: 식재료 분석 및 가벼운 메뉴 추천, 문서 핵심 요약 등을 세심하게 분석"
                )

                if img_bytes:
                    mime_type = "image/png" if getattr(active_image, "type", "") == "image/png" else "image/jpeg"
                    contents_payload = [
                        types.Part.from_bytes(data=img_bytes, mime_type=mime_type),
                        current_user_prompt
                    ]
                    reply_text = generate_with_key_rotation(contents_payload, system_prompt, use_tools=False, enable_search=True)
                else:
                    reply_text = generate_with_key_rotation(current_user_prompt, system_prompt, use_tools=True, enable_search=True)

            st.write(reply_text)

            # ElevenLabs 복제 보이스 재생
            audio_bytes = generate_elevenlabs_audio(reply_text)
            if audio_bytes:
                st.audio(audio_bytes, format="audio/mp3", autoplay=True)
                st.session_state.messages.append({"role": "assistant", "content": reply_text, "audio": audio_bytes})
            else:
                st.session_state.messages.append({"role": "assistant", "content": reply_text})
