@echo off
:: Título de la ventana
title Meet Copilot Pro Launcher

:: 1. Ir a la carpeta del proyecto (asegurando el cambio de disco con /d)
cd /d "C:\Users\mhida\meet-copilot"

:: 2. Activar el entorno virtual
call .venv\Scripts\activate

:: 3. Mostrar mensaje de estado
echo.
echo ==========================================
echo   INICIANDO MEET COPILOT PRO...
echo ==========================================
echo.

:: 4. Ejecutar el script principal
python main_meeting_ai.py

:: 5. Pausa final (para que si hay un error, la ventana no se cierre y puedas leerlo)
echo.
echo El programa se ha cerrado.
pause