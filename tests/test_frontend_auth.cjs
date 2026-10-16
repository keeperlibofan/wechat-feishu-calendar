const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const path = require('node:path');
const { test } = require('node:test');
const vm = require('node:vm');

const script = readFileSync(path.join(__dirname, '../app/static/app.js'), 'utf8');
const expiredPage = '页面已过期，请刷新后重试';
const state = { groups: [], events: [], issues: [], counts: {}, runtime: {}, settings: {} };

async function frontend(request, initialState=state) {
  const elements = new Map();
  const listeners = new Map();
  const element = selector => {
    if (!elements.has(selector)) elements.set(selector, {
      innerHTML: '', textContent: '', style: {}, open: false,
      showModal() { this.open = true; }, close() { this.open = false; }, focus() {},
    });
    return elements.get(selector);
  };
  let booted = false;
  const context = vm.createContext({
    document: {
      querySelector: element, querySelectorAll: () => [],
      addEventListener: (event, handler) => listeners.set(event, handler),
    },
    window: { addEventListener() {} }, location: { hash: '#settings' },
    setTimeout: () => 1, clearTimeout() {}, setInterval() { booted = true; },
    fetch: async (url, options) => {
      const payload = url === '/api/state' ? initialState
        : url.startsWith('/api/connections') ? { wechat: {}, lark: {}, model: {}, calendars: [] }
        : await request(url, options);
      return {
        status: payload.status ?? 200, ok: (payload.status ?? 200) < 400,
        json: async () => payload.body ?? payload,
      };
    },
  });
  vm.runInContext(script, context);
  for (let i = 0; i < 50 && !booted; i++) await new Promise(resolve => setImmediate(resolve));
  assert.ok(booted, 'Frontend must complete its normal boot before a click');
  return { context, elements, input: target => listeners.get('input')({target}), change: target => listeners.get('change')({target}), click: async (action, dataset={}) => {
    const button = { dataset: { action, ...dataset }, disabled: false };
    await listeners.get('click')({ target: { closest: () => button } });
    assert.equal(button.disabled, false);
  } };
}

test('authorization renews a stale page token and shows the generated link', async () => {
  let bootstraps = 0;
  const authCalls = [];
  const ui = await frontend(async (url, options) => {
    if (url === '/api/bootstrap') return { token: ++bootstraps === 1 ? 'old-token' : 'new-token' };
    assert.equal(url, '/api/auth/start');
    authCalls.push(options);
    return authCalls.length === 1 ? { status: 403, body: { error: expiredPage } }
      : { url: 'https://accounts.feishu.cn/auth?example=1', qr: '/api/auth/qr' };
  });
  await ui.click('auth-start');
  assert.equal(authCalls.length, 2);
  assert.equal(authCalls[0].headers['X-App-Token'], 'old-token');
  assert.equal(authCalls[1].headers['X-App-Token'], 'new-token');
  assert.equal(authCalls[1].body, authCalls[0].body);
  assert.match(ui.elements.get('#dialog-content').innerHTML, /https:\/\/accounts\.feishu\.cn\/auth\?example=1/);
  assert.match(ui.elements.get('#dialog-content').innerHTML, /我已完成授权/);
  assert.doesNotMatch(ui.elements.get('#dialog-content').innerHTML, /正在生成授权链接/);
});

test('authorization failure remains visible in its dialog and offers a retry', async () => {
  const ui = await frontend(async url => url === '/api/bootstrap' ? { token: 'token' }
    : { status: 400, body: { error: '飞书请求超时' } });
  await ui.click('auth-start');
  const dialog = ui.elements.get('#dialog-content').innerHTML;
  assert.match(dialog, /飞书请求超时/);
  assert.match(dialog, /data-action="auth-start"/);
  assert.doesNotMatch(dialog, /正在生成授权链接/);
});

test('a repeated expired-page response is not retried indefinitely', async () => {
  let requests = 0;
  let bootstraps = 0;
  const ui = await frontend(async url => {
    if (url === '/api/bootstrap') return { token: `token-${++bootstraps}` };
    requests++;
    return { status: 403, body: { error: expiredPage } };
  });
  await ui.click('auth-start');
  assert.equal(requests, 2);
  assert.equal(bootstraps, 2);
  assert.match(ui.elements.get('#dialog-content').innerHTML, /页面已过期/);
});

test('other forbidden requests keep their protection and are not retried', async () => {
  let requests = 0;
  let bootstraps = 0;
  const ui = await frontend(async url => {
    if (url === '/api/bootstrap') return { token: `token-${++bootstraps}` };
    requests++;
    return { status: 403, body: { error: '不允许跨站访问' } };
  });
  await ui.click('auth-start');
  assert.equal(requests, 1);
  assert.equal(bootstraps, 1);
  assert.match(ui.elements.get('#dialog-content').innerHTML, /不允许跨站访问/);
});


test('custom attributes, filtering choices and introduction survive edits and save together', async () => {
  const initialState = {...state, settings: {interval:30, reminder:5, model_enabled:false, profile:{attributes:[], introduction:''}}};
  let submitted;
  const ui = await frontend(async (url, options) => {
    if(url === '/api/bootstrap') return {token:'token'};
    assert.equal(url, '/api/settings');
    submitted = JSON.parse(options.body);
    initialState.settings = submitted;
    return {ok:true};
  }, initialState);
  await ui.click('profile-add');
  const field = (index, key, value) => ui.input({dataset:{profileIndex:String(index),profileField:key},value});
  field(0, 'name', '出生日期');
  ui.change({dataset:{profileIndex:'0',profileField:'type'}, value:'date'});
  field(0, 'value', '2001-02-03');
  await ui.click('profile-add');
  field(1, 'name', '任意新增属性'); field(1, 'value', '<标签>无需改代码');
  ui.change({dataset:{profileIndex:'1',profileField:'enabled'},checked:false});
  ui.input({id:'profile-introduction',value:'我负责设备管理。\n设备维护通知与我有关。'});
  await ui.click('profile-add');
  await ui.click('profile-remove', {index:'2'});
  await ui.click('refresh-connections');
  ui.change({id:'setting-interval',value:'60'});
  await ui.click('save-settings');
  assert.deepEqual(submitted.profile, {attributes:[
    {name:'出生日期',type:'date',value:'2001-02-03',enabled:true},
    {name:'任意新增属性',type:'text',value:'<标签>无需改代码',enabled:false},
  ],introduction:'我负责设备管理。\n设备维护通知与我有关。'});
  assert.equal(submitted.interval, 60);
  assert.match(ui.elements.get('#main').innerHTML, /&lt;标签&gt;无需改代码/);
  assert.match(ui.elements.get('#main').innerHTML, /设备维护通知与我有关/);
});

test('failed settings save keeps the profile draft available for correction', async () => {
  const ui = await frontend(async url => url === '/api/bootstrap' ? {token:'token'}
    : {status:400,body:{error:'请填写属性名称'}}, {...state,settings:{}});
  await ui.click('profile-add');
  ui.input({dataset:{profileIndex:'0',profileField:'value'},value:'不能丢失的资料'});
  await ui.click('save-settings');
  assert.match(ui.elements.get('#toast').textContent, /请填写属性名称/);
  await ui.click('refresh-connections');
  assert.match(ui.elements.get('#main').innerHTML, /不能丢失的资料/);
});
