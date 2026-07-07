# Business AI OS Installer
$Root = "C:\BusinessAIOS"

Write-Host "Business AI OS Installer"

# Remove existing folders
0..9 | ForEach-Object {
    $name = "{0:D2}_" -f $_
}
$targets = @(
"00_Company","01_AI_CEO","02_AI_Employees","03_Tools",
"04_Projects","05_Prompts","06_Config","07_Logs","08_Tests","09_Runtime"
)
foreach($t in $targets){
    $p = Join-Path $Root $t
    if(Test-Path $p){ Remove-Item $p -Recurse -Force }
}

# Root folders
foreach($t in $targets){
    New-Item -ItemType Directory -Force -Path (Join-Path $Root $t) | Out-Null
}

# Subfolders
$map = @{
"00_Company"=@("01_Constitution","02_SOP","03_Organization","04_Company_Assets","05_Operating_Information","06_Approval_System","07_Templates","08_Standards","09_Policies");
"01_AI_CEO"=@("01_Instructions","02_Memory","03_Decision","04_Reports","05_Approvals","06_Planning","07_Strategy","08_Runtime","09_History");
"02_AI_Employees"=@("01_Automation_AI","02_Marketing_AI","03_Product_AI","04_Finance_AI","05_Government_AI","06_Customer_AI","07_Content_AI","08_Development_AI","09_Temporary_AI");
"03_Tools"=@("01_Zapier","02_Google_Drive","03_Google_Docs","04_Google_Sheets","05_Gmail","06_Calendar","07_Forms","08_MCP","09_API");
"04_Projects"=@("01_Active","02_Planning","03_Completed","04_On_Hold","05_Archive","06_Templates","07_Resources","08_Reports","09_Backup");
"05_Prompts"=@("01_CEO","02_Employees","03_Zapier","04_Marketing","05_Product","06_Government","07_Finance","08_Customer","09_Shared");
"06_Config"=@("01_OpenAI","02_Zapier","03_Google","04_MCP","05_API_Keys","06_Environment","07_Security","08_Settings","09_Backup");
"07_Logs"=@("01_CEO","02_Employees","03_Zapier","04_System","05_Error","06_Runtime","07_Audit","08_History","09_Backup");
"08_Tests"=@("01_CEO","02_Employees","03_Zapier","04_Google","05_Gmail","06_MCP","07_Integration","08_System","09_Regression");
"09_Runtime"=@("01_CEO","02_Employees","03_Workflows","04_Queue","05_Tasks","06_Scheduler","07_Memory","08_Cache","09_Temp")
}

foreach($k in $map.Keys){
 foreach($s in $map[$k]){
   New-Item -ItemType Directory -Force -Path (Join-Path $Root "$k\$s") | Out-Null
 }
}

# Standard markdown files
$files=@{
"00_Company\01_Constitution\Constitution.md"="# Business AI OS Constitution";
"00_Company\02_SOP\SOP_Master.md"="# Business AI OS SOP Master";
"00_Company\03_Organization\Organization.md"="# Business AI OS Organization";
"00_Company\04_Company_Assets\Company_Assets.md"="# Business AI OS Company Assets";
"00_Company\05_Operating_Information\Operating_Information.md"="# Business AI OS Operating Information";
"00_Company\06_Approval_System\Approval_System.md"="# Business AI OS Approval System";
"00_Company\07_Templates\Templates.md"="# Business AI OS Templates";
"00_Company\08_Standards\Standards.md"="# Business AI OS Standards";
"00_Company\09_Policies\Policies.md"="# Business AI OS Policies";
}

foreach($f in $files.Keys){
 $path=Join-Path $Root $f
 $files[$f] | Set-Content -Encoding UTF8 -Path $path
}

Write-Host "Business AI OS installation complete."
