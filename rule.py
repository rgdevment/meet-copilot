import pyautogui
import time
import os

def clear(): os.system('cls')

print("📏 MODO CALIBRACIÓN")
print("Mueve el mouse a la zona de subtítulos...")
print("Presiona Ctrl+C para salir.")

try:
    while True:
        x, y = pyautogui.position()
        # Imprimimos bonito para que no spamee
        print(f"\r📍 Coordenadas Mouse: X={x} Y={y}    ", end="")
        time.sleep(0.1)
except KeyboardInterrupt:
    print("\n✅ Listo.")
