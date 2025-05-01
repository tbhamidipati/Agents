# tools/weather.py

import httpx

def get_weather(city: str) -> str:
    try:
        response = httpx.get(f"http://wttr.in/{city}?format=3")
        return response.text.strip()
    except Exception as e:
        return f"Error fetching weather: {e}"

# Tool schema for LLM
weather_tool = {
    "name": "get_weather",
    "description": "Get the current weather for a city",
    "parameters": {
        "type": "object",
        "properties": {
            "city": {
                "type": "string",
                "description": "Name of the city"
            }
        },
        "required": ["city"]
    }
}
