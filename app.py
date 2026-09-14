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

# 3. ElevenLabs 실시간 음성 생성 함수 (발음 교정 포함)
def fix_pronunciation(text: str) -> str:
    misheard_names = ["정숙", "영수", "진수", "정서", "점수", "정선"]
    for wrong in misheard_names:
        text = text.replace(wrong, "정수")
    return text

def generate_elevenlabs_audio(text: str) -> bytes:
    if not eleven_api_key:
        return b""
    try:
        clean_text = fix_pronunciation(text)
        el_client = ElevenLabs(api_key=eleven_api_key)
        audio_generator = el_client.text_to_speech.convert(
            voice_id=eleven_voice_id,
            text=clean_text,
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
    except Exception:
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
        now = (datetime.now() - timedelta(days=1)).isoformat() + 'Z'
        events_result = service.events().list(
            calendarId=calendar_id,
            timeMin=now,
            maxResults=30,
            singleEvents=True,
            orderBy='startTime'
        ).execute()
        events = events_result.get('items', [])
        if not events:
            return "예정된 일정이 없습니다."
        
        res = []
        for e in events:
            start_val = e['start'].get('dateTime', e['start'].get('date', ''))
            end_val = e['end'].get('dateTime', e['end'].get('date', ''))
            res.append(f"- 제목: {e.get('summary', '제목 없음')} | 시작: {start_val} | 종료: {end_val}")
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
        now = (datetime.now() - timedelta(days=1)).isoformat() + 'Z'
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

# 6. 백그라운드 자동 메모 감지 (영감창작 분리 강화)
def auto_detect_and_remember(user_prompt: str):
    if len(user_prompt.strip()) < 5:
        return
    trigger_ignore = ["브리핑", "날씨", "몇 시", "삭제", "지워", "안녕", "확인해줘", "일정", "보조제", "약", "이름"]
    if any(k in user_prompt for k in trigger_ignore):
        return

    classify_prompt = f"""
사용자의 말에서 기억해둘 만한 [할 일, 장보기, 시상이나 대사 같은 창작 영감, 약속]이 있는지 분석해줘.
발화: "{user_prompt}"

기억할 가치가 있다면 반드시 아래 형식의 JSON으로만 답해. 없으면 NONE 이라고만 답해.
카테고리는 반드시 ["할일", "영감창작", "일상기록"] 중 하나로 지정해.
{{"should_save": true, "category": "할일 또는 영감창작 또는 일상기록", "summary": "정리된 핵심 내용"}}
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
                cat = data.get("category", "일상기록")
                if "영감" in cat or "창작" in cat:
                    cat = "영감창작"
                save_archive_note(data.get("summary"), cat)
    except Exception:
        pass

custom_tools = [add_calendar_event, get_calendar_events, delete_calendar_event, save_archive_note, search_archive_notes]

# 7. Gemini 로테이션 엔진
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
            elif enable_search:
                tools_payload.append({"google_search": {}})

            cfg = types.GenerateContentConfig(
                tools=tools_payload if tools_payload else None,
                system_instruction=system_prompt,
                temperature=0.2
            )
            response = temp_client.models.generate_content(
                model="gemini-3.6-flash",
                contents=contents,
                config=cfg
            )
            return response.text if response.text else "처리를 완료했어."
        except Exception as ex:
            last_error = str(ex)
            if "429" in last_error or "RESOURCE_EXHAUSTED" in last_error:
                time.sleep(0.5)
                continue
            return f"일시적인 오류가 발생했어: {last_error}"

    return f"API 연결이 원활하지 않아. (원인: {last_error if last_error else '할당량 초과'})"

# 8. 고도화된 데일리 브리핑 (이동/날씨 팁 + 주말 문화생활 리마인더)
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
    weekday_str = weekdays[now_dt.weekday()]
    date_header = f"{now_dt.month}월 {now_dt.day}일 {weekday_str}요일"

    is_near_weekend = weekday_str in ["목", "금", "토"]

    briefing_prompt = f"""
너는 가장 친한 친구이자 든든한 전담 비서 '태민'이야.
사용자의 이름은 '정수'야. 항상 다정하게 '정수야'라고 불러줘.
아래 정보를 보고 [친근하고 다정한 반말]로 딱 3~4문장 이내로 핵심만 요약 브리핑해줘.
특수문자나 마크다운 기호 없이 자연스럽게 이어지는 대화체여야 해.

- 오늘: {date_header}
- 날씨: {weather_info}
- 오늘 캘린더 일정: {today_events}
- 최근 메모/할 일/단상: {recent_mem_str}
- 주말 근접 여부: {is_near_weekend}

[필수 구성 가이드: 딱 3~4문장]
1. 정수에게 건네는 따뜻한 아침 인사와 날씨 안내 (비나 눈이 오면 안전운전/이동 주의 팁 포함)
2. 오늘의 일정과 남겨둔 할 일을 짧게 짚어주기
3. {"목/금/토요일이니 주말에 대학로나 문화생활 보면서 힐링할 계획 잊지 말라는 다정한 응원" if is_near_weekend else "아침 식사 후 약 챙겨 먹고 저녁 약도 잊지 말라는 건강 당부와 활기찬 응원"}
"""
    system_prompt = "너는 친근하고 따뜻한 비서 태민이야. 사용자는 정수야. 편안한 반말로 군더더기 없이 짧고 다정하게 말해줘."
    briefing_text = generate_with_key_rotation(briefing_prompt, system_prompt, use_tools=False, enable_search=False)
    
    send_push_notification("☀️ 태민이의 오늘 아침 브리핑", briefing_text)
    return briefing_text

# 9. 사이드바 설정 (음성 안내, 영감 메모 내보내기, 아카이브)
with st.sidebar:
    st.header("🎙️ 비서 목소리")
    st.success("✨ 맞춤 복제 보이스(태민) 연결됨")

    st.write("---")
    st.header("🗂️ 아카이브 보관함")
    
    conn = sqlite3.connect("assistant_archive.db")
    c = conn.cursor()
    c.execute("SELECT id, category, content, created_at FROM archives ORDER BY id DESC LIMIT 30")
    recent_notes = c.fetchall()
    
    # [영감/창작] 메모 모아 내려받기
    c.execute("SELECT created_at, content FROM archives WHERE category='영감창작' ORDER BY id ASC")
    creative_notes = c.fetchall()
    conn.close()

    if creative_notes:
        export_text = "\n".join([f"[{d}] {txt}" for d, txt in creative_notes])
        st.download_button(
            label="📝 영감·창작 노트 다운로드 (.txt)",
            data=export_text,
            file_name=f"creative_notes_{datetime.now().strftime('%m%d')}.txt",
            mime="text/plain",
            use_container_width=True
        )

    if recent_notes:
        for note_id, cat, content, date_str in recent_notes:
            tag_icon = "💡" if cat == "영감창작" else ("✅" if "할일" in cat else "📌")
            with st.expander(f"{tag_icon} [{cat}] {content[:10]}... ({date_str})"):
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
    <div style="display: flex; align-items: center; gap: 12px; margin-bottom: 20px;">
        <img src="data:image/jpeg;base64,{img_base64}" 
             style="width: 44px; height: 44px; border-radius: 50%; object-fit: cover; flex-shrink: 0; box-shadow: 0 2px 6px rgba(0,0,0,0.15);" />
        <span style="font-size: 1.6rem; font-weight: 700; white-space: nowrap; letter-spacing: -0.5px;">2int의 AI 비서 태민</span>
    </div>
    """
else:
    header_html = """
    <div style="display: flex; align-items: center; gap: 10px; margin-bottom: 20px;">
        <span style="font-size: 2rem;">🤖</span>
        <span style="font-size: 1.6rem; font-weight: 700; white-space: nowrap; letter-spacing: -0.5px;">2int의 AI 비서 태민</span>
    </div>
    """

st.markdown(header_html, unsafe_allow_html=True)

if "messages" not in st.session_state:
    st.session_state.messages = []
if "processed_voice_history" not in st.session_state:
    st.session_state.processed_voice_history = set()

# 상단 데일리 브리핑 버튼 & 음소거 토글
col_b1, col_b2 = st.columns([3, 2], vertical_alignment="center")
trigger_briefing = False
with col_b1:
    if st.button("☀️ 오늘의 데일리 브리핑", use_container_width=True):
        trigger_briefing = True
with col_b2:
    # 켜두면 어떤 상황에서도 음성을 생성하지 않음 (크레딧 100% 절약)
    mute_mode = st.toggle("🔇 텍스트만 (음성 끄기)", value=False)

# 대화 내용 출력
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.write(msg["content"])
        if "image" in msg and msg["image"]:
            st.image(msg["image"], width=260)
        if "audio" in msg and msg["audio"]:
            st.audio(msg["audio"], format="audio/mp3")

st.write("---")

# 📷 카메라 / 사진 업로드 (배터리 보호 토글 적용)
camera_img = None
file_img = None

with st.expander("📷 식재료, 사진 촬영 또는 업로드", expanded=False):
    tab_cam, tab_file = st.tabs(["📸 스마트폰 즉석 촬영", "🖼️ 갤러리 사진 선택"])
    with tab_cam:
        use_camera = st.checkbox("카메라 센서 켜기", key="camera_toggle")
        if use_camera:
            camera_img = st.camera_input("냉장고, 재료 등을 찍어봐")
    with tab_file:
        file_img = st.file_uploader("사진 파일 선택", type=["jpg", "jpeg", "png"])

active_image = camera_img if camera_img else file_img

# 음성 및 텍스트 입력창
col1, col2 = st.columns([1, 4])
with col1:
    voice_input = speech_to_text(language="ko", start_prompt="🎤 말하기", stop_prompt="⏹️ 녹음 완료", key="mic_btn")

text_input = st.chat_input("일정, 질문, 식재료 추천 등 무엇이든 편하게 말해줘...")

# 입력 방식 감지 플래그 (텍스트 타이핑 여부)
current_user_prompt = None
is_typing_input = False

if trigger_briefing:
    current_user_prompt = "오늘 데일리 브리핑 시작해줘"
elif text_input:
    current_user_prompt = text_input
    is_typing_input = True  # 타이핑으로 입력함 -> 기본적으로 음성 생성 건너뜀
elif voice_input:
    if voice_input not in st.session_state.processed_voice_history:
        st.session_state.processed_voice_history.add(voice_input)
        current_user_prompt = voice_input
elif active_image and not st.session_state.get("image_processed", False):
    current_user_prompt = "이 사진 보고 어떤 식재료가 있는지, 두부나 양배추처럼 담백하게 전자레인지나 밥솥으로 해먹을 수 있는 깔끔한 메뉴 추천해줘!"

# 11. 요청 처리 및 지능형 음성 출력
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

    if not is_briefing_cmd and not is_delete_cmd:
        auto_detect_and_remember(current_user_prompt)

    with st.chat_message("assistant"):
        with st.spinner("태민이가 확인하고 있어..."):
            if is_briefing_cmd:
                reply_text = create_daily_briefing()
            elif is_delete_cmd:
                _, reply_text = direct_delete_memo(current_user_prompt)
            else:
                now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                system_prompt = (
                    f"너의 이름은 '태민'이야. 가장 친하고 다정한 개인 전담 AI 비서야. "
                    f"사용자의 진짜 이름은 '이정수'이며, 호칭할 때는 항상 다정하게 '정수야' 또는 '정수'라고 불러줘. "
                    f"사용자가 음성 인식 오타로 이름이 이상하게 찍혀 들어오더라도 무시하고 상대방을 무조건 '정수'라고 불러. "
                    f"존댓말 쓰지 말고 편안하고 다정한 반말로 짧고 명확하게 대답해줘. "
                    f"음성으로 들을 때 편하도록 특수문자나 마크다운 기호는 쓰지 마. "
                    f"현재 시간은 {now_str} (한국 표준시)야. "
                    f"- 일정 등록/조회/삭제 요청이 오면 반드시 캘린더 도구를 사용해. "
                    f"- 메모/할 일 저장은 archive 도구를 사용해. "
                    f"- 식단이나 식재료 질문/사진 분석 시: 고기보다는 두부, 양배추, 가벼운 채소 중심의 담백하고 자극 없는 전자레인지/간편 조리법을 우선 제안해."
                )

                if img_bytes:
                    mime_type = "image/png" if getattr(active_image, "type", "") == "image/png" else "image/jpeg"
                    contents_payload = [
                        types.Part.from_bytes(data=img_bytes, mime_type=mime_type),
                        current_user_prompt
                    ]
                    reply_text = generate_with_key_rotation(contents_payload, system_prompt, use_tools=False, enable_search=False)
                else:
                    reply_text = generate_with_key_rotation(current_user_prompt, system_prompt, use_tools=True, enable_search=False)

            st.write(reply_text)

            # 음성 생성 조건 판단:
            # 1) '텍스트만(음소거)' 토글이 켜져 있으면 음성 미생성
            # 2) 키보드로 글을 타이핑해서 보낸 경우도 조용한 상황으로 간주하여 음성 미생성
            # 3) 마이크 음성 대화나 브리핑 요청일 때만 ElevenLabs 호출 (토큰 대폭 절약)
            should_speak = (not mute_mode) and (not is_typing_input or trigger_briefing)

            if should_speak:
                audio_bytes = generate_elevenlabs_audio(reply_text)
                if audio_bytes:
                    st.audio(audio_bytes, format="audio/mp3", autoplay=True)
                    st.session_state.messages.append({"role": "assistant", "content": reply_text, "audio": audio_bytes})
                else:
                    st.session_state.messages.append({"role": "assistant", "content": reply_text})
            else:
                # 텍스트만 기록하고 음성 API 토큰 0 소모
                st.session_state.messages.append({"role": "assistant", "content": reply_text})
