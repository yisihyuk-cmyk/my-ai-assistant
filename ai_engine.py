import os
from datetime import datetime
import streamlit as st
from google import genai
from services import fetch_today_events, get_departure_guidance

def get_gemini_client():
    api_key = None
    if hasattr(st, "secrets") and "GEMINI_API_KEY" in st.secrets:
        api_key = st.secrets["GEMINI_API_KEY"]
    else:
        api_key = os.getenv("GEMINI_API_KEY")
    return genai.Client(api_key=api_key)

SYSTEM_PROMPT = """
당신은 다정하고 명쾌한 1인 전담 AI 비서 '태민이'입니다.
사용자의 하루 일정, 이동 경로, 장보기 및 업무 체크를 돕습니다.
답변은 실용적이고 간결하게 핵심 위주로 안내하며, 과도한 미사여구 없이 따뜻한 어투를 유지합니다.
"""

def generate_daily_briefing():
    """오늘의 일정과 위치 기반 이동 권장 출발 시각을 종합한 아침/데일리 브리핑 생성"""
    client = get_gemini_client()
    events = fetch_today_events()
    
    events_summary = []
    travel_guidance_list = []
    
    for ev in events:
        summary = ev.get("summary", "제목 없음")
        start_raw = ev.get("start", {}).get("dateTime", ev.get("start", {}).get("date", ""))
        location = ev.get("location", "")
        
        events_summary.append(f"- {summary} (시작: {start_raw}, 장소: {location if location else '미정'})")
        
        # 장소 정보가 있고 시작 시간이 분 단위까지 있는 경우 출발 시간 역산
        if location and "T" in start_raw:
            try:
                # ISO 포맷 파싱 (타임존 제거 단순화)
                clean_time = start_raw.split("+")[0]
                dt = datetime.fromisoformat(clean_time)
                guidance = get_departure_guidance(summary, location, dt)
                travel_guidance_list.append(guidance)
            except Exception as e:
                print(f"시간 파싱 실패: {e}")

    schedule_text = "\n".join(events_summary) if events_summary else "오늘 등록된 주요 일정이 없습니다."
    travel_text = "\n\n".join(travel_guidance_list) if travel_guidance_list else ""

    user_content = f"""
다음은 오늘 사용자의 캘린더 일정입니다:
{schedule_text}

아래는 카카오 경로 기반으로 계산된 이동 및 권장 출발 시간 안내입니다:
{travel_text}

위 데이터를 바탕으로 사용자에게 힘찬 하루를 여는 다정한 브리핑 메시지를 작성해줘.
출발 안내가 있다면 누락 없이 깔끔한 글머리 기호로 강조해줘.
"""

    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=user_content,
        config=genai.types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            temperature=0.7
        )
    )
    return response.text

def chat_with_taemin(user_message, chat_history=None):
    """일반 대화 및 실시간 질문 응답 처리"""
    client = get_gemini_client()
    
    # 위치/출발 관련 질문이 들어왔을 때 오늘 캘린더 정보를 주입
    context_addon = ""
    if any(k in user_message for k in ["출발", "몇 시에", "어떻게 가", "얼마나 걸려", "이동"]):
        events = fetch_today_events()
        travel_guidance_list = []
        for ev in events:
            summary = ev.get("summary", "")
            location = ev.get("location", "")
            start_raw = ev.get("start", {}).get("dateTime", "")
            if location and "T" in start_raw:
                try:
                    dt = datetime.fromisoformat(start_raw.split("+")[0])
                    travel_guidance_list.append(get_departure_guidance(summary, location, dt))
                except:
                    pass
        if travel_guidance_list:
            context_addon = "\n\n[참고: 오늘 일정 경로 정보]\n" + "\n".join(travel_guidance_list)

    prompt = f"{user_message}{context_addon}"
    
    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt,
        config=genai.types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            temperature=0.7
        )
    )
    return response.text
