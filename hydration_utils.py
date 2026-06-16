import requests
import concurrent.futures
import json
import os
import time
from typing import Dict, Optional
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()

# ---------- Configuration ----------
GEMINI_API_KEY = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = "gemini-1.5-flash"
GEMINI_TEMPERATURE = 0.7

DEFAULT_LOCATION = {
    'lat': 11.0168, 'lon': 76.9558,
    'city': 'Coimbatore', 'state': 'Tamil Nadu', 'country': 'India'
}

WEATHER_API_URL = "https://api.open-meteo.com/v1/forecast"
WEATHER_PARAMS = "temperature_2m,relative_humidity_2m,wind_speed_10m,pressure_msl,uv_index"

# ---------- Location Service ----------
class LocationService:
    def __init__(self):
        self.cached_location = None

    def get_location(self) -> Dict:
        if self.cached_location:
            return self.cached_location
        location = self._get_consensus_location()
        if location:
            self.cached_location = location
            return location
        return DEFAULT_LOCATION

    def _get_consensus_location(self) -> Optional[Dict]:
        apis = [self._try_ipapi, self._try_ipinfo, self._try_ipapi_co]
        results = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
            futures = [executor.submit(api) for api in apis]
            for future in concurrent.futures.as_completed(futures):
                try:
                    result = future.result()
                    if result and result.get('city') != 'Unknown':
                        results.append(result)
                except:
                    pass
        if not results:
            return None
        city_votes = {}
        for r in results:
            city = r['city']
            city_votes[city] = city_votes.get(city, 0) + 1
        best_city = max(city_votes, key=city_votes.get)
        for r in results:
            if r['city'] == best_city:
                r['confidence'] = f"{city_votes[best_city]}/{len(results)} APIs agreed"
                return r
        return results[0]

    def _try_ipapi(self):
        try:
            r = requests.get('http://ip-api.com/json/', timeout=5)
            d = r.json()
            if d.get('status') == 'success':
                return {
                    'lat': d['lat'], 'lon': d['lon'],
                    'city': d.get('city', 'Unknown'),
                    'state': d.get('regionName', ''),
                    'country': d.get('country', 'India'),
                    'source': 'ip-api'
                }
        except: pass

    def _try_ipinfo(self):
        try:
            r = requests.get('https://ipinfo.io/json', timeout=5)
            d = r.json()
            if 'loc' in d:
                lat, lon = d['loc'].split(',')
                return {
                    'lat': float(lat), 'lon': float(lon),
                    'city': d.get('city', 'Unknown'),
                    'state': d.get('region', ''),
                    'country': d.get('country', 'India'),
                    'source': 'ipinfo'
                }
        except: pass

    def _try_ipapi_co(self):
        try:
            r = requests.get('https://ipapi.co/json/', timeout=5)
            d = r.json()
            if 'error' not in d and d.get('city'):
                return {
                    'lat': d.get('latitude'), 'lon': d.get('longitude'),
                    'city': d.get('city', 'Unknown'),
                    'state': d.get('region', ''),
                    'country': d.get('country_name', 'India'),
                    'source': 'ipapi.co'
                }
        except: pass

# ---------- Weather Service ----------
class WeatherService:
    def get_weather(self, lat, lon):
        params = {
            "latitude": lat,
            "longitude": lon,
            "current": WEATHER_PARAMS,
            "timezone": "auto"
        }
        try:
            r = requests.get(WEATHER_API_URL, params=params, timeout=10)
            r.raise_for_status()
            data = r.json()
            current = data.get("current", {})
            return {
                "temperature": current.get("temperature_2m"),
                "humidity": current.get("relative_humidity_2m"),
                "wind_speed": current.get("wind_speed_10m"),
                "pressure": current.get("pressure_msl"),
                "uv_index": current.get("uv_index")
            }
        except Exception as e:
            print(f"❌ Weather error: {e}")
            return None

