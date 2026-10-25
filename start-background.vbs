Set sh = CreateObject("WScript.Shell")
Set fs = CreateObject("Scripting.FileSystemObject")
sh.CurrentDirectory = fs.GetParentFolderName(WScript.ScriptFullName)
sh.Run "cmd /c start.bat", 0, False
