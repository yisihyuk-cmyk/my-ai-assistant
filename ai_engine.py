import os
import re
from datetime import datetime, timedelta
import streamlit as st
from google import genai
import services

def get_gemini_client():
    api_key = None
    if hasattr(st, "secrets") and "GEMINI_API_KEY" in st.secrets:
        api_key = st.secrets["GEMINI_API_KEY"]
    else:
        api_key = os.getenv("GEMINI_API_KEY")
    return genai.Client(api_key=api_key)

SYSTEM_PROMPT = """
당신은 다정하고 꼼꼼한 1인 전담 AI 비서 '태민이'입니다.
사용자의 업무 마감 및 할 일(Task), 이동 일정, 장보기 및 일상 루틴을 똑똑하게 챙깁니다.
핵심 사항은 놓치지 않도록 직관적이고 깔끔하게 안내하며, 과도한 미사여구 없이 따뜻하고 신뢰감 있는 어투를 유지합니다.
"""

def generate_daily_briefing():
    """오늘의 일정, 대기 중인 [할 일], 이동 권장 출발 시각을 종합한 브리핑 생성"""
    # 1. 만료된 오래된 할 일 자동 청소
    services.clean_expired_tasks(hours_limit=24)
    
    client = get_gemini_client()
    events = services.fetch_today_events()
    active_tasks = services.get_active_tasks()
    
    # 일정 및 출발 안내 취합
    events_summary = []
    travel_guidance_list = []
    
    for ev in events:
        summary = ev.get("summary", "제목 없음")
        start_raw = ev.get("start", {}).get("dateTime", ev.get("start", {}).get("date", ""))
        location = ev.get("location", "")
        
        events_summary.append(f"- {summary} (시작: {start_raw}, 장소: {location if location else '미정'})")
        
        if location and "T" in start_raw:
            try:
                clean_time = start_raw.split("+")[0]
                dt = datetime.fromisoformat(clean_time)
                guidance = services.get_departure_guidance(summary, location, dt)
                travel_guidance_list.append(guidance)
            except Exception as e:
                print(f"시간 파싱 실패: {e}")

    schedule_text = "\n".join(events_summary) if events_summary else "오늘 등록된 주요 일정이 없습니다."
    travel_text = "\n\n".join(travel_guidance_list) if travel_guidance_list else ""
    
    # 미완료 Tasks 요약
    tasks_summary = []
    for t in active_tasks:
        tasks_summary.append(f"- {t.get('title')}")
    tasks_text = "\n".join(tasks_summary) if tasks_summary else "현재 밀려 있는 할 일이 없습니다."

    user_content = f"""
다음은 오늘 사용자의 캘린더 일정입니다:
{schedule_text}

아래는 카카오 경로 기반으로 계산된 이동 및 권장 출발 시간 안내입니다:
{travel_text}

아래는 현재 완료 대기 중인 업무 [할 일] 목록입니다:
{tasks_text}

위 데이터를 바탕으로 사용자에게 오늘 하루를 정리해 주는 다정하고 똑똑한 브리핑 메시지를 작성해줘.
할 일과 출발 시각 안내가 있다면 눈에 잘 띄도록 글머리 기호로 구분해줘.
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
    """할 일 등록/완료 처리 및 일반 대화/경로 질문 처리"""
    msg_clean = user_message.strip()
    
    # 1. 완료/삭제 의도 감지
    finish_keywords = ["끝냈어", "완료했어", "마무리했어", "다 했어", "삭제해줘", "지워줘", "끝남"]
    if any(k in msg_clean for k in finish_keywords):
        # 핵심 키워드 분리
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
        # 기본 마감: 오늘 자정 전 (12시간 뒤)
        due_time = datetime.utcnow() + timedelta(hours=12)
        success, task_id = services.add_work_task(title=msg_clean, due_datetime=due_time)
        if success:
            return (
                f"📌 **[할 일 등록 완료]**\n\n"
                f"- 등록 내용: {msg_clean}\n"
                f"- 구글 Tasks에 저장해 두었으니 잊지 않도록 챙겨줄게.\n"
                f"- 마무리되면 **'{msg_clean.split()[0]} 끝냈어'**라고 말해줘!"
            )

    # 3. 출발 및 이동 관련 질문일 경우 오늘 일정/경로 컨텍스트 주입
    context_addon = ""
    if any(k in msg_clean for k in ["출발", "몇 시에", "어떻게 가", "얼마나 걸려", "이동"]):
        events = services.fetch_today_events()
        travel_guidance_list = []
        for ev in events:
            summary = ev.get("summary", "")
            location = ev.get("location", "")
            start_raw = ev.get("start", {}).get("dateTime", "")
            if location and "T" in start_raw:
                try:
                    dt = datetime.fromisoformat(start_raw.split("+")[0])
                    travel_guidance_list.append(services.get_departure_guidance(summary, location, dt))
                except:
                    pass
        if travel_guidance_list:
            context_addon = "\n\n[오늘 일정 경로 및 출발 계산 정보]\n" + "\n".join(travel_guidance_list)

    # 4. Gemini 대화 모델 답변 생성
    client = get_gemini_client()
    prompt = f"{msg_clean}{context_addon}"
    
    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt,
        config=genai.types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            temperature=0.7
        )
    )
    return response.text
