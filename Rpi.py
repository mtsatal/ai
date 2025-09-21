import os
import sys
import time
import threading
import queue
import json
import subprocess
import tkinter as tk
from datetime import datetime
from typing import Dict, List
import pyttsx3
from langdetect import detect
from vosk import Model, KaldiRecognizer
import sounddevice as sd
from PIL import Image, ImageTk
import cohere
from groq import Groq
import serial
from functools import partial
class Config:
    INPUT_LANGUAGES = ["en", "hi"]
    DEFAULT_LANGUAGE = "en"
    SAMPLE_RATE = 16000
    COHERE_MODEL = "command-r-plus-08-2024"
    GROQ_MODEL = "llama3-8b-8192"
    VOICE_RATE = 150
    MAX_LLM_HISTORY = 5
    NUMBER_OF_SEARCH_RESULTS = 3
COHERE_API_KEY='key'
GROQ_API_KEY='key'
co_client = cohere.ClientV2(api_key=COHERE_API_KEY)
groq_client = Groq(api_key=GROQ_API_KEY)
MODEL_PATHS = {
    "en": "models/english",
    "hi": "models/hindi"
}

vosk_models = {
    lang: Model(path)
    for lang, path in MODEL_PATHS.items()
}
LANG_VOICE_MAP = {
    'en': 'english',
    'hi': 'hindi',
}

def speak(text: str):
    try:
        lang = detect(text)
    except:
        lang = Config.DEFAULT_LANGUAGE

    engine = pyttsx3.init()
    voices = engine.getProperty('voices')
    selected_voice = None

    for voice in voices:
        if LANG_VOICE_MAP.get(lang, '').lower() in voice.name.lower():
            selected_voice = voice.id
            break

    if selected_voice:
        engine.setProperty('voice', selected_voice)

    engine.setProperty('rate', Config.VOICE_RATE)
    engine.say(text)
    engine.runAndWait()
q = queue.Queue()

def audio_callback(indata, frames, time, status):
    if status:
        print(status, file=sys.stderr)
    q.put(bytes(indata))

def recognize_speech(language="en") -> str:
    model = vosk_models.get(language, vosk_models[Config.DEFAULT_LANGUAGE])
    rec = KaldiRecognizer(model, Config.SAMPLE_RATE)
    rec.SetWords(True)

    print(f"🎤 Listening ({language})...")

    with sd.RawInputStream(samplerate=Config.SAMPLE_RATE, blocksize=8000, dtype='int16',
                           channels=1, callback=audio_callback):
        result_text = ""
        while True:
            data = q.get()
            if rec.AcceptWaveform(data):
                result = rec.Result()
                result_json = json.loads(result)
                result_text = result_json.get('text', '')
                break
    return result_text.strip()

def SpeechRecognition():
    print("🗣️ Say 'Hindi' to speak in Hindi, otherwise continue in English")
    command = recognize_speech("en").lower()
    if "hindi" in command:
        return recognize_speech("hi")
    else:
        return recognize_speech("en")

def init_serial(port='/dev/ttyS0', baudrate=9600):
    try:
        ser = serial.Serial(port, baudrate, timeout=1)
        time.sleep(2)
        print("✅ Connected to Arduino")
        return ser
    except Exception as e:
        print("❌ Arduino not connected:", e)
        return None

def send_movement_command(ser, command: str):
    if ser:
        ser.write(command.encode())
        print(f"📤 Sent to Arduino: {command}")
def dmm(query: str) -> List[str]:
    q = query.lower()
    if any(word in q for word in ["forward", "backward", "left", "right", "stop"]):
        return [f"move {q}"]
    elif any(word in q for word in ["weather", "news", "today", "temperature"]):
        return [f"realtime {q}"]
    elif any(word in q for word in ["bye", "exit", "quit"]):
        return ["exit"]
    else:
        return [f"general {q}"]
    
def system_prompt_general():
    return {"role": "system", "content": "You are Jarvis, an intelligent assistant."}

def get_datetime_dict():
    return {"role": "system", "content": f"DateTime: {datetime.now()}"}

