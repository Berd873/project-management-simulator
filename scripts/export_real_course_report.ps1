$ErrorActionPreference='Stop'
$taskRoot=Split-Path -Parent $PSScriptRoot
$taskReport=Join-Path $taskRoot 'docs\report\软件项目管理实验报告_方宇鹄小组_真实API双变更版.docx'
$taskReport=(Resolve-Path -LiteralPath $taskReport).Path
$taskPdf=[IO.Path]::ChangeExtension($taskReport,'.pdf')
$taskWord=New-Object -ComObject Word.Application
$taskWord.Visible=$false
$taskWord.DisplayAlerts=0
$taskWord.AutomationSecurity=3
$taskDoc=$null
try {
 $taskDoc=$taskWord.Documents.Open($taskReport,$false,$false)
 $taskDoc.Repaginate()
 foreach($taskToc in $taskDoc.TablesOfContents){$taskToc.Update()}
 $taskDoc.Repaginate()
 foreach($taskToc in $taskDoc.TablesOfContents){$taskToc.UpdatePageNumbers()}
 $taskDoc.Save()
 $taskDoc.ExportAsFixedFormat($taskPdf,17)
 Write-Output ('Pages: '+$taskDoc.ComputeStatistics(2))
 Write-Output $taskPdf
} finally {
 if($null -ne $taskDoc){$taskDoc.Close(0);[Runtime.InteropServices.Marshal]::FinalReleaseComObject($taskDoc)|Out-Null}
 $taskWord.Quit();[Runtime.InteropServices.Marshal]::FinalReleaseComObject($taskWord)|Out-Null
}
