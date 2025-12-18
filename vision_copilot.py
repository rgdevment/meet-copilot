import easyocr
import pyautogui
import numpy as np
import cv2
from deep_translator import GoogleTranslator
from openai import OpenAI
from rich.console import Console
from rich.panel import Panel
from rich.layout import Layout
from rich.live import Live
from rich.text import Text
import time
import os
import difflib
import threading
import requests
from datetime import datetime

# --- ⚙️ CONFIGURACIÓN ---
REGION = (1230, 14, 880, 66)
MAX_HISTORY_VIEW = 20
MAX_AI_HISTORY = 8
SUMMARY_INTERVAL = 30
LM_STUDIO_URL = "http://localhost:1234/v1"

# --- PERSISTENCIA ---
os.makedirs("meetings", exist_ok=True)
timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
FILE_TRANSCRIPT = f"meetings/transcript_{timestamp}.txt"
FILE_NOTES = f"meetings/notes_ai_{timestamp}.md"

def save_transcript(text):
    t = datetime.now().strftime("%H:%M:%S")
    with open(FILE_TRANSCRIPT, "a", encoding="utf-8") as f:
        f.write(f"[{t}] {text}\n")

def save_ai_note(text):
    with open(FILE_NOTES, "a", encoding="utf-8") as f:
        f.write(f"\n{text}\n")

# --- INICIO ---
def clear(): os.system('cls')
clear()
console = Console()

# Chequeo IA
AI_ENABLED = False
try:
    requests.get(f"{LM_STUDIO_URL}/models", timeout=1)
    AI_ENABLED = True
    console.print(f"[bold green]✅ IA Detectada (Llama 3) -> Input: RAW ENGLISH (OCR)[/bold green]")
except:
    console.print(f"[dim]⚠️ IA No detectada -> Solo transcripción.[/dim]")

console.print("[yellow]⚡ Cargando (Raw Source + High Context)...[/yellow]")

reader = easyocr.Reader(['en'], gpu=False, verbose=False)
translator = GoogleTranslator(source='auto', target='es')
client = OpenAI(base_url=LM_STUDIO_URL, api_key="lm-studio") if AI_ENABLED else None

# Variables Globales
history_log = []
ai_summary_log = []
recent_block_for_ai = [] # Buffer crudo (ahora en Inglés)
last_english_text = ""
previous_ai_context = "Inicio de la reunión."

# --- CEREBRO IA (Tech Lead Bilingüe) ---
def ai_worker():
    global previous_ai_context, recent_block_for_ai, ai_summary_log
    while True:
        time.sleep(SUMMARY_INTERVAL)

        # Necesitamos más datos ahora que el intervalo es largo
        if len(recent_block_for_ai) < 4: continue

        # Este bloque ahora está en INGLÉS (OCR Raw)
        block_text = " ".join(recent_block_for_ai)
        recent_block_for_ai = []
        current_time = datetime.now().strftime("%H:%M")

        try:
            # PROMPT: Inglés Input -> Español Output
            prompt_system = (
                "Eres un Product Manager. Tu tarea es generar minutas de reuniones."
                "Recibirás transcripciones sin procesar (OCR) en INGLÉS."
                "Tu objetivo: Entender resumir por parrafos y transcribir en un lenguaje claro y tecnico en español."
                "Ignora errores de OCR o texto irrelevante."
            )

            prompt_user = (
                f"Contexto anterior: {previous_ai_context}\n"
                f"Nuevo segmento (Inglés OCR): {block_text}\n\n"
                "Resumen técnico en Español:"
            )

            response = client.chat.completions.create(
                model="local-model",
                messages=[
                    {"role": "system", "content": prompt_system},
                    {"role": "user", "content": prompt_user}
                ],
                temperature=0.2,
                max_tokens=500
            )

            new_note = response.choices[0].message.content.strip()

            formatted_entry = f"### [{current_time}] Hito\n{new_note}"
            save_ai_note(formatted_entry)
            previous_ai_context = new_note

            ai_summary_log.insert(0, f"[{current_time}] {new_note}")
            if len(ai_summary_log) > MAX_AI_HISTORY:
                ai_summary_log.pop()

        except: pass

if AI_ENABLED:
    t_ai = threading.Thread(target=ai_worker, daemon=True)
    t_ai.start()

# --- LAYOUT ---
layout = Layout()
if AI_ENABLED:
    layout.split_row(Layout(name="stream", ratio=5), Layout(name="summary", ratio=5))
    layout["stream"].split_column(Layout(name="english", size=3), Layout(name="spanish", ratio=1))
else:
    layout.split_column(Layout(name="english", size=3), Layout(name="spanish", ratio=1))

def is_continuation(old_text, new_text):
    if not old_text or not new_text: return False
    if old_text.lower() in new_text.lower(): return True
    return difflib.SequenceMatcher(None, old_text, new_text).ratio() > 0.6

console.print("[bold green]🔴 REC: Grabando (Input IA: Raw English)...[/bold green]")

with Live(layout, refresh_per_second=4, console=console) as live:
    while True:
        try:
            # 1. OCR
            screenshot = pyautogui.screenshot(region=REGION)
            frame = np.array(screenshot)
            result = reader.readtext(frame, detail=0, paragraph=True)
            current_english = " ".join(result).strip()

            # 2. Procesamiento
            if len(current_english) > 5 and current_english != last_english_text:
                if current_english in last_english_text and len(current_english) < len(last_english_text):
                    continue

                try:
                    # A. Traducción para el Usuario (Google - Rápido)
                    es_trad = translator.translate(current_english)

                    # Gestión Historial Visual
                    updated_existing = False
                    if history_log:
                        if is_continuation(history_log[0], es_trad):
                            history_log[0] = es_trad
                            updated_existing = True
                        else:
                            history_log.insert(0, es_trad)
                    else:
                        history_log.insert(0, es_trad)

                    if not updated_existing:
                        save_transcript(es_trad) # Guardamos lo que tú ves

                        # B. Input para la IA (CAMBIO CLAVE: RAW ENGLISH)
                        if AI_ENABLED:
                            # Pasamos el inglés original. Llama 3 sabrá qué hacer.
                            recent_block_for_ai.append(current_english)

                    if len(history_log) > MAX_HISTORY_VIEW: history_log.pop()
                    last_english_text = current_english
                except: pass

            # 3. Render
            history_text = Text()
            for i, line in enumerate(history_log):
                if i == 0: history_text.append(f"➤ {line}\n", style="bold green")
                else: history_text.append(f"  {line}\n", style="dim white")

            ai_text = Text()
            if AI_ENABLED:
                for entry in ai_summary_log:
                    parts = entry.split("] ", 1)
                    if len(parts) == 2:
                        ai_text.append(f"{parts[0]}] ", style="bold yellow")
                        ai_text.append(f"{parts[1]}\n\n", style="white")
                    else:
                        ai_text.append(f"{entry}\n\n")

            if AI_ENABLED:
                layout["stream"]["english"].update(Panel(f"[cyan]{current_english}[/cyan]", title="🇬🇧 Live (OCR)"))
                layout["stream"]["spanish"].update(Panel(history_text, title="🇨🇱 Traducción Rápida"))
                layout["summary"].update(Panel(ai_text, title="🧠 Minuta Técnica (Source: English)"))
            else:
                layout["english"].update(Panel(f"[cyan]{current_english}[/cyan]", title="🇬🇧 Live"))
                layout["spanish"].update(Panel(history_text, title="🇨🇱 Historial"))

            if cv2.waitKey(100) & 0xFF == ord('q'): break
        except Exception: continue

cv2.destroyAllWindows()
