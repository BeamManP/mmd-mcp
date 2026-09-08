@echo off
setlocal
set "VSWHERE=%ProgramFiles(x86)%\Microsoft Visual Studio\Installer\vswhere.exe"
if not exist "%VSWHERE%" (
  echo Install Visual Studio Build Tools with Desktop development with C++.
  exit /b 1
)
for /f "usebackq delims=" %%i in (`"%VSWHERE%" -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath`) do set "MMD_BUILD_VS=%%i"
if not defined MMD_BUILD_VS exit /b 1
call "%MMD_BUILD_VS%\VC\Auxiliary\Build\vcvars64.bat" >nul
if errorlevel 1 exit /b 1
pushd "%~dp0.."
if not exist "src\mmd_mcp\_native" mkdir "src\mmd_mcp\_native"
if not exist "local\native-build" mkdir "local\native-build"
cl /nologo /std:c++17 /O2 /MT /LD /W4 /WX /DUNICODE /D_UNICODE /Fo"local\native-build\selection_bridge.obj" /Fe"src\mmd_mcp\_native\mmd_selection.dll" "native\selection_bridge.cpp" /link user32.lib /IMPLIB:"local\native-build\mmd_selection.lib"
set "MMD_BUILD_RESULT=%ERRORLEVEL%"
popd
exit /b %MMD_BUILD_RESULT%
