import os
import re
import requests
from datetime import datetime, timedelta
import streamlit as st
import services

CANDIDATE_MODELS = [
    "gemini-3.6-flash",
    "gemini-2.5-flash"
]

SYSTEM_PROMPT = """
너는 나의 가장 가깝고 다정한 단짝 친구이자 1인 전담 AI 비서 '태민이'야.
사용자의 이름은 '정수'이며, 언제나 다정하게 "정수야"라고 편하게 이름을 불러줘.
절대 존댓말을 쓰지 않고, 자연스럽고 포근한 친구 반말(~했어, ~할게, ~해, ~보내자 등)을 써.
말을 건넬 때 '1.', '2.', '3.' 같은 번호나 리스트 항목을 매기지 말고, 친구와 편하게 이야기하듯 매끄러운 줄글과 대화체로 전해줘.
"""

def get_api_keys_pool():
    raw_keys = ""
    if hasattr(st, "secrets"):
        if "GEMINI_API_KEY" in st.secrets:
            raw_keys = str(st.secrets["GEMINI_API_KEY"])
        elif "gemini" in st.secrets and "api_key" in st.secrets["gemini"]:
            raw_keys = str(st.secrets["gemini"]["api_key"])
        elif "GOOGLE_API_KEY" in st.secrets:
            raw_keys = str(st.secrets["GOOGLE_API_KEY"])
            
    if not raw_keys:
        raw_keys = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY") or ""

    keys = [k.strip().strip("'").strip('"') for k in raw_keys.split(",") if k.strip()]
    if not keys:
        raise ValueError("❌ 등록된 유효한 Gemini API Key가 없습니다.")
    return keys

def get_next_api_key():
    keys = get_api_keys_pool()
    if "gemini_rr_index" not in st.session_state:
        st.session_state["gemini_rr_index"] = 0
    current_idx = st.session_state["gemini_rr_index"] % len(keys)
    selected_key = keys[current_idx]
    st.session_state["gemini_rr_index"] = (current_idx + 1) % len(keys)
    return selected_key

def call_gemini_rest(prompt_text):
    keys = get_api_keys_pool()
    payload = {
        "systemInstruction": {"parts": [{"text": SYSTEM_PROMPT}]},
        "contents": [{"parts": [{"text": prompt_text}]}],
        "generationConfig": {"temperature": 0.7}
    }
    last_error = None
    for _ in range(len(keys)):
        api_key = get_next_api_key()
        headers = {"Content-Type": "application/json", "x-goog-api-key": api_key}
        for model in CANDIDATE_MODELS:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
            try:
                res = requests.post(url, headers=headers, json=payload, timeout=20)
                if res.status_code == 200:
                    data = res.json()
                    candidates = data.get("candidates", [])
                    if candidates:
                        parts = candidates[0].get("content", {}).get("parts", [])
                        if parts:
                            return parts[0].get("text", "")
                    return "정수야, 답변을 잘 받아오지 못했어."
                else:
                    err_msg = res.json().get("error", {}).get("message", res.text)
                    last_error = f"{res.status_code} ({model}) - {err_msg}"
                    if res.status_code != 404:
                        break
            except Exception as e:
                last_error = str(e)
                break
    raise Exception(f"호출 실패: {last_error}")

def generate_daily_briefing():
    """자연스러운 대화 흐름으로 날씨, 아침 약, 일정, 할 일을 전하는 아침 브리핑"""
    try:
        try:
            services.clean_expired_tasks(hours_limit=24)
        except Exception:
            pass
        
        weather_info = services.get_today_weather()
        events = services.fetch_today_events()
        active_tasks = services.get_active_tasks()
        
        events_summary = []
        travel_guidance_list = []
        
        for ev in events:
            summary = ev.get("summary", "제목 없음")
            # 종일 일정(date) 및 시간 지정 일정(dateTime) 처리
            start_raw = ev.get("start", {}).get("dateTime", ev.get("start", {}).get("date", ""))
            location = ev.get("location", "")
            
            # 읽기 쉬운 시간 표시
            if "T" in start_raw:
                time_part = start_raw.split("T")[1][:5]
                time_str = f"{time_part} 시작"
            else:
                time_str = "종일 일정"
                
            loc_str = f", 장소: {location}" if location else ""
            events_summary.append(f"- {summary} ({time_str}{loc_str})")
            
            if location and "T" in start_raw:
                try:
                    clean_time = start_raw.split("+")[0]
                    dt = datetime.fromisoformat(clean_time)
                    guidance = services.get_departure_guidance(summary, location, dt)
                    travel_guidance_list.append(guidance)
                except Exception:
                    pass

        schedule_text = "\n".join(events_summary) if events_summary else "오늘 등록된 주요 일정은 없어."
        travel_text = "\n\n".join(travel_guidance_list) if travel_guidance_list else ""
        
        tasks_summary = [f"- {t.get('title')}" for t in active_tasks if t.get('title')]
        tasks_text = "\n".join(tasks_summary) if tasks_summary else "현재 밀려 있는 할 일은 없어."

        user_content = f"""
친구 '정수'에게 아침에 다정하게 말을 건네듯 브리핑을 작성해줘.

[필수 규칙]
- 시작은 "정수야, 좋은 아침!"처럼 다정하게 이름을 부르며 시작할 것.
- **절대 1, 2, 3 같은 번호나 목록 번호를 붙이지 말 것.** 친구와 편안하게 수다 떨듯 문단으로 매끄럽게 이어줘.
- **날씨**: 안산 날씨를 친근하게 알려주며 옷차림 챙겨주기
  (날씨 정보: {weather_info})
- **건강**: "밥 든든하게 먹고 아침 약 꼭 챙겨 먹어!"라고 따뜻하게 당부하기
- **오늘 캘린더 일정 & 이동**: 
  {schedule_text}
  {travel_text}
- **할 일(Tasks)**: 
  {tasks_text}
- 마지막엔 기분 좋은 응원과 함께 오늘 하루도 신나게 보내자고 마무리해줘.
"""
        return call_gemini_rest(user_content)
    except Exception as e:
        return f"정수야, 좋은 아침! (브리핑 준비 중 잠깐 오류가 생겼어: {e})"

