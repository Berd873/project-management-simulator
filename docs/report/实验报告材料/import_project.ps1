$ErrorActionPreference = 'Stop'
$source = Join-Path $PSScriptRoot '图书管理项目计划.xml'
$target = Join-Path $PSScriptRoot '图书管理项目计划.mpp'
$app = New-Object -ComObject MSProject.Application
try {
    $app.Visible = $false
    $app.FileOpenEx($source)
    $project = $app.ActiveProject
    if ($null -eq $project) { throw 'Project did not open the imported plan' }
    $tasks = @($project.Tasks | Where-Object { $_ -ne $null })
    Write-Output "Project=$($project.Name); Tasks=$($tasks.Count)"
    foreach ($task in $tasks) {
        Write-Output "ID=$($task.ID); WBS=$($task.WBS); Name=$($task.Name); Predecessors=$($task.Predecessors)"
    }
    $app.FileSaveAs($target)
    Write-Output "Saved=$target"
} finally {
    $app.Quit()
}
