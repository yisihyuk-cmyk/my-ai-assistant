import streamlit as st
import sqlite3
from datetime import datetime
import google.generativeai as genai

# 모바일 화면 최적화 설정
st.set_page_config(page_title="나만의 AI 비서", page_icon="🤖")
st.title("🤖 나만의 개인 비서")

# API 키 설정
api_key = st.secrets.get("GEMINI_API_KEY")
if not api_key:
    st.error("API 키가 설정되지 않았습니다.")
    st.stop()

genai.configure(api_key=api_key)

# 1. 로컬 저장소 초기화
def init_db():
    conn = sqlite3.connect("assistant.db")
    c = conn.cursor()
    c.execute("CREATE TABLE IF NOT EXISTS notes (id INTEGER PRIMARY KEY, content TEXT, created_at TEXT)")
    conn.commit()
    conn.close()

init_db()

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

# 2. 모델 설정
model = genai.GenerativeModel(
    model_name="gemini-1.5-flash",
    tools=[save_memo, read_memos],
    system_instruction="너는 친절한 모바일 개인 비서야. 사용자가 일정이나 메모를 남기면 save_memo 도구로 저장해주고, 확인해달라고 하면 read_memos 도구로 목록을 확인해서 친절히 알려줘."
)

if "chat" not in st.session_state:
    st.session_state.chat = model.start_chat(enable_automatic_function_calling=True)

if "messages" not in st.session_state:
    st.session_state.messages = []

# 대화 내용 표시
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.write(msg["content"])

# 입력창
if user_input := st.chat_input("일정이나 메모를 말씀해주세요..."):
    st.session_state.messages.append({"role": "user", "content": user_input})
    with st.chat_message("user"):
        st.write(user_input)

    with st.chat_message("assistant"):
        response = st.session_state.chat.send_message(user_input)
        st.write(response.text)
        st.session_state.messages.append({"role": "assistant", "content": response.text})
