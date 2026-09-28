// Optional developer test: npm install --no-save playwright, then node tests/ui.cjs.
const { chromium } = require('playwright');
const { spawn, spawnSync } = require('node:child_process');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const assert = require('node:assert/strict');
const root = path.resolve(__dirname, '..');
const scripts = path.join(root, 'plugins/project-coding-harness/scripts');
const python = process.env.HARNESS_PYTHON || 'python';
const project = fs.mkdtempSync(path.join(os.tmpdir(), 'harness-ui-'));
fs.writeFileSync(path.join(project, 'main.py'), 'print("hello")\n');
function call(action, payload = {}) {
  const code = 'import json,sys;sys.path.insert(0,sys.argv[1]);from store import dispatch;print(json.dumps(dispatch(sys.argv[2],sys.argv[3],json.loads(sys.stdin.read())),ensure_ascii=True))';
  const result = spawnSync(python, ['-X', 'utf8', '-c', code, scripts, action, project], { input: JSON.stringify(payload), encoding: 'utf8' });
  if (result.status) throw new Error(result.stderr);
  return JSON.parse(result.stdout);
}
async function main() {
  const server = spawn(python, [path.join(scripts, 'harness.py'), 'dashboard', '--project', project]);
  let browser;
  try {
    const url = await new Promise((resolve, reject) => {
      let output = '';
      const timer = setTimeout(() => reject(new Error('Server startup timeout')), 10000);
      server.on('error', reject);
      server.stdout.on('data', data => { output += data; const match = output.match(/http:\/\/127\.0\.0\.1:\d+\/[^\s]+/); if (match) { clearTimeout(timer); resolve(match[0]); } });
    });
    browser = await chromium.launch({ channel: process.env.HARNESS_BROWSER || 'msedge', headless: true });
    const page = await browser.newPage({ viewport: { width: 960, height: 1000 } });
    const errors = [];
    page.on('pageerror', e => errors.push(e.message));
    await page.goto(url);
    await page.locator('#badge').filter({ hasText: '미분석' }).waitFor();
    await page.selectOption('#depth', 'deep');
    await page.fill('#rounds', '2');
    await page.click('#save');
    await page.locator('#message').filter({ hasText: '프로젝트 설정을 저장했습니다' }).waitFor();
    assert.deepEqual(call('status').settings, { review_depth: 'deep', max_rounds: 2, usage_mode: 'auto', offer_setup: true });
    await page.selectOption('#usage', 'on_request');
    await page.selectOption('#offer', 'no');
    await page.click('#save-usage');
    await page.locator('#message').filter({ hasText: '프로젝트 사용 설정을 저장했습니다' }).waitFor();
    assert.deepEqual(call('preferences').settings, { review_depth: 'deep', max_rounds: 2, usage_mode: 'on_request', offer_setup: false });
    await page.reload();
    await page.waitForFunction(() => document.querySelector('#usage').value === 'on_request');
    assert.equal(await page.inputValue('#offer'), 'no');
    // Conversation tools use the same partial configure contract; UI sees changes on refresh.
    call('configure', { usage_mode: 'auto', offer_setup: true });
    await page.click('#reload');
    await page.waitForFunction(() => document.querySelector('#usage').value === 'auto');
    assert.equal(await page.inputValue('#offer'), 'yes');
    await page.click('#analyze');
    await page.locator('#handoff:not([hidden])').waitFor();
    const request = call('status').requests.find(r => r.status === 'pending');
    assert.equal(request.mode, 'analyze');
    assert.ok((await page.inputValue('#request')).includes(request.id));
    call('save_analysis', { request_id: request.id, name: '친구의 가계부', project: '# 목적\n개인 지출 관리', architecture: '# 구조\nmain.py 진입점', verification: '# 검증\n테스트 명령 미설정', evidence: ['main.py'], note_decisions: {} });
    const proposal = call('propose', { title: '지출 금액은 정수로 저장한다', body: '소수점 반올림 오차를 피하기 위해 최소 화폐 단위의 정수로 저장한다.', evidence: ['main.py'] });
    await page.click('#reload');
    await page.getByRole('heading', { name: '친구의 가계부', exact: true }).waitFor();
    await page.getByRole('button', { name: '기억하기', exact: true }).click();
    await page.locator('#message').filter({ hasText: '동의한 내용을 기억했습니다' }).waitFor();
    assert.equal(call('status').notes[0].id, proposal.id);
    await page.click('#refresh');
    await page.locator('#handoff:not([hidden])').waitFor();
    assert.equal(call('status').requests.find(r => r.status === 'pending').mode, 'refresh');
    await page.click('#cancel');
    await page.locator('#message').filter({ hasText: '대기 요청을 취소했습니다' }).waitFor();
    fs.mkdirSync(path.join(root, '.test-output'), { recursive: true });
    await page.screenshot({ path: path.join(root, '.test-output/dashboard.png'), fullPage: true });
    await page.setViewportSize({ width: 390, height: 844 });
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth));
    // Exercise the MCP Apps bridge with a simulated host, not an actual Codex host.
    const widget = fs.readFileSync(path.join(root, 'plugins/project-coding-harness/ui/dashboard.html'), 'utf8');
    await page.exposeFunction('testHarnessCall', (action, payload) => call(action, payload));
    await page.setContent('<iframe id="widget" style="width:900px;height:1000px"></iframe>');
    await page.evaluate(({ widget, snapshot }) => {
      window.sentPrompts = [];
      const frame = document.getElementById('widget');
      window.addEventListener('message', async event => {
        if (event.source !== frame.contentWindow) return;
        const m = event.data;
        if (!m || m.jsonrpc !== '2.0' || m.id === undefined) return;
        let result = {};
        if (m.method === 'tools/call') result = { structuredContent: await window.testHarnessCall(m.params.name.slice(8), m.params.arguments.payload) };
        if (m.method === 'ui/message') window.sentPrompts.push(m.params.content[0].text);
        frame.contentWindow.postMessage({ jsonrpc:'2.0', id:m.id, result }, '*');
        if (m.method === 'ui/initialize') frame.contentWindow.postMessage({ jsonrpc:'2.0', method:'ui/notifications/tool-result', params:{ structuredContent:snapshot } }, '*');
      });
      frame.srcdoc = widget;
    }, { widget, snapshot: call('status') });
    const frame = page.frameLocator('#widget');
    await frame.locator('#badge').filter({ hasText: '분석됨' }).waitFor();
    await frame.locator('#refresh').click();
    await frame.locator('#message').filter({ hasText: '현재 대화에 분석 요청을 보냈습니다' }).waitFor();
    assert.equal(await page.evaluate(() => window.sentPrompts.length), 1);
    assert.ok((await page.evaluate(() => window.sentPrompts[0])).includes('refresh'));
    await frame.locator('#cancel').click();
    await frame.locator('#message').filter({ hasText: '대기 요청을 취소했습니다' }).waitFor();
    assert.deepEqual(errors, []);
    console.log('PASS: browser settings, analysis request, memory consent, refresh/cancel, mobile layout, simulated MCP Apps bridge; no JS errors');
  } finally {
    if (browser) await browser.close();
    server.kill();
    await new Promise(resolve => server.exitCode !== null ? resolve() : server.once('exit', resolve));
    fs.rmSync(project, { recursive: true, force: true });
  }
}
main().catch(e => { console.error(e); process.exitCode = 1; });
