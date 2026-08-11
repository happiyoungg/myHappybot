# uv pip install langchain-mcp-adapters langchain langchain-openai python-dotenv streamlit
import streamlit as st
from dotenv import load_dotenv

from langchain.tools import tool
from langchain.agents import create_agent

load_dotenv()

@tool
def get_weather(location: str) -> str:
    """특정 지역의 날씨 정보 제공"""
    return f"{location}의 날씨: 눈, -2°C, 미세먼지 매우나쁨"

tools = [get_weather]

agent = create_agent(model="gpt-5.4-mini", tools=tools)

if "messages" not in st.session_state:
    st.session_state.messages = []

prompt = st.chat_input("무엇을 도와드릴까요?")

if prompt:
    st.session_state.messages.append({"role": "user", "content": prompt})
    response = agent.invoke({"messages": [{"role": "user", "content": prompt}]})
    response_content = response["messages"][-1].content
    st.session_state.messages.append({"role": "ai", "content": response_content})

for message in st.session_state.messages :
    with st.chat_message(message["role"]):
        st.markdown(message["content"])
