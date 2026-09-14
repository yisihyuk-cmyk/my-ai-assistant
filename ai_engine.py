import json
import time
from datetime import datetime, timedelta
from google import genai
from google.genai import types
import streamlit as st
from config import API_KEYS
import services

custom_tools = [
    services.add_calendar_event,
    services.get_calendar_events,
    services.delete_calendar_event,
    services.save_archive_note
]

def generate_with_key_rotation(contents, system_prompt, use_tools=True):
    if "key_index" not in st.session_state:
        st.session_state.key_index = 0

    total = len(API_KEYS)
    last_err = ""
    for _ in range(total):
        k = API_KEYS[st.session_state.key_index]
        st.session_state.key_index = (st.session_state.key_index + 1) % total
        try:
            client = genai.Client(api_key=k)
            cfg = types.GenerateContentConfig(
                tools=custom_tools if use_tools else None,
                system_instruction=system_prompt,
                temperature=0.2
            )
            res = client.models.generate_content(
                model="gemini-3.6-flash",
                contents=contents,
                config=cfg
            )
            return res.text if res.text else "처리를 완료했어."
        except Exception as ex:
            last_err = str(ex)
            if "429" in last_err or "RESOURCE_EXHAUSTED" in last_err:
                time.sleep(0.5)
                continue
            return f"일시적 오류: {last_err}"
    return f"API 연결 지연: {last_err}"

def auto_detect_and_remember(user_prompt: str):
    if len(user_prompt.strip()) < 5:
        return
    if any(k in user_prompt for k in ["브리핑", "날씨", "몇 시", "삭제", "안녕", "확인해줘", "일정"]):
        return

    prompt = f"""사용자 발화에서 기억할 할일, 장보기, 창작 영감이 있으면 JSON으로 응답해.
없으면 NONE.
카테고리는 반드시 ["할일", "영감창작", "일상기록"] 중 하나로 지정해.
{{"should_save": true, "category": "할일 또는 영감창작 또는 일상기록", "summary": "내용"}}
발화: "{user_prompt}" """

    try:
        current_idx = st.session_state.get("key_index", 0)
        client = genai.Client(api_key=API_KEYS[current_idx])
        res = client.models.generate_content(model="gemini-3.6-flash", contents=prompt)
        ans = res.text.strip()
        if "{" in ans and "should_save" in ans:
            data = json.loads(ans[ans.find("{"):ans.rfind("}")+1])
            if data.get("should_save"):
                services.save_archive_note(data.get("summary"), data.get("category", "일상기록"))
    except Exception:
        pass

def get_briefing(is_morning: bool = True) -> str:
    if is_morning:
        services.cleanup_past_todo_events()
        weather = services.get_current_weather()
        events = services.get_day_events_str(datetime.now())
        prompt = f"정수에게 다정한 반말로 아침 브리핑 3~4문장 작성. 날씨: {weather}, 일정: {events}. 비/눈 시 운전주의, 약 복용 당부."
    else:
        tmrw = datetime.now() + timedelta(days=1)
        events = services.get_day_events_str(tmrw)
        prompt = f"정수에게 하루 위로와 함께 내일 일정({events}) 미리보기 3~4문장 브리핑. 저녁 약 복용 당부."

    text = generate_with_key_rotation(prompt, "너는 다정한 비서 태민이야. 반말로 자연스럽게 답해줘.", use_tools=False)
    title = "☀️ 오늘 아침 브리핑" if is_morning else "🌙 오늘 하루 마무리"
    services.send_push_notification(title, text)
    return text

def develop_creative_idea(source_text: str) -> str:
    prompt = f"다음 단상/메모를 발전시켜 감각적인 시적 변주나 소설 대사 씬을 스케치해줘:\n\"{source_text}\""
    return generate_with_key_rotation(prompt, "너는 문학적 창작 파트너야. 품격 있는 문장으로 제안해줘.", use_tools=False)
