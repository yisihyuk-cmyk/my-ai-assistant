import streamlit as st
import sqlite3
from datetime import datetime
from google import genai
from google.genai import types

# 모바일 화면 최적화 설정
st.set_page_config(page_title="나만의 AI 비서", page_icon="🤖")
st.title("🤖 나만의 개인 비서")

# API 키 설정 (보안 저장소에서 가져옴)
api_key = st.secrets.get("GEMINI_API_KEY")
if not api_key:
    st.error("API 키가 설정되지 않았습니다. 관리자 설정을 확인해주세요.")
    st.stop()

client = genai.Client(api_key=api_key)

# 1. 간단한 메모/일정 저장소(DB) 준비
def init_db():
    conn = sqlite3.connect("assistant.db")
    c = conn.cursor()
    c.execute("CREATE TABLE IF NOT EXISTS notes (id INTEGER PRIMARY KEY, content TEXT, created_at TEXT)")
    conn.commit()
    conn.close()

init_db()

# 2. AI가 사용할 도구 함수 정의
def save_memo(content: str) -> str:
    """사용자의 일정이나 중요한 메모, 할 일을 기록합니다."""
    conn = sqlite3.connect("assistant.db")
    c = conn.cursor()
    c.execute("INSERT INTO notes (content, created_at) VALUES (?, ?)", 
              (content, datetime.now().strftime("%Y-%m-%d %H:%M")))
    conn.commit()
    conn.close()
    return f"기록 완료: '{content}'"

def read_memos() -> str:
    """저장된 모든 메모와 일정을 확인합니다."""
    conn = sqlite3.connect("assistant.db")
    c = conn.cursor()
    c.execute("SELECT content, created_at FROM notes ORDER BY id DESC LIMIT 10")
    rows = c.fetchall()
    conn.close()
    if not rows:
        return "현재 저장된 메모나 일정이 없습니다."
    return "\n".join([f"- [{time}] {text}" for text, time in rows])

tools = [save_memo, read_memos]

# 3. 대화 화면 구성
if "messages" not in st.session_state:
    st.session_state.messages = []

# 이전 대화 출력
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.write(msg["content"])

# 스마트폰 입력창
if user_input := st.chat_input("일정이나 메모를 말씀해주세요..."):
    st.session_state.messages.append({"role": "user", "content": user_input})
    with st.chat_message("user"):
        st.write(user_input)

    # AI 답변 생성
    with st.chat_message("assistant"):
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=user_input,
            config=types.GenerateContentConfig(
                tools=tools,
                system_instruction="너는 친절한 모바일 개인 비서야. 사용자가 일정이나 메모를 남기면 저장해주고, 확인해달라고 하면 목록을 알려줘."
            )
        )
        st.write(response.text)
        st.session_state.messages.append({"role": "assistant", "content": response.text})