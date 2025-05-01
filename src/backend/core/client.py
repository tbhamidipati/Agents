import json
import traceback
from openai import AsyncAzureOpenAI
import chainlit as cl
from mcp.types import TextContent, ImageContent


from backend.config import (
    AZURE_OPENAI_MODEL,
    AZURE_OPENAI_ENDPOINT,
    AZURE_OPENAI_API_KEY,
    AZURE_OPENAI_API_VERSION,
    SYSTEM_PROMPT
)
from backend.tools import get_weather, weather_tool

class ChatClient:
    def __init__(self):
        self.client = AsyncAzureOpenAI(
            azure_endpoint=AZURE_OPENAI_ENDPOINT,
            api_key=AZURE_OPENAI_API_KEY,
            api_version=AZURE_OPENAI_API_VERSION,
        )
        self.deployment_name = AZURE_OPENAI_MODEL
        self.system_prompt = SYSTEM_PROMPT
        self.messages = []
        self.active_streams = []

    async def _cleanup_streams(self):
        for stream in self.active_streams:
            try:
                await stream.aclose()
            except Exception:
                pass
        self.active_streams = []

    async def process_response_stream(self, response_stream, tools, temperature=0):
        function_arguments = ""
        function_name = ""
        tool_call_id = ""
        is_collecting_function_args = False
        collected_messages = []
        tool_called = False

        self.active_streams.append(response_stream)

        try:
            async for part in response_stream:
                if part.choices == []:
                    continue
                delta = part.choices[0].delta
                finish_reason = part.choices[0].finish_reason

                if delta.content:
                    collected_messages.append(delta.content)
                    yield delta.content

                if delta.tool_calls:
                    tool_call = delta.tool_calls[0]
                    if tool_call.function.name:
                        function_name = tool_call.function.name
                        tool_call_id = tool_call.id
                    if tool_call.function.arguments:
                        function_arguments += tool_call.function.arguments
                        is_collecting_function_args = True

                if finish_reason == "tool_calls" and is_collecting_function_args:
                    function_args = json.loads(function_arguments)
                    mcp_tools = cl.user_session.get("mcp_tools", {})
                    mcp_name = None
                    for connection_name, session_tools in mcp_tools.items():
                        if any(tool.get("name") == function_name for tool in session_tools):
                            mcp_name = connection_name
                            break

                    self.messages.append({
                        "role": "assistant",
                        "tool_calls": [{
                            "id": tool_call_id,
                            "function": {
                                "name": function_name,
                                "arguments": function_arguments
                            },
                            "type": "function"
                        }]
                    })

                    if response_stream in self.active_streams:
                        self.active_streams.remove(response_stream)
                        await response_stream.close()

                    func_response = await self.call_tool(mcp_name, function_name, function_args)
                    self.messages.append({
                        "tool_call_id": tool_call_id,
                        "role": "tool",
                        "name": function_name,
                        "content": json.loads(func_response),
                    })

                    self.last_tool_called = function_name
                    tool_called = True
                    break

                if finish_reason == "stop":
                    if collected_messages:
                        final_content = ''.join([msg for msg in collected_messages if msg is not None])
                        if final_content.strip():
                            self.messages.append({"role": "assistant", "content": final_content})

                    if response_stream in self.active_streams:
                        self.active_streams.remove(response_stream)
                    break

        except GeneratorExit:
            if response_stream in self.active_streams:
                self.active_streams.remove(response_stream)
                await response_stream.aclose()
        except Exception as e:
            print(f"Error in process_response_stream: {e}")
            traceback.print_exc()
            if response_stream in self.active_streams:
                self.active_streams.remove(response_stream)
            self.last_error = str(e)

        self.tool_called = tool_called
        self.last_function_name = function_name if tool_called else None

    async def generate_response(self, human_input, tools, temperature=0):
        self.messages.append({"role": "user", "content": human_input})

        while True:
            response_stream = await self.client.chat.completions.create(
                model=self.deployment_name,
                messages=self.messages,
                tools=tools,
                parallel_tool_calls=False,
                stream=True,
                temperature=temperature
            )

            try:
                async for token in self._stream_and_process(response_stream, tools, temperature):
                    yield token

                if not self.tool_called:
                    break
            except GeneratorExit:
                await self._cleanup_streams()
                return

    async def _stream_and_process(self, response_stream, tools, temperature):
        self.tool_called = False
        self.last_function_name = None
        self.last_error = None

        async for token in self.process_response_stream(response_stream, tools, temperature):
            yield token

    async def call_tool(self, mcp_name, function_name, function_args):
        if function_name == "get_weather":
            city = function_args.get("city", "Unknown")
            result = get_weather(city)
            return json.dumps([{"type": "text", "text": result}])

        try:
            mcp_session, _ = cl.context.session.mcp_sessions.get(mcp_name)
            func_response = await mcp_session.call_tool(function_name, function_args)
            resp_items = []
            for item in func_response.content:
                if isinstance(item, TextContent):
                    resp_items.append({"type": "text", "text": item.text})
                elif isinstance(item, ImageContent):
                    resp_items.append({
                        "type": "image_url",
                        "image_url": {"url": f"data:{item.mimeType};base64,{item.data}"},
                    })
                else:
                    raise ValueError(f"Unsupported content type: {type(item)}")
            return json.dumps(resp_items)
        except Exception as e:
            traceback.print_exc()
            return json.dumps([{"type": "text", "text": str(e)}])
