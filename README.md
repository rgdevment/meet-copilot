# Vision Copilot v9 - Guía de Usuario

Este asistente técnico utiliza inteligencia artificial y visión por computadora para capturar, traducir y resumir tus reuniones en tiempo real.

## Instalacion Rapida (Clean Setup)

1. **Clonar el repo y entrar a la carpeta.**
2. **Crear y activar el entorno aislado:**
   python -m venv .venv
   .\.venv\Scripts\activate
3. **Instalar dependencias desde el manifiesto:**
   pip install -r requirements.txt


## 1. Requisitos Previos
- **Python 3.11** instalado en Windows.
- **LM Studio** (opcional, para resúmenes con Llama 3).
- **Windows Live Captions** activo (disponible en Windows 11).

## 2. Configuración de Permisos y Entorno
Para evitar errores de seguridad al ejecutar scripts en Windows, sigue estos pasos en tu terminal PowerShell (como administrador):

1. **Habilitar ejecución de scripts:**
   Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser

2. **Crear el entorno virtual (VENV):**
   Ve a la carpeta del proyecto y ejecuta:
   python -m venv .venv

3. **Activar el entorno:**
   .\.venv\Scripts\activate
   (Sabrás que está activo porque verás "(.venv)" al inicio de la línea de comandos).

## 3. Instalación de Librerías
Con el entorno virtual activado, instala solo lo necesario:

pip install "numpy<2.0" easyocr opencv-python pyautogui deep-translator openai rich requests (o requirements.txt)

## 4. Configuración de Windows Live Captions
El script lee una zona específica de tu pantalla. Para que funcione correctamente:

1. **Activar Subtítulos:** Presiona `Win + Ctrl + L`.
2. **Posicionamiento:** Mueve la barra de subtítulos a la parte superior de la pantalla.
3. **Calibración:** El script está configurado para leer la zona:
   - X: 1230 a 2110
   - Y: 14 a 80
   (Asegúrate de que el texto de los subtítulos aparezca dentro de ese recuadro).

## 5. Ejecución del Copilot
Cada vez que vayas a iniciar una reunión:

1. **Abrir LM Studio:** Inicia el "Local Server" en el puerto 1234 si quieres resúmenes con IA.
2. **Activar VENV:** `.\.venv\Scripts\activate`
3. **Lanzar Script:** `python vision_copilot.py`

## 6. Archivos de Salida
El sistema genera automáticamente una carpeta llamada `meetings/` donde guarda:
- **Transcripción:** Historial línea por línea en texto plano (`.txt`).
- **Notas de IA:** Resúmenes técnicos estructurados en Markdown (`.md`).

## 7. Comandos Útiles
- **Detener el programa:** Presiona la tecla `q` sobre la ventana de "Vision Debug" o `Ctrl + C` en la terminal.
- **Verificar captura:** La ventana "Vision Debug" te permite ver exactamente qué está leyendo la IA en tiempo real.
