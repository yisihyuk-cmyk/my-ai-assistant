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
    try:
        try:
            services.clean_expired_tasks(hours_limit=24)
        except Exception:
            pass
        
        events = services.fetch_today_events()
        active_tasks = services.get_active_tasks()
        
        # 1. 구글 시트 최근 메모 5개 조회
        recent_notes = services.get_all_notes(limit=5)
        notes_lines = []
        if recent_notes:
            for n in recent_notes:
                cat = n.get("분류", n.get("카테고리", "메모"))
                cnt = n.get("내용", "")
                if cnt:
                    notes_lines.append(f"- [{cat}] {cnt}")
        notes_text = "\n".join(notes_lines) if notes_lines else "최근 따로 남겨둔 특별한 메모는 없어."
        
        # 첫 번째 일정 장소 기준 날씨, 없으면 안산
        target_location = "안산"
        for ev in events:
            loc = ev.get("location", "").strip()
            if loc:
                target_location = loc
                break
                
        weather_info = services.get_today_weather(target_location)
        
        events_summary = []
        travel_guidance_list = []
        
        for ev in events:
            summary = ev.get("summary", "제목 없음")
            start_raw = ev.get("start", {}).get("dateTime", ev.get("start", {}).get("date", ""))
            location = ev.get("location", "")
            
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

        # Gemini에게 실제로 전달되는 프롬프트에 메모(notes_text) 주입
        user_content = f"""
친구 '정수'에게 아침에 다정하게 말을 건네듯 브리핑을 작성해줘.

[분량 및 형식 엄수]
- **공백 포함 250~350자 이내로 콤팩트하게 작성할 것.**
- 시작은 "정수야, 좋은 아침!"처럼 다정하게 이름을 부르며 시작할 것.
- **절대 1, 2, 3 같은 번호나 목록 기호를 쓰지 말고 부드러운 대화체 문단으로 이어줘.**
- 일정이나 메모가 없을 때는 길게 나열하지 말고 자연스럽게 한 문장으로 넘길 것.

[필수 내용]
- 날씨: {weather_info} 바탕으로 체감 날씨와 옷차림/우산 위주로 간결히 전하기
- 건강: "밥 든든히 챙겨 먹고 아침 약 꼭 챙겨 먹어!"라고 따뜻하게 당부하기
- 일정 & 이동: {schedule_text} / {travel_text}
- 할 일: {tasks_text}
- 최근 중요 메모/생각: {notes_text} (정수가 최근 메모해 둔 내용이 있다면 잊지 않게 자연스럽게 한 번 언급해줘)
- 기분 좋은 한마디 응원으로 마무리하기
"""
        return call_gemini_rest(user_content)
    except Exception as e:
        return f"정수야, 좋은 아침! (브리핑 준비 중 잠깐 오류가 생겼어: {e})"


def generate_evening_briefing():
    try:
        active_tasks = services.get_active_tasks()
        tasks_summary = [f"- {t.get('title')}" for t in active_tasks if t.get('title')]
        tasks_text = "\n".join(tasks_summary) if tasks_summary else "밀린 할 일 없이 다 잘 끝냈어!"

        # 구글 시트 최근 메모 5개 조회
        recent_notes = services.get_all_notes(limit=5)
        notes_lines = []
        if recent_notes:
            for n in recent_notes:
                cat = n.get("분류", n.get("카테고리", "메모"))
                cnt = n.get("내용", "")
                if cnt:
                    notes_lines.append(f"- [{cat}] {cnt}")
        notes_text = "\n".join(notes_lines) if notes_lines else "오늘 특별히 남겨둔 메모는 없어."

        # Gemini에게 실제로 전달되는 프롬프트에 메모(notes_text) 주입
        user_content = f"""
친구 '정수'에게 하루를 토닥여주며 편안하게 건네는 저녁 브리핑을 작성해줘.

[분량 및 형식 엄수]
- **공백 포함 250~350자 내외로 작성할 것 (절대 400자를 넘기지 마).**
- "정수야, 오늘 하루도 정말 고생 많았어!"처럼 다정하게 이름을 부르며 시작할 것.
- **절대 1, 2, 3 같은 번호나 목록 기호를 쓰지 말고 포근한 대화체 문단으로 이어줘.**

[필수 내용]
- 고생한 정수를 따뜻하게 위로하기
- 건강: "자기 전에 저녁 약 잊지 말고 꼭 챙겨 먹어!"라고 당부하기
- 남은 할 일 & 메모 점검: 할 일({tasks_text})과 오늘/최근 메모({notes_text})를 가볍게 짚어주며 잘 챙겼는지 확인하기
- 편안한 밤 보내라는 따뜻한 인사로 마무리하기
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
