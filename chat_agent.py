import os
import json
import requests
import time
from dotenv import load_dotenv
import db_manager

load_dotenv()

GEMINI_API_KEY = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = "gemini-3.1-flash-lite"
GEMINI_TEMPERATURE = 0.7

class ContextAwareChatAgent:
    def __init__(self, location, weather, water_data, schedule_data):
        self.location = location
        self.weather = weather
        self.water_data = water_data
        self.schedule_data = schedule_data
        self.api_key = GEMINI_API_KEY
        self.api_url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}"

    def _call_gemini(self, prompt: str) -> str:
        if not self.api_key:
            return "❌ API key not set. Please set GEMINI_API_KEY in .env"
        headers = {"Content-Type": "application/json"}
        data = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": GEMINI_TEMPERATURE,
                "maxOutputTokens": 500,
                "topP": 0.95,
                "topK": 40
            }
        }
        try:
            response = requests.post(self.api_url, headers=headers, json=data, timeout=30)
            if response.status_code == 429:
                time.sleep(3)
                response = requests.post(self.api_url, headers=headers, json=data, timeout=30)
            response.raise_for_status()
            result = response.json()
            if "candidates" in result and result["candidates"]:
                return result["candidates"][0]["content"]["parts"][0].get("text", "No response text.")
            return "No valid response from Gemini."
        except Exception as e:
            return f"Error: {e}"

    def chat(self, user_message: str) -> str:
        # Get exact numbers from DB
        today_intake = db_manager.get_today_water_intake()
        total_target_ml = int(self.water_data.get('water_litres', 2.8) * 1000)
        remaining = max(0, total_target_ml - today_intake)

        recent = db_manager.get_recent_conversations(limit=3)
        conv_lines = []
        for user, bot in reversed(recent):
            conv_lines.append(f"User: {user}")
            conv_lines.append(f"Assistant: {bot}")
        recent_context = "\n".join(conv_lines) if conv_lines else "No previous conversation."

        city = self.location.get('city', 'your city')
        temp = self.weather.get('temperature', '?')
        humidity = self.weather.get('humidity', '?')
        uv = self.weather.get('uv_index', '?')
        interval = self.water_data.get('interval_minutes', 30)
        serving = self.water_data.get('serving_ml', 200)

        system_context = f"""You are a helpful AI assistant named CANI.

CURRENT FACTS (do not change these numbers):
- Location: {city}, Weather: {temp}°C, humidity {humidity}%, UV {uv}
- Daily water target: {total_target_ml} ml
- User has reported drinking: {today_intake} ml today
- Remaining to reach target: {remaining} ml
- Recommended serving: {serving} ml every {interval} minutes

RECENT CONVERSATION:
{recent_context}

INSTRUCTIONS:
- When the user asks about how much they've drunk, give them the exact number from "User has reported drinking" above.
- When they ask how much more, give them the "Remaining" number.
- Never guess or invent water amounts. Use only the numbers provided.
- Keep answers concise and friendly.
"""
        full_prompt = f"{system_context}\nUser: {user_message}\nAssistant:"
        return self._call_gemini(full_prompt)