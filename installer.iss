; Inno Setup script (free tool: https://jrsoftware.org/isinfo.php)
; 1. Run build_exe.bat first so dist\DeviceLoans.exe exists.
; 2. Open this file in Inno Setup and press Build > Compile (or F9).
; 3. Your installer appears in the Output folder as DeviceLoans-Setup.exe.

[Setup]
AppName=Device Loans
AppVersion=1.0
AppPublisher=Touqeer
DefaultDirName={autopf}\Device Loans
DefaultGroupName=Device Loans
OutputBaseFilename=DeviceLoans-Setup
Compression=lzma
SolidCompression=yes
; installs for the current user only, so no admin rights are needed
PrivilegesRequired=lowest
DisableProgramGroupPage=yes
UninstallDisplayName=Device Loans

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; Flags: unchecked

[Files]
Source: "dist\DeviceLoans.exe"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\Device Loans"; Filename: "{app}\DeviceLoans.exe"
Name: "{autodesktop}\Device Loans"; Filename: "{app}\DeviceLoans.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\DeviceLoans.exe"; Description: "Start Device Loans now"; Flags: nowait postinstall skipifsilent
