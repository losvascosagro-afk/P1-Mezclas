@echo off
chcp 65001 > nul
title Laboratorio de Compatibilidad de Mezclas

echo.
echo  ╔══════════════════════════════════════════════╗
echo  ║   Laboratorio de Compatibilidad de Mezclas   ║
echo  ║   Iniciando servidor...                       ║
echo  ╚══════════════════════════════════════════════╝
echo.
echo  Abriendo navegador en http://localhost:5000
echo  Para cerrar la app, presiona Ctrl+C en esta ventana.
echo.

:: Abrir el navegador después de 2 segundos
start "" /b cmd /c "timeout /t 2 /nobreak > nul && start http://localhost:5000"

:: Iniciar Flask
"C:\Program Files\QGIS 3.40.10\apps\Python312\python.exe" "%~dp0start.py"

pause
