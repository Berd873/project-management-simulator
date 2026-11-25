const path=require('node:path');
const fs=require('node:fs');
const {spawn}=require('node:child_process');
const {chromium}=require(path.resolve('frontend/node_modules/@playwright/test'));
(async()=>{
 const root=process.cwd(),out=path.join(root,'output/real-ticketing');
 const manifest=JSON.parse(fs.readFileSync(path.join(out,'manifest.json'),'utf8'));
 if(!manifest.success)throw new Error('Completed real run required');
 const python=path.resolve('.venv/Scripts/python.exe');
 const server=spawn(python,['-m','app.serve'],{cwd:root,windowsHide:true,env:{...process.env,APP_PORT:'8769',PYTHONPATH:path.join(root,'backend'),DATABASE_URL:'sqlite:///'+path.join(out,'demo.db').replaceAll('\\','/'),TEMP:path.join(out,'../temp'),TMP:path.join(out,'../temp')},stdio:'ignore'});
 let browser;
 try{
  for(let i=0;i<60;i++){try{if((await fetch('http://127.0.0.1:8769/api/v1/health')).ok)break;}catch{} await new Promise(r=>setTimeout(r,500));}
  browser=await chromium.launch({channel:'msedge',headless:true});
  const page=await browser.newPage({viewport:{width:1440,height:1100},deviceScaleFactor:1});
  await page.goto('http://127.0.0.1:8769/?run='+manifest.run_id);
  await page.locator('.role-card').first().waitFor();
  await page.getByRole('status').filter({hasText:'已完成验收'}).waitFor();
  await page.screenshot({path:path.join(out,'real-overview.png'),fullPage:false});
  await page.getByRole('button',{name:/变更与审批/}).click();
  await page.locator('.baseline-row').nth(2).waitFor();
  await page.screenshot({path:path.join(out,'real-changes.png'),fullPage:true});
  console.log('PASS: real-run UI loaded, three baselines visible, screenshots saved');
 }finally{if(browser)await browser.close();server.kill();}
})().catch(e=>{console.error(e.message);process.exitCode=1});
