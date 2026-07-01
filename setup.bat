@echo off
echo.
echo   ╔══════════════════════════════════╗
echo   ║      Assistente — Setup     ║
echo   ╚══════════════════════════════════╝
echo.

where flutter >nul 2>nul
if %ERRORLEVEL% NEQ 0 (
    echo Flutter nao encontrado!
    echo Instale em: https://flutter.dev/docs/get-started/install
    echo E adicione ao PATH antes de executar este script.
    pause
    exit /b 1
)

echo [OK] Flutter encontrado
echo.

flutter config --enable-windows-desktop
echo.

echo Instalando dependencias...
flutter pub get
echo.

echo Iniciando assistente...
flutter run -d windows

pause