def google_search_text(query: str) -> str:
    try:
        from googlesearch import search
        results = list(search(query, num_results=Config.NUMBER_OF_SEARCH_RESULTS))
        return "\n".join(results)
    except Exception as e:
        return f"Search failed: {e}"

async def cohere_chat(messages: List[Dict[str, str]]) -> str:
    resp = co_client.chat(model=Config.COHERE_MODEL, messages=messages)
    return resp.message.content[0].text

async def groq_chat(messages: List[Dict[str, str]]) -> str:
    resp = groq_client.chat.completions.create(model=Config.GROQ_MODEL, messages=messages)
    return resp.choices[0].message.content

async def general_chat(prompt: str, history: List[Dict[str, str]]) -> str:
    messages = [system_prompt_general(), get_datetime_dict()] + history[-Config.MAX_LLM_HISTORY*2:]
    messages.append({"role": "user", "content": prompt})
    return await cohere_chat(messages)

async def real_time_chat(prompt: str, history: List[Dict[str, str]]) -> str:
    messages = [system_prompt_general(), get_datetime_dict()]
    messages.append({"role": "system", "content": google_search_text(prompt)})
    messages += history[-Config.MAX_LLM_HISTORY*2:]
    messages.append({"role": "user", "content": prompt})
    return await groq_chat(messages)


def launch_gui(ser, face_queue):
    root = tk.Tk()
    root.title("Jarvis Control Panel")
    root.geometry("480x320")

    face_images = {}
    expressions = ['neutral', 'listening', 'thinking', 'speaking']
    for expr in expressions:
        try:
            img = Image.open(f"face_{expr}.png").resize((150, 150))
            face_images[expr] = ImageTk.PhotoImage(img)
        except Exception as e:
            print(f"Error loading face_{expr}.png:", e)
    face_label = tk.Label(root, image=face_images.get("neutral"))
    face_label.pack()

    def update_face():
        try:
            while not face_queue.empty():
                expr = face_queue.get_nowait()
                if expr in face_images:
                    face_label.config(image=face_images[expr])
        except:
            pass
        root.after(100, update_face)

    update_face()

    f = tk.Frame(root)
    f.pack()

    tk.Button(f, text="Forward", command=lambda: send_movement_command(ser, 'F')).grid(row=0, column=1)
    tk.Button(f, text="Left", command=lambda: send_movement_command(ser, 'L')).grid(row=1, column=0)
    tk.Button(f, text="Stop", command=lambda: send_movement_command(ser, 'S')).grid(row=1, column=1)
    tk.Button(f, text="Right", command=lambda: send_movement_command(ser, 'R')).grid(row=1, column=2)
    tk.Button(f, text="Backward", command=lambda: send_movement_command(ser, 'B')).grid(row=2, column=1)

    root.mainloop()
    
import asyncio
from queue import Queue

async def main():
    ser = init_serial()
    face_queue = Queue()
    threading.Thread(target=launch_gui, args=(ser, face_queue), daemon=True).start()

    history = []

    print("✅ Jarvis is ready...")

    while True:
        face_queue.put("listening")
        query = SpeechRecognition()
        print("🗣️ You:", query)
        face_queue.put("thinking")
        history.append({"role": "user", "content": query})
        actions = dmm(query)

        if any(a.startswith("move") for a in actions):
            if "forward" in query: send_movement_command(ser, 'F')
            elif "backward" in query: send_movement_command(ser, 'B')
            elif "left" in query: send_movement_command(ser, 'L')
            elif "right" in query: send_movement_command(ser, 'R')
            elif "stop" in query: send_movement_command(ser, 'S')

        if any(a.startswith("realtime") for a in actions):
            response = await real_time_chat(query, history)
        elif any(a.startswith("general") for a in actions):
            response = await general_chat(query, history)
        else:
            response = "Goodbye!"
            face_queue.put("speaking")
            speak(response)
            face_queue.put("neutral")
            break

        print("🤖 Jarvis:", response)
        face_queue.put("speaking")
        speak(response)
        face_queue.put("neutral")
        history.append({"role": "assistant", "content": response})

if __name__ == "__main__":
    asyncio.run(main())
