@echo off
setlocal
cd /d "%~dp0"

echo ============================================
echo   Group Addler - Construccion Windows EXE
echo ============================================
echo.

echo [1/3] Limpiando builds anteriores...
if exist "build" rmdir /s /q "build"
if exist "dist" rmdir /s /q "dist"
echo     Listo.
echo.

echo [2/3] Ejecutando PyInstaller...
uv run python build.py
echo.

echo [3/3] Verificando resultado...
if exist "dist\GroupAddler\GroupAddler.exe" (
    echo ============================================
    echo   BUILD COMPLETADO EXITOSAMENTE
    echo ============================================
    echo.
    echo   EXE: dist\GroupAddler\GroupAddler.exe
    echo.
    echo   Copia toda la carpeta "GroupAddler" a
    echo   la maquina destino.
    echo ============================================
) else (
    echo ERROR: No se encontro el exe en dist\
)

echo.
pause
