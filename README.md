# Meet Copilot Pro - AI Meeting Architect (GUI Edition)

Aplicación de escritorio para orquestar reuniones inteligentes en Windows. Utiliza automatización de UI para capturar subtítulos de Microsoft Teams, procesarlos con Inteligencia Artificial Local (LM Studio) y generar documentación técnica en tiempo real.

> **NOTA IMPORTANTE:** Esta versión (v2.0) soporta **EXCLUSIVAMENTE MICROSOFT TEAMS** como fuente de audio/texto.

## Características Técnicas

* **Interfaz:** GUI Nativa (Tkinter) con Modo Oscuro (VS Code Theme). Estabilidad total sin parpadeos.
* **Captura:** `uiautomation` sobre el DOM de Teams (Scraping de Accessibility Tree).
* **IA:** Conexión a LM Studio vía API compatible con OpenAI (Localhost).
* **Procesamiento:** Lógica LIFO (Last In First Out) para visualización y colas FIFO para procesamiento de archivos.
* **Traducción:** Instantánea en hilo dedicado.
* **Salida:** Archivos Markdown (.md) para Raw Data y Bitácora Técnica.

## Requisitos Previos

1.  **Sistema Operativo:** Windows 10 o 11 (Obligatorio para `uiautomation`).
2.  **Python:** Versión 3.10 o superior.
3.  **LM Studio:** Instalado y ejecutando un servidor local.
4.  **Microsoft Teams:** Aplicación de escritorio (Nueva o Clásica) con **Subtítulos en Vivo activados** durante la reunión.

## Estructura del Proyecto

* `main_meeting_ai.py`: Entry point. Gestiona la GUI, hilos de IA y orquestación.
* `teams_stream_capture.py`: Módulo de bajo nivel para leer la memoria de la ventana de Teams.
* `realtime_translator.py`: Servicio de traducción (Google/DeepL wrapper).
* `reuniones_logs/`: Directorio de salida automática.

## Instalación

1.  Clona el repositorio:
    ```bash
    git clone <tu-repo>
    cd meet-copilot
    ```

2.  Crea y activa el entorno virtual:
    ```bash
    python -m venv .venv
    .venv\Scripts\activate
    ```

3.  Instala las dependencias:
    Usa el archivo `requirements.txt` y ejecuta `pip install -r requirements.txt`:

## Configuración de LM Studio (Critico)

Para que el Tech Lead funcione:
1.  Carga un modelo ligero pero capaz (ej: `Llama-3-8B-Instruct-v2` o `Mistral-Nemo`).
2.  Ve a la pestaña **Developer/Server** (icono `<->`).
3.  **Context Length:** Ajústalo a `8192` (necesario para el resumen final).
4.  **Port:** `1234` (default).
5.  Presiona **Start Server**.

## Ejecución

### Método 1: Consola
```bash
python main_meeting_ai.py

## Ejecucion Rapida (Lanzador de Escritorio)



Para ejecutar el asistente con un doble clic desde tu escritorio sin abrir consolas manualmente, crea un archivo .bat:



1. Abre el Bloc de Notas.

2. Pega el siguiente codigo:



   @echo off

   title Meet Copilot Pro Launcher



   :: Ajusta la carpeta si clonaste el repo en otro lugar

   cd /d "%USERPROFILE%\meet-copilot"



   :: Activa el entorno y lanza la app

   call .venv\Scripts\activate

   cls

   echo  ================================================

   echo    MEET COPILOT PRO - ORQUESTADOR IA

   echo  ================================================

   echo.

   python main_meeting_ai.py



   echo.

   echo El programa se ha cerrado.

   pause



3. Guardalo en tu Escritorio con el nombre Iniciar_Copilot.bat.

4. Listo! Solo haz doble clic para iniciar la sesion.

