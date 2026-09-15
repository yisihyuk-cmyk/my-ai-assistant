from datetime import datetime, timedelta, timezone

# 한국 표준시(KST: UTC+9) 타임존 객체
KST = timezone(timedelta(hours=9))

def fetch_today_events(target_date=None):
    service = get_calendar_service()
    if not service:
        return []
    
    # Secrets의 CALENDAR_ID (yisihyuk@gmail.com) 사용
    cal_id = CALENDAR_ID if CALENDAR_ID else "primary"
    
    # 한국 시간 기준 현재 시각 계산
    now_kst = datetime.now(timezone.utc).astimezone(KST)
    if target_date is None:
        target_date = now_kst
    
    # 한국 시간 기준 당일 시작(00:00:00)과 끝(23:59:59)
    start_of_day = datetime(target_date.year, target_date.month, target_date.day, 0, 0, 0, tzinfo=KST).isoformat()
    end_of_day = datetime(target_date.year, target_date.month, target_date.day, 23, 59, 59, tzinfo=KST).isoformat()
    
    try:
        events_result = service.events().list(
            calendarId=cal_id,
            timeMin=start_of_day,
            timeMax=end_of_day,
            singleEvents=True,
            orderBy="startTime"
        ).execute()
        items = events_result.get("items", [])
        print(f"[{cal_id}] 캘린더 조회 성공: {len(items)}건")
        return items
    except Exception as e:
        print(f"Calendar API 조회 오류 ({cal_id}): {e}")
        return []
