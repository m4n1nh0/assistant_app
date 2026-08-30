; Instalador do INTARQ AI Assistant para Windows (Inno Setup 6).
;
; Decisoes que valem registro:
;
; - Instalacao POR USUARIO (PrivilegesRequired=lowest). O app e um assistente
;   pessoal com atalho global e janela propria; nao precisa de nada em Program
;   Files. Instalar no perfil do usuario elimina o prompt de UAC, que e o maior
;   ponto de desistencia numa instalacao baixada da internet.
;
; - CloseApplications. O app fica residente com atalho global registrado;
;   sobrescrever DLL de um processo vivo falha no meio da instalacao.
;
; - WebView2 verificado, nao assumido. O componente de navegador embutido
;   depende do runtime Evergreen: presente por padrao no Windows 11, nem sempre
;   no Windows 10. Sem ele o app abre e quebra so quando o usuario usa a parte
;   que precisa dele - o pior momento para descobrir.
;
; Compilado por scripts/build_installer.ps1, que passa AppVersion e os caminhos.
; Os valores abaixo sao apenas defaults para compilar a mao.

#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif
#ifndef SourceDir
  #define SourceDir "..\interface\build\windows\x64\runner\Release"
#endif
#ifndef OutputDir
  #define OutputDir "..\dist"
#endif
#ifndef IconFile
  #define IconFile "..\interface\windows\runner\resources\app_icon.ico"
#endif
#ifndef LicenseFile
  #define LicenseFile "..\LICENSE"
#endif

#define AppName "INTARQ AI Assistant"
#define AppShortName "INTARQ"
#define AppPublisher "INTARQ"
#define AppExeName "assistant_app.exe"
#define AppUrl "https://github.com"

[Setup]
; Estavel entre versoes: e por ele que o Windows reconhece upgrade em vez de
; instalar uma segunda copia lado a lado.
AppId={{D894FD45-2A45-57F5-AE1E-4934524F4A8D}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
VersionInfoVersion={#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppUrl}
AppSupportURL={#AppUrl}
AppUpdatesURL={#AppUrl}

DefaultDirName={autopf}\{#AppShortName}
DefaultGroupName={#AppShortName}
DisableProgramGroupPage=yes
DisableDirPage=auto

PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog

OutputDir={#OutputDir}
OutputBaseFilename=INTARQ-Setup-{#AppVersion}
SetupIconFile={#IconFile}
UninstallDisplayIcon={app}\{#AppExeName}
UninstallDisplayName={#AppName}
LicenseFile={#LicenseFile}

Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.17763

; Fecha o app antes de sobrescrever os binarios, e reabre depois.
CloseApplications=yes
RestartApplications=yes

[Languages]
Name: "brazilianportuguese"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"
Name: "startup"; Description: "Iniciar o {#AppShortName} junto com o Windows"; GroupDescription: "Inicializacao:"; Flags: unchecked

[Files]
; Todo o conteudo do build de release: exe, DLLs dos plugins e a pasta data/
; com flutter_assets (onde vive assets/config/app_defaults.json).
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExeName}"
Name: "{group}\{cm:UninstallProgram,{#AppShortName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppShortName}"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon
Name: "{userstartup}\{#AppShortName}"; Filename: "{app}\{#AppExeName}"; Tasks: startup

[Run]
Filename: "{app}\{#AppExeName}"; Description: "{cm:LaunchProgram,{#AppShortName}}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Nao apaga dados do usuario (conversas, configuracao): desinstalar nao pode
; destruir o historico de quem so quer reinstalar.
Type: filesandordirs; Name: "{app}\data"

[Code]
const
  WebView2Key =
    'SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}';
  WebView2Bootstrapper = 'https://go.microsoft.com/fwlink/p/?LinkId=2124703';

var
  WebView2Missing: Boolean;

{ O runtime pode estar registrado em tres lugares: por maquina em 64 e 32 bits,
  e por usuario. Checar so um deles produz falso negativo e faz o instalador
  baixar de novo algo que ja existe. }
function WebView2Installed(): Boolean;
var
  Version: String;
begin
  Result :=
    (RegQueryStringValue(HKLM, 'SOFTWARE\WOW6432Node\' + WebView2Key, 'pv', Version) or
     RegQueryStringValue(HKLM, WebView2Key, 'pv', Version) or
     RegQueryStringValue(HKCU, WebView2Key, 'pv', Version))
    and (Version <> '') and (Version <> '0.0.0.0');
end;

function InitializeSetup(): Boolean;
begin
  WebView2Missing := not WebView2Installed();
  Result := True;
end;

procedure InstallWebView2();
var
  Page: TOutputProgressWizardPage;
  Downloader: TDownloadWizardPage;
  ResultCode: Integer;
  Target: String;
begin
  Target := ExpandConstant('{tmp}\MicrosoftEdgeWebview2Setup.exe');

  Downloader := CreateDownloadPage(
    'Componente adicional',
    'Baixando o runtime WebView2, necessario para o navegador embutido.',
    nil);
  Downloader.Clear;
  Downloader.Add(WebView2Bootstrapper, 'MicrosoftEdgeWebview2Setup.exe', '');
  Downloader.Show;
  try
    try
      Downloader.Download;
    except
      { Falha de rede nao aborta a instalacao: o app funciona sem WebView2,
        exceto na parte que usa navegador embutido. Melhor instalar e avisar do
        que recusar tudo. }
      MsgBox(
        'Nao foi possivel baixar o runtime WebView2.' + #13#10#13#10 +
        'O ' + '{#AppShortName}' + ' sera instalado, mas as telas que usam ' +
        'navegador embutido nao vao funcionar ate voce instalar o ' +
        '"Microsoft Edge WebView2 Runtime".',
        mbInformation, MB_OK);
      Exit;
    end;
  finally
    Downloader.Hide;
  end;

  Page := CreateOutputProgressPage('Componente adicional',
    'Instalando o runtime WebView2...');
  Page.SetText('Isso leva alguns instantes.', '');
  Page.Show;
  try
    Exec(Target, '/silent /install', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  finally
    Page.Hide;
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if (CurStep = ssPostInstall) and WebView2Missing then
    InstallWebView2();
end;
