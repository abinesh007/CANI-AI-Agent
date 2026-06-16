import tkinter as tk
from tkinter import scrolledtext, Entry, Button
import threading
import re
import datetime
from hydration_utils import LocationService, WeatherService, HydrationScheduler, GeminiAgent
from chat_agent import ContextAwareChatAgent
import db_manager

# ---------- Improved parser ----------
def parse_water_intake(text):
    """
    Returns amount in ml if the user explicitly states they drank water.
    Returns None if it looks like a question or no amount is mentioned.
    """
    text = text.lower()
    # If it's a question, skip logging (we only log statements)
    question_words = ['how', 'what', 'when', 'why', 'where', 'who', '?', 'can you', 'tell me']
    if any(word in text for word in question_words):
        return None

    patterns = [
        (r'(\d+\.?\d*)\s*(?:ml|millilitres?|milliliters?)', 1),
        (r'(\d+\.?\d*)\s*(?:l|litre|liters?)', 1000),
        (r'(\d+)\s*(?:glass|glasses)', 250),
        (r'(\d+)\s*(?:cup|cups)', 240),
    ]
    for pattern, multiplier in patterns:
        match = re.search(pattern, text)
        if match:
            amount = float(match.group(1)) * multiplier
            return int(amount)
    return None

def parse_meal_confirmation(text):
    """Detect if user confirms having a meal."""
    meal_keywords = {
        'breakfast': ['breakfast', 'brunch'],
        'lunch': ['lunch', 'noon meal'],
        'dinner': ['dinner', 'supper'],
        'snack': ['snack', 'evening snack']
    }
    text = text.lower()
    for meal, keywords in meal_keywords.items():
        for kw in keywords:
            if kw in text and any(phrase in text for phrase in ['had', 'ate', 'done', 'finished', 'completed']):
                return meal
    return None

# ---------- Main GUI Application ----------
class ChatApp:
    def __init__(self, root):
        self.root = root
        self.root.title("CANI - Context-Aware AI Chatbot")
        self.root.geometry("650x550")
        self.root.resizable(True, True)

        # ---- Init DB ----
        db_manager.init_db()

        # ---- Fetch location & weather ----
        self.location = LocationService().get_location()
        self.weather = WeatherService().get_weather(self.location['lat'], self.location['lon'])
        if not self.weather:
            self.weather = {"temperature": 25, "humidity": 60, "uv_index": 3}  # fallback

        # ---- Get recommendations & schedule ----
        gemini_agent = GeminiAgent()
        self.recommendations = gemini_agent.get_recommendations(self.location, self.weather)
        self.water_data = self.recommendations.get('water_data', {'water_litres': 2.8, 'interval_minutes': 30, 'serving_ml': 200})
        self.scheduler = HydrationScheduler()
        self.schedule_data = self.scheduler.generate_schedule(self.water_data)

        # ---- Build context-aware chatbot ----
        self.chat_agent = ContextAwareChatAgent(
            location=self.location,
            weather=self.weather,
            water_data=self.water_data,
            schedule_data=self.schedule_data
        )

        # ---- GUI widgets ----
        self.chat_area = scrolledtext.ScrolledText(root, wrap=tk.WORD, state='disabled', font=("Arial", 11))
        self.chat_area.pack(padx=10, pady=10, fill=tk.BOTH, expand=True)

        input_frame = tk.Frame(root)
        input_frame.pack(padx=10, pady=(0,10), fill=tk.X)

        self.input_field = Entry(input_frame, font=("Arial", 11))
        self.input_field.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0,5))
        self.input_field.bind("<Return>", self.send_message)

        self.send_btn = Button(input_frame, text="Send", command=self.send_message, width=8)
        self.send_btn.pack(side=tk.RIGHT)

        self.status = tk.Label(root, text="Ready", anchor=tk.W, font=("Arial", 9))
        self.status.pack(fill=tk.X, padx=10, pady=(0,5))

        # ---- Display startup info ----
        self.display_message("🌤️", f"Welcome! I'm CANI.\n📍 {self.location['city']}, {self.location.get('state', '')}\n"
                                   f"🌡️ {self.weather['temperature']}°C | 💧 Humidity: {self.weather['humidity']}%")
        self.display_message("💧", f"Today's water target: {self.water_data['water_litres']}L "
                                   f"({self.schedule_data['serving_ml']}ml every {self.schedule_data['interval_minutes']} min)")
        self.display_message("🍽️", f"Food tip: {self.recommendations.get('food', '')[:150]}...")

        # ---- Update status bar with initial intake ----
        self.update_status_bar()

        # ---- Start periodic reminder timer ----
        self.reminder_interval = self.schedule_data['interval_minutes'] * 60  # seconds
        self.next_reminder_index = 0
        self.schedule_list = self.schedule_data['schedule']
        self.reminder_running = True
        self.schedule_reminder()

    def display_message(self, sender, message):
        self.chat_area.config(state='normal')
        self.chat_area.insert(tk.END, f"{sender}: {message}\n\n")
        self.chat_area.see(tk.END)
        self.chat_area.config(state='disabled')

    def update_status_bar(self):
        today_total = db_manager.get_today_water_intake()
        target = int(self.water_data['water_litres'] * 1000)
        remaining = max(0, target - today_total)
        self.status.config(text=f"Today: {today_total}ml / {target}ml  |  Remaining: {remaining}ml")

    def send_message(self, event=None):
        user_msg = self.input_field.get().strip()
        if not user_msg:
            return
        self.input_field.delete(0, tk.END)
        self.display_message("You", user_msg)

        # ---- Parse and log only if it's a statement ----
        amount_ml = parse_water_intake(user_msg)
        if amount_ml is not None:
            db_manager.log_water_intake(amount_ml, note=user_msg)
            self.update_status_bar()
        else:
            meal = parse_meal_confirmation(user_msg)
            if meal:
                db_manager.log_meal(meal, True)
                self.update_status_bar()

        # ---- Get bot reply ----
        self.status.config(text="Thinking...")
        self.send_btn.config(state='disabled')
        threading.Thread(target=self.get_reply, args=(user_msg,), daemon=True).start()

    def get_reply(self, user_msg):
        reply = self.chat_agent.chat(user_msg)
        db_manager.log_conversation(user_msg, reply)
        self.root.after(0, self.display_message, "CANI", reply)
        self.root.after(0, self.update_status_bar)
        self.root.after(0, self.status.config, {"text": "Ready"})
        self.root.after(0, self.send_btn.config, {"state": "normal"})

    def schedule_reminder(self):
        if not self.reminder_running or self.next_reminder_index >= len(self.schedule_list):
            return
        reminder_text = f"⏰ Reminder: Drink {self.schedule_data['serving_ml']}ml of water now! " \
                        f"({self.next_reminder_index+1}/{len(self.schedule_list)})"
        self.display_message("💧", reminder_text)
        self.next_reminder_index += 1
        self.root.after(self.reminder_interval * 1000, self.schedule_reminder)

if __name__ == "__main__":
    root = tk.Tk()
    app = ChatApp(root)
    root.mainloop()