import chainlit as cl
from backend.core.client import ChatClient
from backend.tools import get_weather, weather_tool

@cl.on_chat_start
async def start_chat():
    client = ChatClient()
    cl.user_session.set("messages", [])
    cl.user_session.set("system_prompt", client.system_prompt)

@cl.on_message
async def on_message(message: cl.Message):
    tools = [{"type": "function", "function": weather_tool}]
    client = ChatClient()
    client.messages = cl.user_session.get("messages", [])

    msg = cl.Message(content="")
    async for text in client.generate_response(human_input=message.content, tools=tools):
        await msg.stream_token(text)

    cl.user_session.set("messages", client.messages)
