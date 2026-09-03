' Sobe o servidor (sem mostrar janela de terminal) e abre o app numa janela
' própria do Edge (sem barra de endereço/abas, feito "--app"), como se fosse
' um programa instalado de verdade. Dê 2 cliques neste arquivo pra usar.

Set fso = CreateObject("Scripting.FileSystemObject")
Set WshShell = CreateObject("WScript.Shell")

scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
WshShell.CurrentDirectory = scriptDir & "\app"

' Acha o pythonw.exe instalado — usar caminho completo em vez de "pythonw" puro,
' porque WshShell.Run nem sempre resolve o PATH do jeito que um terminal normal
' resolveria (pode cair no stub do Windows Store e falhar em silêncio).
pythonwPaths = Array( _
  WshShell.ExpandEnvironmentStrings("%LOCALAPPDATA%") & "\Programs\Python\Python314\pythonw.exe", _
  WshShell.ExpandEnvironmentStrings("%LOCALAPPDATA%") & "\Python\bin\pythonw.exe" _
)

pythonwEncontrado = ""
For Each caminho In pythonwPaths
  If fso.FileExists(caminho) Then
    pythonwEncontrado = caminho
    Exit For
  End If
Next

If pythonwEncontrado = "" Then
  MsgBox "Não encontrei o pythonw.exe instalado. Abra o app manualmente: 'cd app' e 'python server.py'.", 16, "Controle de Periódicos"
  WScript.Quit
End If

' Sobe o servidor Flask em segundo plano, sem janela (pythonw = sem console)
WshShell.Run """" & pythonwEncontrado & """ server.py", 0, False

' Dá um tempinho pro servidor subir antes de abrir o navegador
WScript.Sleep 3000

' Acha o Edge instalado (32 ou 64 bits) e abre em modo "app"
edgePaths = Array( _
  "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe", _
  "C:\Program Files\Microsoft\Edge\Application\msedge.exe" _
)

edgeEncontrado = ""
For Each caminho In edgePaths
  If fso.FileExists(caminho) Then
    edgeEncontrado = caminho
    Exit For
  End If
Next

If edgeEncontrado <> "" Then
  WshShell.Run """" & edgeEncontrado & """ --app=http://localhost:8501 --window-size=1320,880", 1, False
Else
  ' Edge não encontrado nesse caminho padrão — abre no navegador comum
  WshShell.Run "http://localhost:8501", 1, False
End If