def generate_evening_briefing():
    """자연스러운 대화 흐름으로 저녁 약, 할 일, 휴식을 전하는 저녁 브리핑"""
    try:
        active_tasks = services.get_active_tasks()
        tasks_summary = [f"- {t.get('title')}" for t in active_tasks if t.get('title')]
        tasks_text = "\n".join(tasks_summary) if tasks_summary else "밀린 할 일 없이 다 잘 끝냈어!"

        user_content = f"""
친구 '정수'에게 하루를 토닥여주며 편안하게 건네는 저녁 브리핑을 작성해줘.

[필수 규칙]
- "정수야, 오늘 하루도 정말 고생 많았어!"처럼 다정하게 이름을 부르며 시작할 것.
- **절대 1, 2, 3 같은 번호나 순번을 매기지 말 것.**
- 수고한 정수를 포근하게 위로하고, "자기 전에 저녁 약 잊지 말고 꼭 챙겨 먹어!"라고 챙겨주기.
- 남은 할 일이 있다면 가볍게 언급해 주고, 없으면 마음 편히 쉬라고 하기:
  {tasks_text}
- 편안한 밤 보내라는 따뜻한 인사로 마무리할 것.
"""
        return call_gemini_rest(user_content)
    except Exception as e:
        return f"정수야, 오늘 하루도 정말 수고 많았어! 편안한 저녁 보내. (오류: {e})"

def chat_with_taemin(user_message, chat_history=None):
    msg_clean = user_message.strip()
    
    finish_keywords = ["끝냈어", "완료했어", "마무리했어", "다 했어", "삭제해줘", "지워줘", "끝남"]
    if any(k in msg_clean for k in finish_keywords):
        target_kw = msg_clean
        for k in finish_keywords:
            target_kw = target_kw.replace(k, "")
        target_kw = re.sub(r"[은는이가을를]", "", target_kw).strip()
        success, res_text = services.complete_or_delete_task(target_kw)
        return f"✅ **{res_text}**" if success else f"💬 {res_text}"

    task_keywords = ["해야 돼", "해야 해", "할 일 등록", "챙겨줘", "제출해야 돼", "작성해야 해", "입력해야 해", "업무 등록"]
    if any(k in msg_clean for k in task_keywords):
        due_time = datetime.utcnow() + timedelta(hours=12)
        success, task_id = services.add_work_task(title=msg_clean, due_datetime=due_time)
        if success:
            return (
                f"📌 **[할 일 등록 완료]**\n\n"
                f"- 등록 내용: {msg_clean}\n"
                f"- 정수야, 구글 Tasks에 잊지 않게 잘 적어뒀어.\n"
                f"- 다 끝나면 **'{msg_clean.split()[0]} 끝냈어'**라고 편하게 말해줘!"
            )

    context_addon = ""
    if any(k in msg_clean for k in ["출발", "몇 시에", "어떻게 가", "얼마나 걸려", "이동"]):
        try:
            events = services.fetch_today_events()
            travel_guidance_list = []
            for ev in events:
                summary = ev.get("summary", "")
                location = ev.get("location", "")
                start_raw = ev.get("start", {}).get("dateTime", "")
                if location and "T" in start_raw:
                    dt = datetime.fromisoformat(start_raw.split("+")[0])
                    travel_guidance_list.append(services.get_departure_guidance(summary, location, dt))
            if travel_guidance_list:
                context_addon = "\n\n[오늘 일정 경로 안내]\n" + "\n".join(travel_guidance_list)
        except Exception:
            pass

    try:
        prompt = f"정수의 질문: {msg_clean}{context_addon}\n정수에게 번호 매김 없이 다정하고 편안한 반말로 답변해줘."
        return call_gemini_rest(prompt)
    except Exception as e:
        return f"정수야, 내가 답변하려다 잠깐 오류가 생겼어: {e}"