# ---------- Hydration Scheduler ----------
class HydrationScheduler:
    def generate_schedule(self, water_data: dict, wake_up: int = 7, sleep: int = 23):
        total_ml = water_data['water_litres'] * 1000
        interval = water_data['interval_minutes']
        serving = water_data['serving_ml']

        waking_minutes = (sleep - wake_up) * 60
        servings = min(int(total_ml / serving), waking_minutes // interval)

        schedule = []
        current_time = datetime.strptime(f"{wake_up}:00", "%H:%M")
        for i in range(servings):
            schedule.append({
                'time': current_time.strftime("%I:%M %p"),
                'amount_ml': serving,
                'percentage': round(((i+1)*serving / total_ml) * 100)
            })
            current_time += timedelta(minutes=interval)

        return {
            'total_ml': int(total_ml),
            'serving_ml': serving,
            'interval_minutes': interval,
            'total_servings': servings,
            'schedule': schedule,
            'time_range': f"{wake_up}:00 - {sleep}:00"
        }

# ---------- Gemini Recommendation Agent (fallback + AI) ----------
class GeminiAgent:
    def __init__(self):
        self.api_key = GEMINI_API_KEY
        self.api_url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}"

    def _call_gemini(self, prompt: str) -> Optional[str]:
        try:
            headers = {'Content-Type': 'application/json'}
            data = {
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {
                    "temperature": GEMINI_TEMPERATURE,
                    "maxOutputTokens": 400,
                    "topP": 0.95,
                    "topK": 40
                }
            }
            response = requests.post(self.api_url, headers=headers, json=data, timeout=30)
            if response.status_code == 429:
                time.sleep(3)
                response = requests.post(self.api_url, headers=headers, json=data, timeout=30)
            response.raise_for_status()
            result = response.json()
            if 'candidates' in result and result['candidates']:
                parts = result['candidates'][0]['content']['parts']
                if parts:
                    return parts[0].get('text', '')
            return None
        except:
            return None

    def get_recommendations(self, location: dict, weather: dict) -> dict:
        temp = weather['temperature']
        humidity = weather['humidity']
        uv = weather['uv_index']
        city = location.get('city', 'your area')
        hour = datetime.now().hour

        if 5 <= hour < 12:
            time_context = "morning"
        elif 12 <= hour < 17:
            time_context = "afternoon"
        elif 17 <= hour < 21:
            time_context = "evening"
        else:
            time_context = "night"

        prompt = f"""You are a practical, modern health advisor. Give realistic recommendations.

CONTEXT:
- City: {city}, India
- Temperature: {temp}°C, Humidity: {humidity}%, UV Index: {uv}
- Time: {time_context}
- Month: {datetime.now().strftime('%B')}

IMPORTANT RULES:
- Be practical and realistic - what would a normal person actually do?
- No ancient/traditional remedies unless they're genuinely common today
- Suggest things people actually have at home or can easily buy
- Don't force regional foods if they're not relevant
- Keep it simple and actionable

Return ONLY valid JSON (no markdown, no ```):
{{
  "summary": "One friendly sentence about today's weather and what it means for health",
  "hydration": "Simple, practical hydration tips. How much water, when to drink, what's easily available (water, coconut water, buttermilk, lemon water, etc.)",
  "food": "2-3 realistic meal suggestions. Things people actually eat. If it's hot, suggest light meals. If cool, suggest normal food.",
  "activity": "One practical activity suggestion considering the weather and time of day",
  "water_data": {{"water_litres": 2.8, "interval_minutes": 30, "serving_ml": 200, "risk_level": "moderate"}}
}}

Keep each field under 80 words. Be natural, like advice from a friend."""

        response = self._call_gemini(prompt)
        if response:
            try:
                content = response.strip()
                if content.startswith("```"):
                    lines = content.split('\n')
                    content = '\n'.join(lines[1:-1] if lines[-1].strip() == '```' else lines[1:])
                start = content.find('{')
                end = content.rfind('}') + 1
                if start >= 0 and end > start:
                    data = json.loads(content[start:end])
                    if 'water_data' in data:
                        return data
            except:
                pass
        return self._get_fallback(temp, humidity, uv, city, time_context)

    def _get_fallback(self, temp, humidity, uv, city, time_context):
        water = 2.5
        if temp >= 35: water += 1.0; risk = "extreme"; interval = 15; serving = 150
        elif temp >= 30: water += 0.6; risk = "high"; interval = 20; serving = 180
        elif temp >= 20: water += 0.3; risk = "moderate"; interval = 30; serving = 200
        else: risk = "low"; interval = 45; serving = 200
        if humidity >= 70: water += 0.3
        elif humidity < 40: water -= 0.1

        if temp > 35:
            summary = f"It's really hot in {city} today at {temp}°C. Stay indoors if possible and keep yourself well hydrated."
            hydration = f"Drink {water}L water today. Keep a water bottle on your desk. Coconut water or buttermilk if available. Avoid tea/coffee in the afternoon. Set a 20-min reminder on your phone."
            food = "Have light meals today. Curd rice, salad, sandwiches. Fresh fruits like watermelon or orange. Avoid heavy biryani or fried food for lunch."
            activity = "Skip outdoor exercise today. If you must go out, do it before 8 AM or after 6 PM. Carry water with you."
        elif temp > 30:
            summary = f"Warm day in {city} at {temp}°C. Stay comfortable and drink enough water throughout the day."
            hydration = f"Aim for {water}L today. Start with 2 glasses in the morning. Keep sipping water at your desk. Lemon water is refreshing. Don't wait till you're thirsty."
            food = "Eat light but filling meals. Rice with dal and vegetables. A side of yogurt. Fresh fruits as snacks. Normal home-cooked food is best."
            activity = "Morning or evening walk is fine. Avoid peak sun hours (12-3 PM). Indoor exercise is comfortable today."
        elif temp > 20:
            summary = f"Pleasant {temp}°C in {city} today. Comfortable weather, but don't forget to stay hydrated."
            hydration = f"Drink {water}L water today. Regular intervals - a glass every 1-2 hours. Your normal routine should be fine."
            food = "Normal balanced meals. Whatever you usually eat - just include some fruits and vegetables. Nothing special needed."
            activity = "Great day for outdoor activities. Walking, jogging, sports - all good. Just carry water if you're out long."
        else:
            summary = f"Cooler day at {temp}°C in {city}. You might not feel thirsty, but your body still needs water."
            hydration = f"Drink {water}L today. Warm water is comforting in this weather. Herbal tea or soup counts toward your intake. Don't skip water just because it's cool."
            food = "Warm meals are nice today. Dal, roti, soup, or whatever you like. Hot beverages are fine. Normal eating routine works."
            activity = "Good day for exercise. A brisk walk or jog will warm you up. Indoor or outdoor - whatever you prefer."

        return {
            "summary": summary,
            "hydration": hydration,
            "food": food,
            "activity": activity,
            "water_data": {
                "water_litres": round(water, 1),
                "interval_minutes": interval,
                "serving_ml": serving,
                "risk_level": risk
            }
        }