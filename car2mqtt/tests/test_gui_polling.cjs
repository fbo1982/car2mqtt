const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const {test} = require('node:test');
const html = fs.readFileSync('app/templates/index.html', 'utf8');
const segment = (from,to)=>html.slice(html.indexOf(from),html.indexOf(to,html.indexOf(from)));
const deferred = ()=>{let resolve;const promise=new Promise(r=>resolve=r);return {promise,resolve};};

test('all inline scripts parse after replacing template expressions', ()=>{
  for(const match of html.matchAll(/<script[^>]*>([\s\S]*?)<\/script>/g)){
    new vm.Script(match[1].replace(/\{\{[\s\S]*?\}\}/g,'null'));
  }
});

test('dashboard shares one pending request and avoids unchanged rendering', async()=>{
  const waiting=deferred();let calls=0,renders=0;
  const context=vm.createContext({setTimeout,clearTimeout,AbortController,Response,cards:[],renderCards:()=>renders++,
    fetch:async()=>{calls++;await waiting.promise;return new Response(JSON.stringify({vehicles:[{id:'TEST'}]}));}});
  vm.runInContext(segment('async function fetchRead(', 'async function postJson('),context);
  const first=context.loadDashboard();const second=context.loadDashboard();
  assert.equal(calls,1);waiting.resolve();await Promise.all([first,second]);
  assert.equal(renders,1);await context.loadDashboard();assert.equal(calls,2);assert.equal(renders,1);
});

test('a forced refresh after save fetches again after the old poll completes', async()=>{
  const waiting=deferred();let calls=0;
  const context=vm.createContext({setTimeout,clearTimeout,AbortController,Response,cards:[],renderCards:()=>{},
    fetch:async()=>{calls++;await waiting.promise;return new Response(JSON.stringify({vehicles:[]}));}});
  vm.runInContext(segment('async function fetchRead(', 'async function postJson('),context);
  const first=context.loadDashboard();const afterSave=context.loadDashboard(true);
  assert.equal(calls,1);waiting.resolve();await Promise.all([first,afterSave]);assert.equal(calls,2);
});

test('log polls do not overlap or show a previous vehicle response', async()=>{
  const waiting=deferred();let calls=0;const viewer={textContent:'NEW',scrollHeight:1};
  const context=vm.createContext({editState:{vehicleId:'OLD',lastLogText:''},field:()=>viewer,
    fetchText:async()=>{calls++;return waiting.promise;}});
  vm.runInContext(segment('let logRequest = null;', '\nfunction startLiveLogs('),context);
  const first=context.refreshVehicleLogs();const second=context.refreshVehicleLogs();assert.equal(calls,1);
  context.editState.vehicleId='NEW';waiting.resolve('OLD CONTENT');await Promise.all([first,second]);
  assert.equal(viewer.textContent,'NEW');
});

test('save buttons reject duplicate submissions and restore after completion',async()=>{
  const waiting=deferred();let posts=0;let closes=0;
  const elements={editManufacturer:{value:'acconia'},editPlate:{value:'SILENCE'},editLabel:{value:'Silence'},editEnabled:{checked:true},
    editAcconiaAccount:{value:'test@example.invalid'},editAcconiaPassword:{value:'dummy'},editAcconiaScooterId:{value:''},
    editAcconiaPollInterval:{value:'60'},editAcconiaCapacity:{value:''},editAcconiaApiKey:{value:''},editAcconiaHttpRawDebug:{checked:false},
    saveEditBtn:{disabled:false},saveEditKeepOpenBtn:{disabled:false},editDialog:{close:()=>closes++}};
  const context=vm.createContext({field:id=>elements[id],editState:{vehicleId:'SILENCE'},normalizeVehicleIdFromPlate:x=>x,
    document:{querySelectorAll:()=>[]},postJson:async()=>{posts++;await waiting.promise;return {vehicle_id:'SILENCE'};},
    loadDashboard:async()=>{},stopLiveLogs:()=>{},showNotice:()=>{}});
  vm.runInContext(segment('let editSavePending = false;', "\nfield('saveEditKeepOpenBtn').onclick"),context);
  const first=context.saveEdit(true);const second=context.saveEdit(true);
  assert.equal(posts,1);assert.equal(elements.saveEditBtn.disabled,true);waiting.resolve();await Promise.all([first,second]);
  assert.equal(elements.saveEditBtn.disabled,false);assert.equal(elements.saveEditKeepOpenBtn.disabled,false);assert.equal(closes,1);
});


test('MySilence diagnostic starts once and does not update another vehicle dialog', async()=>{
  const waiting=deferred();let calls=0,logs=0;const button={disabled:false};
  const context=vm.createContext({editState:{vehicleId:'OLD'},field:()=>button,encodeURIComponent,
    postJson:async()=>{calls++;await waiting.promise;},startLiveLogs:()=>logs++,showNotice:()=>{}});
  vm.runInContext(segment('async function startSilenceDiagnostics(', "field('silenceDiagnosticsBtn').onclick"),context);
  const first=context.startSilenceDiagnostics();const second=context.startSilenceDiagnostics();
  assert.equal(calls,1);assert.equal(button.disabled,true);
  context.editState.vehicleId='NEW';waiting.resolve();await Promise.all([first,second]);
  assert.equal(logs,0);assert.equal(button.disabled,false);
});
