/* Optional development regression; requires Playwright and an installed browser. */
const {chromium}=require('playwright');
const fs=require('fs'), path=require('path'), assert=require('assert');
(async()=>{
  const [url,out,executablePath]=process.argv.slice(2);
  const browser=await chromium.launch({headless:true,...(executablePath?{executablePath}:{}),timeout:20000});
  const page=await browser.newPage({viewport:{width:1440,height:1080},deviceScaleFactor:1});
  const errors=[],checks=[];page.on('pageerror',e=>errors.push(e.message));
  try{
    await page.goto(url);await page.waitForFunction(()=>!document.getElementById('run').disabled);
    await page.waitForFunction(()=>!document.getElementById('loadSaved').disabled);
    checks.push('页面启动并自动加载 MCP 任务列表');
    const reports=await (await page.request.get(url+'/api/agh-reports')).json();
    async function saved(caseId){
      const task=reports.find(r=>r.case_id===caseId);assert(task,caseId);
      await page.selectOption('#saved',task.task_id);await page.click('#loadSaved');
      await page.waitForFunction(id=>{try{return JSON.parse(document.getElementById('json').textContent).task_id===id;}catch{return false;}},task.task_id);
      assert((await page.locator('#modeBanner').innerText()).includes('MCP'));
      return task;
    }
    const normal=await saved('normal');assert.equal(await page.locator('#status').innerText(),'已交付');
    await page.click('#refreshSaved');await page.waitForFunction(()=>!document.getElementById('refreshSaved').disabled);
    assert.equal(await page.locator('#saved').inputValue(),normal.task_id);
    checks.push('保存结果可加载且刷新保留当前选择');
    const downloadWait=page.waitForEvent('download');await page.click('#download');const download=await downloadWait;
    const downloaded=path.join(out,download.suggestedFilename());await download.saveAs(downloaded);
    const actual=await (await page.request.get(url+'/api/report?task_id='+normal.task_id)).json();
    assert.deepEqual(JSON.parse(fs.readFileSync(downloaded,'utf8')),actual);
    checks.push('下载结果与 HTTP 原始导出逐项一致');
    await saved('closure');assert((await page.locator('#resultTitle').innerText()).includes('R → E → D'));
    assert(await page.locator('#map line[stroke="#b33d3d"]').count()>0);
    await page.screenshot({path:path.join(out,'closure.png'),fullPage:true});
    checks.push('封路重规划路线与红色封闭航段显示正确');
    await saved('boundary');assert.equal(await page.locator('#status').innerText(),'已停止');assert.equal(await page.locator('#energy').innerText(),'0.00');
    assert((await page.locator('#chart').textContent()).includes('未起飞'));
    checks.push('时间边界中止保持零能耗且无执行曲线');
    await saved('sensor_failure');assert((await page.locator('#chartLegend').innerText()).includes('传感器失效'));
    checks.push('传感器失效明确标注仿真温度性质');
    await page.selectOption('#scenario','normal');await page.fill('#wind','10');await page.click('#run');
    await page.waitForFunction(()=>document.getElementById('modeBanner').textContent.includes('离线合成'));
    assert.equal(await page.locator('#status').innerText(),'已停止');assert((await page.locator('#plans').innerText()).includes('地速不足'));
    checks.push('极端逆风在页面返回拒绝原因');
    await page.selectOption('#scenario','normal');await page.fill('#battery','1');await page.click('#run');
    await page.waitForFunction(()=>document.getElementById('error').textContent.length>0);
    assert(!await page.locator('#run').isDisabled());
    checks.push('非法配置展示错误并恢复按钮');
    await page.route('**/api/report?*',route=>route.fulfill({status:404,contentType:'application/json',body:'{"error":"测试缺失任务"}'}));
    await page.click('#loadSaved');await page.waitForFunction(()=>document.getElementById('error').textContent==='测试缺失任务');
    assert(!await page.locator('#loadSaved').isDisabled());await page.unroute('**/api/report?*');
    checks.push('结果读取失败展示错误并恢复按钮');
    await page.route('**/api/agh-reports',route=>route.fulfill({status:200,contentType:'application/json',body:'[]'}));
    await page.click('#refreshSaved');await page.waitForFunction(()=>!document.getElementById('refreshSaved').disabled);
    assert(await page.locator('#loadSaved').isDisabled());assert((await page.locator('#saved').innerText()).includes('尚无导出'));
    await page.unroute('**/api/agh-reports');await page.click('#refreshSaved');await page.waitForFunction(()=>!document.getElementById('loadSaved').disabled);
    checks.push('空结果列表给出指引并停用查看按钮');
    await page.setViewportSize({width:390,height:844});await saved('closure');
    assert(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth));
    await page.screenshot({path:path.join(out,'mobile.png'),fullPage:true});
    checks.push('移动屏幕布局无横向页面溢出');
    assert.deepEqual(errors,[]);
    fs.writeFileSync(path.join(out,'browser_check.json'),JSON.stringify({scope:'real_browser_local_engineering_validation',overall_passed:true,count:checks.length,cases:checks,page_errors:errors,agh_session_verified:false,browser:await browser.version()},null,2));
    for(const check of checks)console.log('PASS：'+check);
  }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
