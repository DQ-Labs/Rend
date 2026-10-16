; Inno Setup script for Rend.
;
; Compile via installer/build_installer.py, which reads config.py (the
; single source of truth for the app's identity) and passes every value
; below as a /D preprocessor define. Nothing identity-related is
; hardcoded here.
;
; Requires Inno Setup 6.3+ (for the x64compatible architecture names).

#ifndef AppVersion
  #error Compile via installer/build_installer.py so defines come from config.py
#endif

[Setup]
; Stable AppId (the bundle id from config.py) so upgrades replace the
; existing install and Apps & Features shows a single entry.
AppId={#AppId}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppURL}
AppSupportURL={#AppSupportURL}
AppUpdatesURL={#AppUpdatesURL}
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
LicenseFile=..\LICENSE
OutputDir=..\dist\installer
OutputBaseFilename={#AppName}-Setup-{#AppVersion}
SetupIconFile=..\rend.ico
UninstallDisplayIcon={app}\{#AppName}.exe
UninstallDisplayName={#AppName}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

; The app is a PyInstaller one-dir build: {app}\Rend.exe is the launcher and
; {app}\_internal holds everything it loads (Python runtime, torch, ffmpeg,
; assets, demucs). Up to 1.4.1 the app was a single one-file Rend.exe in the
; same place, so an upgrade overwrites that file in place under the same name
; and existing Start-menu/desktop shortcuts keep working.

[InstallDelete]
; Clear the previous build's runtime before copying the new one. Installing
; over an older one-dir build would otherwise leave DLLs and modules that the
; new build no longer ships sitting next to the ones it does, where Python or
; Windows' DLL search can pick them up.
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "..\dist\{#AppName}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[UninstallDelete]
; Inno removes every file it installed, but not anything created next to them
; at runtime. Rend writes its logs and model weights to %LOCALAPPDATA%\Rend, never
; here; this is the belt-and-braces guarantee that uninstall leaves no runtime
; folder behind regardless.
Type: filesandordirs; Name: "{app}\_internal"
Type: dirifempty; Name: "{app}"

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppName}.exe"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppName}.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppName}.exe"; Description: "{cm:LaunchProgram,{#StringChange(AppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent
