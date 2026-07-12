# uv pip install langchain-mcp-adapters langchain langchain-openai python-dotenv streamlit
import streamlit as st
from dotenv import load_dotenv
from openai import OpenAI

from langchain.agents import create_agent

load_dotenv()

client = OpenAI()

if "messages" not in st.session_state:
    st.session_state.messages = []

prompt = st.chat_input("무엇을 도와드릴까요?")

if prompt:
    st.session_state.messages.append({"role": "user", "content": prompt})
    response = client.responses.create(
        model="gpt-5.5",
        input=prompt
    )
    st.session_state.messages.append({"role": "ai", "content": response.output_text})

for message in st.session_state.messages :
    with st.chat_message(message["role"]):
        st.markdown(message["content"])
