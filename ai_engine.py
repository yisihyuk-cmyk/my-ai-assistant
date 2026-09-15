import os
import re
import json
import requests
from datetime import datetime, timedelta
import streamlit as st
import services

MODEL_NAME = "gemini-1.5-flash"

SYSTEM_PROMPT = """
당신은 다정하고 꼼꼼한 1인 전담 AI 비서 '태민이'입니다.
사용자의 업무 마감 및 할 일(Task), 이동 일정, 장보기 및 일상 루틴을 똑똑하게 챙깁니다.
핵심 사항은 놓치지 않도록 직관적이고 깔끔하게 안내하며, 과도한 미사여구 없이 따뜻하고 신뢰감 있는 어투를 유지합니다.
"""

def get_api_key():
    """Secrets 또는 환경변수에서 순수 API Key 문자열만 추출"""
    api_key = None
    if hasattr(st, "secrets"):
        if "GEMINI_API_KEY" in st.secrets:
            api_key = st.secrets["GEMINI_API_KEY"]
        elif "gemini" in st.secrets and "api_key" in st.secrets["gemini"]:
            api_key = st.secrets["gemini"]["api_key"]
        elif "GOOGLE_API_KEY" in st.secrets:
            api_key = st.secrets["GOOGLE_API_KEY"]
            
    if not api_key:
        api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")

    if not api_key:
        raise ValueError("GEMINI_API_KEY를 찾을 수 없습니다.")

    return str(api_key).strip().strip("'").strip('"')

def call_gemini_rest(prompt_text):
    """GCP 서비스 계정 충돌을 완전히 우회하는 순수 REST API 호출"""
    api_key = get_api_key()
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL_NAME}:generateContent?key={api_key}"
    
    headers = {"Content-Type": "application/json"}
    payload = {
        "systemInstruction": {
            "parts": [{"text": SYSTEM_PROMPT}]
        },
        "contents": [
            {
                "parts": [{"text": prompt_text}]
            }
        ],
        "generationConfig": {
            "temperature": 0.7
        }
    }
    
    res = requests.post(url, headers=headers, json=payload, timeout=20)
    if res.status_code == 200:
        data = res.json()
        candidates = data.get("candidates", [])
        if candidates:
            parts = candidates[0].get("content", {}).get("parts", [])
            if parts:
                return parts[0].get("text", "")
        return "답변을 받아오지 못했습니다."
    else:
        err_msg = res.json().get("error", {}).get("message", res.text)
        raise Exception(f"{res.status_code} - {err_msg}")

def generate_daily_briefing():
    """오늘의 일정, 대기 중인 [할 일], 이동 권장 출발 시각을 종합한 아침 브리핑 생성"""
    try:
        try:
            services.clean_expired_tasks(hours_limit=24)
        except Exception:
            pass
        
        events = services.fetch_today_events()
        active_tasks = services.get_active_tasks()
        
        events_summary = []
        travel_guidance_list = []
        
        for ev in events:
            summary = ev.get("summary", "제목 없음")
            start_raw = ev.get("start", {}).get("dateTime", ev.get("start", {}).get("date", ""))
            location = ev.get("location", "")
            
            events_summary.append(f"- {summary} (시간: {start_raw}, 장소: {location if location else '미정'})")
            
            if location and "T" in start_raw:
                try:
                    clean_time = start_raw.split("+")[0]
                    dt = datetime.fromisoformat(clean_time)
                    guidance = services.get_departure_guidance(summary, location, dt)
                    travel_guidance_list.append(guidance)
                except Exception:
                    pass

        schedule_text = "\n".join(events_summary) if events_summary else "오늘 등록된 주요 일정이 없습니다."
        travel_text = "\n\n".join(travel_guidance_list) if travel_guidance_list else ""
        
        tasks_summary = [f"- {t.get('title')}" for t in active_tasks if t.get('title')]
        tasks_text = "\n".join(tasks_summary) if tasks_summary else "현재 밀려 있는 할 일이 없습니다."

        user_content = f"""
다음 정보를 바탕으로 오늘 아침 브리핑 메시지를 다정하게 작성해줘:

[오늘 캘린더 일정]
{schedule_text}

[이동 및 권장 출발 시각 안내]
{travel_text}

[처리 대기 중인 업무/할 일 목록]
{tasks_text}

출발 시각 안내와 중요 할 일이 있다면 글머리 기호로 알아보기 쉽게 강조해줘.
"""
        return call_gemini_rest(user_content)
    except Exception as e:
        return f"☀️ 좋은 아침이야! (브리핑 생성 중 오류가 발생했어: {e})"

def generate_evening_briefing():
    """하루를 마무리하며 남은 할 일과 내일 일정을 챙기는 저녁 브리핑"""
    try:
        active_tasks = services.get_active_tasks()
        
        tasks_summary = [f"- {t.get('title')}" for t in active_tasks if t.get('title')]
        tasks_text = "\n".join(tasks_summary) if tasks_summary else "밀린 할 일 없이 모두 완료했습니다!"

        user_content = f"""
오늘 저녁 마무리 브리핑을 작성해줘.
사용자가 오늘 하루도 고생 많았다고 따뜻하게 격려해주고,
아직 완료되지 않은 다음 [할 일]들을 점검해줘:
{tasks_text}
내일을 위해 편안한 쉼을 권하는 포근한 어투로 마무리해줘.
"""
        return call_gemini_rest(user_content)
    except Exception as e:
        return f"🌙 오늘 하루도 정말 수고 많았어! 편안한 저녁 시간 보내. (오류: {e})"

def chat_with_taemin(user_message, chat_history=None):
    """할 일 등록/완료 처리 및 일반 대화"""
    msg_clean = user_message.strip()
    
    # 1. 완료/삭제 의도 감지
    finish_keywords = ["끝냈어", "완료했어", "마무리했어", "다 했어", "삭제해줘", "지워줘", "끝남"]
    if any(k in msg_clean for k in finish_keywords):
        target_kw = msg_clean
        for k in finish_keywords:
            target_kw = target_kw.replace(k, "")
        target_kw = re.sub(r"[은는이가을를]", "", target_kw).strip()
        
        success, res_text = services.complete_or_delete_task(target_kw)
        if success:
            return f"✅ **{res_text}**"
        else:
            return f"💬 {res_text}"

    # 2. [할 일] 등록 의도 감지
    task_keywords = ["해야 돼", "해야 해", "할 일 등록", "챙겨줘", "제출해야 돼", "작성해야 해", "입력해야 해", "업무 등록"]
    if any(k in msg_clean for k in task_keywords):
        due_time = datetime.utcnow() + timedelta(hours=12)
        success, task_id = services.add_work_task(title=msg_clean, due_datetime=due_time)
        if success:
            return (
                f"📌 **[할 일 등록 완료]**\n\n"
                f"- 등록 내용: {msg_clean}\n"
                f"- 구글 Tasks에 잊지 않게 저장해 뒀어.\n"
                f"- 다 끝내면 **'{msg_clean.split()[0]} 끝냈어'**라고 편하게 말해줘!"
            )

    # 3. 경로/출발 관련 질문
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

    # 4. Gemini REST 호출
    try:
        prompt = f"{msg_clean}{context_addon}"
        return call_gemini_rest(prompt)
    except Exception as e:
        return f"태민이가 답변을 생성하는 중 오류가 발생했어: {e}"
