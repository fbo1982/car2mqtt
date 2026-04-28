
const providers = {{ providers | tojson }};
let cards = {{ cards_json | safe }};
let helperHomezoneJson = {{ helper_homezone_json | safe }};
let uiSettings = {{ ui_settings_json | safe }};
let availableZones = {{ zones_json | safe }};
let mqttClients = {{ mqtt_clients_json | safe }};
const mqttClientState = { editingId: null };
const createState = { manufacturer: null, authSessionId: null, authReady: false };
const editState = { vehicleId: null, reauthSessionId: null, authReady: true, liveLogTimer: null, liveLogsEnabled: false, lastLogText: '', needsVerification: false };
const field = (id) => document.getElementById(id);

function normalizeVehicleIdFromPlate(plate){
  return String(plate || '').toUpperCase().replace(/[^A-Z0-9]/g,'');
}

function yamlEscape(value){
  return String(value ?? '').replace(/"/g, '\"');
}
function manufacturerTopicPrefix(manufacturer){
  return String(manufacturer || '').toLowerCase();
}
function getCurrentEditCard(){
  return cards.find(card => card.id === editState.vehicleId) || null;
}
function normalizeEvccOnIdentifyMode(value){
  const mode = String(value || '').trim().toLowerCase();
  if(mode === 'aus' || mode === 'off') return 'off';
  if(mode === 'pv') return 'pv';
  if(mode === 'min+pv' || mode === 'minpv' || mode === 'min_pv' || mode === 'min-pv') return 'minpv';
  if(mode === 'schnell' || mode === 'now') return 'now';
  return 'off';
}
function evccCfgFromCardOrVehicle(obj){
  const cfg = (obj && obj.evcc_config) || (obj && obj.provider_config) || {};
  const fallbackTitle = (obj && (obj.label || obj.title || obj.license_plate)) || '';
  const fallbackCapacity = (obj && obj.metrics && obj.metrics.capacityKwh != null) ? obj.metrics.capacityKwh : '';
  const cap = cfg.evcc_capacity_kwh ?? cfg.capacity_kwh ?? fallbackCapacity ?? '';
  const title = cfg.evcc_title || fallbackTitle || '';
  return {
    evcc_ref: cfg.evcc_ref || '',
    evcc_managed: cfg.evcc_managed !== false,
    evcc_auto_sync: cfg.evcc_auto_sync !== false,
    evcc_name: cfg.evcc_name || title,
    evcc_title: title,
    evcc_capacity_kwh: cap || '',
    evcc_phases: cfg.evcc_phases || '',
    evcc_identifiers: Array.isArray(cfg.evcc_identifiers) ? cfg.evcc_identifiers.join(', ') : (cfg.evcc_identifiers || ''),
    evcc_onidentify_mode: normalizeEvccOnIdentifyMode(cfg.evcc_onidentify_mode || 'off'),
  };
}
function fillEvccVehicleConfigFields(obj){
  const cfg = evccCfgFromCardOrVehicle(obj || {});
  const isRemote = !!(obj && obj.remote);
  field('editEvccRef').value = cfg.evcc_ref || '';
  field('editEvccName').value = cfg.evcc_name || '';
  field('editEvccTitle').value = cfg.evcc_title || '';
  field('editEvccCapacity').value = cfg.evcc_capacity_kwh || '';
  field('editEvccPhases').value = cfg.evcc_phases || '';
  field('editEvccIdentifiers').value = cfg.evcc_identifiers || '';
  field('editEvccOnIdentifyMode').value = normalizeEvccOnIdentifyMode(cfg.evcc_onidentify_mode || 'off');
  setEvccRemoteFieldMode(isRemote);
}
function setEvccRemoteFieldMode(isRemote){
  const editableOnlyOnHost = ['editEvccName','editEvccTitle','editEvccCapacity','editEvccPhases','editEvccIdentifiers'];
  editableOnlyOnHost.forEach(id => { const el = field(id); if(el) el.disabled = !!isRemote; });
  if(field('editEvccRef')) field('editEvccRef').disabled = false;
  if(field('editEvccOnIdentifyMode')) field('editEvccOnIdentifyMode').disabled = false;
  field('evccRemoteConfigHint')?.classList.toggle('hidden', !isRemote);
  if(field('saveEvccVehicleConfigBtn')) field('saveEvccVehicleConfigBtn').textContent = isRemote ? 'Lokale EVCC-Zuordnung speichern' : 'EVCC/MQTT-Konfiguration speichern';
}
function collectEvccVehicleConfigPayload(){
  return {
    evcc_ref: field('editEvccRef')?.value?.trim() || '',
    evcc_managed: true,
    evcc_auto_sync: true,
    evcc_name: field('editEvccName')?.value?.trim() || '',
    evcc_title: field('editEvccTitle')?.value?.trim() || '',
    evcc_capacity_kwh: field('editEvccCapacity')?.value?.trim() || '',
    evcc_phases: field('editEvccPhases')?.value || '',
    evcc_identifiers: field('editEvccIdentifiers')?.value?.trim() || '',
    evcc_onidentify_mode: normalizeEvccOnIdentifyMode(field('editEvccOnIdentifyMode')?.value || 'off'),
  };
}
function setEditRemoteMode(enabled, card=null){
  field('editRemoteSection')?.classList.toggle('hidden', !enabled);
  field('editBmwSection')?.classList.toggle('hidden', true);
  field('editGwmSection')?.classList.toggle('hidden', true);
  field('editAcconiaSection')?.classList.toggle('hidden', true);
  field('gwmVerifyPanel')?.classList.toggle('hidden', true);
  field('editLocalMainFields')?.classList.toggle('hidden', !!enabled);
  const mqttAssign = field('editMqttClientsAssign')?.closest('.info-box');
  if(mqttAssign) mqttAssign.style.display = enabled ? 'none' : '';
  const logBox = field('vehicleLogViewer')?.closest('.log-box');
  if(logBox) logBox.style.display = enabled ? 'none' : '';
  const keepOpenBtn = field('saveEditKeepOpenBtn');
  const saveCloseBtn = field('saveEditBtn');
  if(keepOpenBtn){
    keepOpenBtn.style.display = '';
    keepOpenBtn.textContent = enabled ? 'Lokale EVCC-Zuordnung speichern' : 'Speichern';
  }
  if(saveCloseBtn){
    saveCloseBtn.style.display = '';
    saveCloseBtn.textContent = enabled ? 'Speichern & schließen' : 'Speichern & schließen';
  }
  field('editReauthQuickBtn').style.display = enabled ? 'none' : '';
  const cancelBtn = field('cancelEditBtn');
  if(cancelBtn){
    cancelBtn.style.display = '';
    cancelBtn.textContent = enabled ? 'Schließen' : 'Abbrechen';
  }
  const enabledWrap = field('editEnabled')?.closest('.field');
  if(enabledWrap) enabledWrap.style.display = enabled ? 'none' : '';
  const manWrap = field('editManufacturer')?.closest('.field');
  if(manWrap) manWrap.style.display = enabled ? 'none' : '';
  field('bmwHowtoBtn')?.classList.toggle('hidden', true);
  field('editLabel').readOnly = !!enabled;
  field('editPlate').readOnly = !!enabled;
  if(enabled && card){
    field('editRemoteLabel').value = String(card.label || card.license_plate || '');
    field('editRemotePlate').value = String(card.license_plate || '');
    field('editRemoteVin').value = String(card.vin || ((card.live || {}).vin || ''));
    field('editRemoteServerName').value = String(card.remote_server_name || '');
    field('editRemoteDeviceTrackerEnabled').checked = !!card.device_tracker_enabled;
    field('editAuthState').textContent = card.status_detail || card.manufacturer_note || 'Remote Fahrzeug';
  } else {
    field('editRemoteLabel').value = '';
    field('editRemotePlate').value = '';
    field('editRemoteVin').value = '';
    field('editRemoteServerName').value = '';
  }
}

function getCopyConfigContext(){
  const manufacturer = field('editManufacturer').value || 'bmw';
  const id = normalizeVehicleIdFromPlate(field('editPlate').value.trim());
  const rawPlate = field('editPlate').value.trim() || id;
  const title = field('editLabel').value.trim() || id;
  const current = getCurrentEditCard();
  let capacity = '';
  if(manufacturer === 'gwm'){
    capacity = String(field('editGwmCapacity')?.value || '').trim();
  } else if (manufacturer === 'bmw') {
    capacity = String((current && current.metrics && current.metrics.capacityKwh != null ? current.metrics.capacityKwh : '') || '').trim();
  }
  const manufacturerPrefix = manufacturerTopicPrefix(manufacturer);
  const topicBase = `car/${manufacturerPrefix}/${id}/mapped`;
  const entityBase = `car_${manufacturerPrefix}_${id.toLowerCase()}`;
  const varPrefix = `${id.toLowerCase()}_`;
  const evccCfg = evccCfgFromCardOrVehicle(current || {});
  const onIdentifyMode = normalizeEvccOnIdentifyMode(field('editEvccOnIdentifyMode')?.value || evccCfg.evcc_onidentify_mode || 'off');
  return { manufacturer, manufacturerPrefix, id, rawPlate, title, current, capacity, topicBase, entityBase, varPrefix, onIdentifyMode };
}
function getHelperCards(){
  return (cards || []).filter(card => card && card.license_plate && card.manufacturer);
}
function mqttStatusLabel(status){
  if(status === 'online') return 'Online';
  if(status === 'offline') return 'Offline';
  return 'Deaktiviert';
}
function renderMqttClientsGrid(){
  const grid = field('mqttClientsGrid'); if(!grid) return;
  const addTile = `
    <article class="vehicle-card add-card" role="button" tabindex="0" onclick="openCreateMqttClient()" style="min-height:220px">
      <div class="add-card-plus">+</div><div class="add-card-label">Client hinzufügen</div>
    </article>`;
  const cardsHtml = (mqttClients || []).map(client => `
    <article class="vehicle-card">
      <div class="vehicle-head">
        <div><div class="vehicle-title">${client.name || client.id}</div><div class="vehicle-subtitle">${client.host}:${client.port}</div></div>
        <div class="status-badge ${client.status || 'disabled'}">${mqttStatusLabel(client.status)}</div>
      </div>
      <div class="vehicle-metrics">
        <div class="metric"><span>Aktiv</span><strong>${client.enabled ? 'ja' : 'nein'}</strong></div>
        <div class="metric"><span>Raw</span><strong>${client.send_raw ? 'ja' : 'nein'}</strong></div>
        <div class="metric"><span>Benutzer</span><strong>${client.username || '-'}</strong></div>
      </div>
      <div class="card-footer">
        <div class="muted" style="font-size:13px">${client.enabled ? ((client.runtime_status && client.runtime_status.last_ok) ? ('Letzte Übertragung: ' + client.runtime_status.last_ok) : 'Weiterleitung aktiv') : 'Client deaktiviert'}</div>
        <div class="card-actions"><button class="tiny-btn" type="button" onclick="editMqttClient('${client.id}')">Bearbeiten</button><button class="danger-btn" type="button" onclick="deleteMqttClient('${client.id}')">Löschen</button></div>
      </div>
    </article>`).join('');
  grid.innerHTML = addTile + cardsHtml;
}

function renderEditMqttClientAssignments(vehicle){
  const wrap = field('editMqttClientsAssign'); if(!wrap) return;
  const assigned = new Set((vehicle && vehicle.mqtt_client_ids) || []);
  wrap.innerHTML = (mqttClients || []).map(client => `
    <label class="comm-toggle comm-card"><input type="checkbox" class="edit-mqtt-client-check" value="${client.id}" ${assigned.has(client.id) ? 'checked' : ''}><span><span class="comm-title">${client.name || client.id}</span><div class="comm-help">${client.host}:${client.port} · ${mqttStatusLabel(client.status)}</div></span></label>
  `).join('') || '<div class="muted">Keine MQTT Clients vorhanden. Lege sie über den Button "MQTT Clients" an.</div>';
}
function setMqttClientEditorVisible(visible){ const box = field('mqttClientEditor'); if(box) box.style.display = visible ? '' : 'none'; const actions = field('mqttClientEditorActions'); if(actions) actions.style.display = visible ? '' : 'none'; }
function resetMqttClientForm(hideEditor=false){ mqttClientState.editingId = null; field('mqttClientName').value=''; field('mqttClientHost').value=''; field('mqttClientPort').value='1883'; field('mqttClientBaseTopic').value=''; field('mqttClientUsername').value=''; field('mqttClientPassword').value=''; field('mqttClientEnabled').checked=true; field('mqttClientSendRaw').checked=false; if(field('mqttClientEditorTitle')) field('mqttClientEditorTitle').textContent='Client hinzufügen'; setMqttClientEditorVisible(!hideEditor); }
function openCreateMqttClient(){ resetMqttClientForm(false); showNotice('mqttClientsError',''); }
window.openCreateMqttClient = openCreateMqttClient;
function editMqttClient(id){ const client=(mqttClients||[]).find(c=>c.id===id); if(!client) return; mqttClientState.editingId=id; field('mqttClientName').value=client.name||''; field('mqttClientHost').value=client.host||''; field('mqttClientPort').value=client.port||1883; field('mqttClientBaseTopic').value=client.base_topic||''; field('mqttClientUsername').value=client.username||''; field('mqttClientPassword').value=client.password||''; field('mqttClientEnabled').checked=!!client.enabled; field('mqttClientSendRaw').checked=!!client.send_raw; if(field('mqttClientEditorTitle')) field('mqttClientEditorTitle').textContent='Client bearbeiten'; setMqttClientEditorVisible(true); showNotice('mqttClientsError',''); }
window.editMqttClient = editMqttClient;
async function deleteMqttClient(id){ if(!confirm('MQTT Client wirklich löschen?')) return; await fetch(`./api/mqtt-clients/${id}`, {method:'DELETE'}); const res = await fetch('./api/mqtt-clients'); mqttClients = (await res.json()).clients || []; renderMqttClientsGrid(); const card = getCurrentEditCard(); if(card) renderEditMqttClientAssignments(card); if(mqttClientState.editingId===id){ resetMqttClientForm(true); } }
window.deleteMqttClient = deleteMqttClient;
async function openMqttClientsDialog(){ renderMqttClientsGrid(); resetMqttClientForm(true); field('mqttClientsDialog').showModal(); }
function buildHelperConfigurationYamlTemplate(){
  const helperCards = getHelperCards();
  const blocks = [];
  blocks.push(`#######################################
## EVCC Basis-Topics ##
#######################################

    - name: "evcc Loadpoint 1 Connected"
      unique_id: evcc_lp1_connected
      state_topic: "evcc/loadpoints/1/connected"
      availability_topic: "evcc/status"
      payload_available: "online"
      payload_not_available: "offline"

    - name: "evcc Loadpoint 1 Vehicle"
      unique_id: evcc_lp1_vehicle
      state_topic: "evcc/loadpoints/1/vehicleTitle"
      availability_topic: "evcc/status"
      payload_available: "online"
      payload_not_available: "offline"`);
  helperCards.forEach(card => {
    const manufacturer = manufacturerTopicPrefix(card.manufacturer);
    const id = normalizeVehicleIdFromPlate(card.license_plate || card.id || '');
    const rawPlate = String(card.license_plate || id);
    const title = String(card.label || id);
    const topicBase = `car/${manufacturer}/${id}/mapped`;
    const entityBase = `car_${manufacturer}_${id.toLowerCase()}`;
    const displayManufacturer = manufacturer.toUpperCase();
    blocks.push(`#######################################
## ${rawPlate} ${title} ##
#######################################

    - name: "Car ${displayManufacturer} ${id} Plugged TS"
      unique_id: ${entityBase}_plugged_ts
      state_topic: "${topicBase}/plugged_ts"
      availability_topic: "evcc/status"
      payload_available: "online"
      payload_not_available: "offline"

    - name: "Car ${displayManufacturer} ${id} Plugged"
      unique_id: ${entityBase}_plugged
      state_topic: "${topicBase}/plugged"
      availability_topic: "evcc/status"
      payload_available: "online"
      payload_not_available: "offline"

    - name: "Car ${displayManufacturer} ${id} Latitude"
      unique_id: ${entityBase}_latitude
      state_topic: "${topicBase}/latitude"
      availability_topic: "evcc/status"
      payload_available: "online"
      payload_not_available: "offline"

    - name: "Car ${displayManufacturer} ${id} Longitude"
      unique_id: ${entityBase}_longitude
      state_topic: "${topicBase}/longitude"
      availability_topic: "evcc/status"
      payload_available: "online"
      payload_not_available: "offline"`);
  });
  return blocks.join(`

`);
}
function escapeHelperValue(value, fallback){
  const v = (value || '').toString().trim();
  return yamlEscape(v || fallback || '');
}
function getSelectedHomeZoneEntityId(){
  return String(uiSettings?.helper_home_zone_entity_id || '').trim();
}
function describeHomezone(homezone){
  if(!homezone) return 'Keine Home Zone gewählt.';
  if(homezone.selected_via_settings && homezone.entity_id){
    const detected = String(homezone.detected_entity_id || '').trim();
    return detected && detected !== homezone.entity_id ? `Aktive Auswahl: ${homezone.entity_id} (erkannt: ${detected})` : `Aktive Auswahl: ${homezone.entity_id}`;
  }
  if(homezone.found && homezone.source){
    return `Automatisch erkannt aus ${homezone.source}`;
  }
  return 'Keine gespeicherte Home Zone - Standard zone.home wird verwendet.';
}
async function loadSettingsData(){
  const initial = {
    ui_settings: uiSettings || {},
    zones: Array.isArray(availableZones) ? availableZones : [],
    effective_homezone: helperHomezoneJson || null,
  };
  if(initial.zones.length || initial.effective_homezone){
    return initial;
  }
  try{
    const resp = await fetch('api/settings');
    if(!resp.ok) throw new Error('Einstellungen konnten nicht geladen werden.');
    const data = await resp.json();
    uiSettings = data.ui_settings || {};
    availableZones = Array.isArray(data.zones) ? data.zones : [];
    if(data.effective_homezone) helperHomezoneJson = data.effective_homezone;
    return data;
  }catch(err){
    return initial;
  }
}
function prettyZoneLabel(entityId){
  const raw = String(entityId || '').trim();
  if(!raw) return '';
  const base = raw.startsWith('zone.') ? raw.slice(5) : raw;
  return base.split('_').filter(Boolean).map(part => part.charAt(0).toUpperCase() + part.slice(1)).join(' ');
}
function renderSettingsDialog(data){
  const select = field('settingsHomeZoneSelect');
  const info = field('settingsHomeZoneInfo');
  const trackerToggle = field('settingsDeviceTrackerEnabled');
  if(!select) return;
  const zones = Array.isArray(data?.zones) ? [...data.zones] : [];
  const selected = String(data?.ui_settings?.helper_home_zone_entity_id || '');
  const effectiveEntity = String(data?.effective_homezone?.entity_id || '');
  const detectedEntity = String(data?.effective_homezone?.detected_entity_id || '');
  if(selected && !zones.some(z => z && z.entity_id === selected)) {
    zones.push({ entity_id: selected, name: prettyZoneLabel(selected) || selected });
  }
  if(effectiveEntity && !zones.some(z => z && z.entity_id === effectiveEntity)) {
    zones.push({ entity_id: effectiveEntity, name: prettyZoneLabel(effectiveEntity) || effectiveEntity });
  }
  if(detectedEntity && !zones.some(z => z && z.entity_id === detectedEntity)) {
    zones.push({ entity_id: detectedEntity, name: prettyZoneLabel(detectedEntity) || detectedEntity });
  }
  availableZones = zones;
  select.innerHTML = '';
  const autoOpt = document.createElement('option');
  autoOpt.value = '';
  autoOpt.textContent = 'Automatisch erkennen';
  select.appendChild(autoOpt);
  zones.forEach(zone => {
    const opt = document.createElement('option');
    opt.value = zone.entity_id;
    opt.textContent = `${zone.name} (${zone.entity_id})`;
    if(zone.entity_id === selected) opt.selected = true;
    select.appendChild(opt);
  });
  if(info) info.textContent = describeHomezone(data?.effective_homezone || helperHomezoneJson);
  if(trackerToggle) trackerToggle.checked = !!(data?.ui_settings?.device_tracker_enabled);
  const ui = data?.ui_settings || {};
  if(field("settingsHaDiscoveryEnabled")) field("settingsHaDiscoveryEnabled").checked = ui.ha_discovery_enabled !== false;
  if(field("settingsHaDiscoveryPrefix")) field("settingsHaDiscoveryPrefix").value = ui.ha_discovery_prefix || "homeassistant";
  if(field("settingsHaDiscoveryRetain")) field("settingsHaDiscoveryRetain").checked = ui.ha_discovery_retain !== false;
  if(field("settingsEvccEnabled")) field("settingsEvccEnabled").checked = !!ui.evcc_enabled;
  if(field("settingsEvccUrl")) field("settingsEvccUrl").value = ui.evcc_url || "http://localhost:7070";
  if(field("settingsEvccPassword")) field("settingsEvccPassword").value = "";
  if(field("settingsEvccDbPath")) field("settingsEvccDbPath").value = ui.evcc_db_path || "/data/evcc.db";
  if(field("settingsEvccAutoCreate")) field("settingsEvccAutoCreate").checked = !!ui.evcc_auto_create;
  if(field("settingsEvccAutoUpdate")) field("settingsEvccAutoUpdate").checked = ui.evcc_auto_update !== false;
  if(field("settingsEvccAutoDelete")) field("settingsEvccAutoDelete").checked = !!ui.evcc_auto_delete;
}
async function openSettingsDialog(){
  const dlg = field('settingsDialog');
  if(!dlg) return;
  try{
    const data = await loadSettingsData();
    renderSettingsDialog(data);
  }catch(err){
    const info = field('settingsHomeZoneInfo');
    if(info) info.textContent = err.message || 'Einstellungen konnten nicht geladen werden.';
  }
  try{ dlg.showModal(); }catch(e){ dlg.setAttribute('open','open'); dlg.style.display='flex'; }
}
function closeSettingsDialog(){
  const d = field('settingsDialog');
  if(d){ try{ d.close(); }catch(e){ d.removeAttribute('open'); d.style.display='none'; } }
}

function buildHelperAutomationsYamlTemplate(homezone){
  const helperCards = getHelperCards();
  const J2O = "{{ '{{' }}";
  const J2C = "{{ '}}' }}";
  const J2SO = "{{ '{%' }}";
  const J2SC = "{{ '%}' }}";
  const homeLatValue = escapeHelperValue(homezone?.home_lat, `${J2O} state_attr('zone.home', 'latitude') | float(0) ${J2C}`);
  const homeLonValue = escapeHelperValue(homezone?.home_lon, `${J2O} state_attr('zone.home', 'longitude') | float(0) ${J2C}`);
  const foundExisting = !!homezone?.found;
  const homezoneSource = String(homezone?.source || '');
  const checkedPaths = Array.isArray(homezone?.checked_paths) ? homezone.checked_paths.filter(Boolean) : [];
  const homezoneComment = foundExisting
    ? `# Vorhandene Homezone übernommen${homezoneSource ? ` aus: ${homezoneSource}` : ''}`
    : `# Keine vorhandene Homezone gefunden - Standard zone.home verwendet${checkedPaths.length ? ` | geprüft: ${checkedPaths.slice(0,4).join(', ')}` : ''}`;
  const cardVars = helperCards.map((card, index) => {
    const id = normalizeVehicleIdFromPlate(card.license_plate || card.id || '');
    const entityBase = `car_${manufacturerTopicPrefix(card.manufacturer)}_${id.toLowerCase()}`;
    const prefix = `v${index + 1}_`;
    const title = String(card.label || id);
    return `    ##################################################
    # ${title}
    ##################################################
    ${prefix}vehicle: "${yamlEscape(title)}"
    ${prefix}plugged_raw: "${J2O} states('sensor.${entityBase}_plugged') ${J2C}"
    ${prefix}plugged_ts_raw: "${J2O} states('sensor.${entityBase}_plugged_ts') ${J2C}"
    ${prefix}lat_raw: "${J2O} states('sensor.${entityBase}_latitude') ${J2C}"
    ${prefix}lon_raw: "${J2O} states('sensor.${entityBase}_longitude') ${J2C}"

    ${prefix}plugged: "${J2O} ${prefix}plugged_raw in ['true', 'True', 'on', '1'] ${J2C}"

    ${prefix}ts: >
      ${J2SO} if ${prefix}plugged_ts_raw not in ['unknown', 'unavailable', '', none] ${J2SC}
        ${J2O} as_timestamp(as_datetime(${prefix}plugged_ts_raw)) ${J2C}
      ${J2SO} else ${J2SC}
        ${J2O} none ${J2C}
      ${J2SO} endif ${J2SC}

    ${prefix}has_gps: >
      ${J2O} ${prefix}lat_raw not in ['unknown', 'unavailable', '', none]
         and ${prefix}lon_raw not in ['unknown', 'unavailable', '', none] ${J2C}

    ${prefix}lat: >
      ${J2SO} if ${prefix}has_gps ${J2SC}
        ${J2O} ${prefix}lat_raw | float(0) ${J2C}
      ${J2SO} else ${J2SC}
        ${J2O} none ${J2C}
      ${J2SO} endif ${J2SC}

    ${prefix}lon: >
      ${J2SO} if ${prefix}has_gps ${J2SC}
        ${J2O} ${prefix}lon_raw | float(0) ${J2C}
      ${J2SO} else ${J2SC}
        ${J2O} none ${J2C}
      ${J2SO} endif ${J2SC}

    ${prefix}delta: >
      ${J2SO} if connect_ts is not none and ${prefix}ts is not none ${J2SC}
        ${J2O} (connect_ts - ${prefix}ts) | abs ${J2C}
      ${J2SO} else ${J2SC}
        ${J2O} 999999 ${J2C}
      ${J2SO} endif ${J2SC}

    ${prefix}distance_m: >
      ${J2SO} if ${prefix}has_gps ${J2SC}
        ${J2O} distance(${prefix}lat, ${prefix}lon, home_lat, home_lon) * 1000 ${J2C}
      ${J2SO} else ${J2SC}
        ${J2O} 999999 ${J2C}
      ${J2SO} endif ${J2SC}

    ${prefix}match: >
      ${J2O} ${prefix}plugged
         and ${prefix}ts is not none
         and ${prefix}delta | float(999999) < 300
         and ${prefix}distance_m | float(999999) < 300 ${J2C}`;
  }).join(`

`);
  const matchConditions = helperCards.map((card, index) => `      ${J2SO} if v${index+1}_match and v${index+1}_delta | float(999999) < ns.delta ${J2SC}
        ${J2SO} set ns.vehicle = v${index+1}_vehicle ${J2SC}
        ${J2SO} set ns.delta = v${index+1}_delta | float(999999) ${J2SC}
      ${J2SO} endif ${J2SC}`).join(`
`);
  const logDetails = helperCards.map((card, index) => `          ${yamlEscape(card.label || card.license_plate || card.id || ('Vehicle ' + (index+1)))}: plugged='${J2O} v${index+1}_plugged ${J2C}' ts='${J2O} v${index+1}_ts ${J2C}' delta='${J2O} v${index+1}_delta ${J2C}'
          dist='${J2O} v${index+1}_distance_m | round(1) ${J2C}m' match='${J2O} v${index+1}_match ${J2C}'`).join(`
`);
  return `##########################################
########## EVCC AUTOMATISIERUNG ##########
##########################################

- alias: Daheimladen Start HA Fahrzeugentscheidung
  id: daheimladen_start_ha_vehicle_decision
  mode: restart

  trigger:
    - platform: state
      entity_id: sensor.evcc_loadpoint_1_connected
      to: "true"

  variables:
    ##################################################
    # Homezone: Standort der Wallbox einsetzen
    # Hier deine Home-Assistant-Zone oder feste Koordinaten eintragen
    # Beispiel Zone:
    # home_lat: "${J2O} state_attr('zone.home', 'latitude') | float(0) ${J2C}"
    # home_lon: "${J2O} state_attr('zone.home', 'longitude') | float(0) ${J2C}"
    ##################################################
    ${homezoneComment}
    home_lat: "${homeLatValue}"
    home_lon: "${homeLonValue}"
    connect_ts: "${J2O} as_timestamp(states.sensor.evcc_loadpoint_1_connected.last_updated) ${J2C}"

${cardVars}

    matched_vehicle: >
      ${J2SO} set ns = namespace(vehicle='unknown', delta=999999) ${J2SC}
${matchConditions}
      ${J2O} ns.vehicle ${J2C}

  action:
    - service: system_log.write
      data:
        level: warning
        message: >
          [HA DECISION]
          connect_ts='${J2O} connect_ts ${J2C}'
${logDetails}
          matched='${J2O} matched_vehicle ${J2C}'

    - if:
        - condition: template
          value_template: "${J2O} matched_vehicle != 'unknown' ${J2C}"
      then:
        - service: script.daheimladen_force_evcc_vehicle
          data:
            vehicle: "${J2O} matched_vehicle ${J2C}"`;
}
function buildHelperScriptsYamlTemplate(){
  const J2O = "{{ '{{' }}";
  const J2C = "{{ '}}' }}";
  return `##########################################
########## DAHEIMLADEN SCRIPTS ###########
##########################################

daheimladen_force_evcc_vehicle:
  alias: Daheimladen - Fahrzeug hart in evcc setzen
  mode: queued
  max: 20
  fields:
    vehicle:
      description: Fahrzeugname
      example: Fahrzeugname aus Automation

  sequence:
    - variables:
        car: "${J2O} vehicle | default('unknown') ${J2C}"

    - if:
        - condition: template
          value_template: "${J2O} car not in ['', 'unknown', 'unavailable', none] ${J2C}"
      then:
        - service: mqtt.publish
          data:
            topic: "evcc/loadpoints/1/vehicle/set"
            payload: ""
            qos: 1
            retain: false

        - service: mqtt.publish
          data:
            topic: "evcc/loadpoints/1/vehicle/set"
            payload: "${J2O} car ${J2C}"
            qos: 1
            retain: false

        - service: mqtt.publish
          data:
            topic: "evcc/loadpoints/1/vehicle/set"
            payload: "${J2O} car ${J2C}"
            qos: 1
            retain: false

        - service: mqtt.publish
          data:
            topic: "evcc/loadpoints/1/vehicle/set"
            payload: "${J2O} car ${J2C}"
            qos: 1
            retain: false`;
}

function buildEvccCustomTemplate(){
  const { id, title, capacity, topicBase, onIdentifyMode } = getCopyConfigContext();
  return `###########################################
###### CAR2MQTT Custom EVCC Template ######
###########################################

title: ${yamlEscape(title)} #<- Angezeigter Fahrzeugname
capacity: ${capacity || '0'} #<- Auf die Batteriekapazität anpassen
phases: 3 #<- Wieviele Phasen werden verwendet 1,3 zulässig
icon: car
identifiers:
  - ${id}
soc:
  source: mqtt
  topic: ${topicBase}/soc
  timeout: 24h

onIdentify: #<- genau ein Lademodus aktiv
  mode: ${onIdentifyMode} # off=Aus, pv=PV, minpv=Min+PV, now=Schnell

range:
  source: mqtt
  topic: ${topicBase}/range
  timeout: 24h

odometer:
  source: mqtt
  topic: ${topicBase}/odometer
  timeout: 24h

limitsoc:
  source: mqtt
  topic: ${topicBase}/limitSoc
  timeout: 24h

status:
  source: combined
  plugged:
    source: mqtt
    topic: ${topicBase}/plugged
    timeout: 24h
  charging:
    source: mqtt
    topic: ${topicBase}/charging
    timeout: 24h
`;
}
function buildConfigurationYamlTemplate(){
  const { manufacturerPrefix, id, rawPlate, title, topicBase, entityBase } = getCopyConfigContext();
  const displayManufacturer = manufacturerPrefix.toUpperCase();
  return `#######################################
## ${rawPlate} ${title} ##
#######################################

    - name: "Car ${displayManufacturer} ${id} Plugged TS"
      unique_id: ${entityBase}_plugged_ts
      state_topic: "${topicBase}/plugged_ts"
      availability_topic: "evcc/status"
      payload_available: "online"
      payload_not_available: "offline"

    - name: "Car ${displayManufacturer} ${id} Plugged"
      unique_id: ${entityBase}_plugged
      state_topic: "${topicBase}/plugged"
      availability_topic: "evcc/status"
      payload_available: "online"
      payload_not_available: "offline"

    - name: "Car ${displayManufacturer} ${id} Latitude"
      unique_id: ${entityBase}_latitude
      state_topic: "${topicBase}/latitude"
      availability_topic: "evcc/status"
      payload_available: "online"
      payload_not_available: "offline"

    - name: "Car ${displayManufacturer} ${id} Longitude"
      unique_id: ${entityBase}_longitude
      state_topic: "${topicBase}/longitude"
      availability_topic: "evcc/status"
      payload_available: "online"
      payload_not_available: "offline"`;
}
function buildAutomationsYamlTemplate(){
  const { entityBase, title, varPrefix } = getCopyConfigContext();
  const J2O = "{{ '{{' }}";
  const J2C = "{{ '}}' }}";
  const J2SO = "{{ '{%' }}";
  const J2SC = "{{ '%}' }}";
  return `    ##################################################
    # ${title}
    ##################################################
    ${varPrefix}vehicle: "${yamlEscape(title)}"
    ${varPrefix}plugged_raw: "${J2O} states('sensor.${entityBase}_plugged') ${J2C}"
    ${varPrefix}plugged_ts_raw: "${J2O} states('sensor.${entityBase}_plugged_ts') ${J2C}"
    ${varPrefix}lat_raw: "${J2O} states('sensor.${entityBase}_latitude') ${J2C}"
    ${varPrefix}lon_raw: "${J2O} states('sensor.${entityBase}_longitude') ${J2C}"

    ${varPrefix}plugged: "${J2O} ${varPrefix}plugged_raw in ['true', 'True', 'on', '1'] ${J2C}"

    ${varPrefix}ts: >
      ${J2SO} if ${varPrefix}plugged_ts_raw not in ['unknown', 'unavailable', '', none] ${J2SC}
        ${J2O} as_timestamp(as_datetime(${varPrefix}plugged_ts_raw)) ${J2C}
      ${J2SO} else ${J2SC}
        ${J2O} none ${J2C}
      ${J2SO} endif ${J2SC}

    ${varPrefix}has_gps: >
      ${J2O} ${varPrefix}lat_raw not in ['unknown', 'unavailable', '', none]
         and ${varPrefix}lon_raw not in ['unknown', 'unavailable', '', none] ${J2C}

    ${varPrefix}lat: >
      ${J2SO} if ${varPrefix}has_gps ${J2SC}
        ${J2O} ${varPrefix}lat_raw | float(0) ${J2C}
      ${J2SO} else ${J2SC}
        ${J2O} none ${J2C}
      ${J2SO} endif ${J2SC}

    ${varPrefix}lon: >
      ${J2SO} if ${varPrefix}has_gps ${J2SC}
        ${J2O} ${varPrefix}lon_raw | float(0) ${J2C}
      ${J2SO} else ${J2SC}
        ${J2O} none ${J2C}
      ${J2SO} endif ${J2SC}

    ${varPrefix}delta: >
      ${J2SO} if connect_ts is not none and ${varPrefix}ts is not none ${J2SC}
        ${J2O} (connect_ts - ${varPrefix}ts) | abs ${J2C}
      ${J2SO} else ${J2SC}
        ${J2O} 999999 ${J2C}
      ${J2SO} endif ${J2SC}

    ${varPrefix}distance_m: >
      ${J2SO} if ${varPrefix}lat is not none and ${varPrefix}lon is not none and home_lat != 0 and home_lon != 0 ${J2SC}
        ${J2SO} set pi = 3.141592653589793 ${J2SC}
        ${J2SO} set r = 6371000 ${J2SC}
        ${J2SO} set lat1 = home_lat * pi / 180 ${J2SC}
        ${J2SO} set lon1 = home_lon * pi / 180 ${J2SC}
        ${J2SO} set lat2 = ${varPrefix}lat * pi / 180 ${J2SC}
        ${J2SO} set lon2 = ${varPrefix}lon * pi / 180 ${J2SC}
        ${J2SO} set dlat = lat2 - lat1 ${J2SC}
        ${J2SO} set dlon = lon2 - lon1 ${J2SC}
        ${J2SO} set a = (sin(dlat / 2) ** 2) + cos(lat1) * cos(lat2) * (sin(dlon / 2) ** 2) ${J2SC}
        ${J2SO} set c = 2 * atan2(sqrt(a), sqrt(1 - a)) ${J2SC}
        ${J2O} r * c ${J2C}
      ${J2SO} else ${J2SC}
        ${J2O} 999999 ${J2C}
      ${J2SO} endif ${J2SC}

    ${varPrefix}match: >
      ${J2O} ${varPrefix}plugged
         and (${varPrefix}delta | float(999999) <= 20)
         and (${varPrefix}distance_m | float(999999) <= 100) ${J2C}`;
}
async function copyTextRobust(content){
  if(navigator.clipboard){
    try{
      await navigator.clipboard.writeText(content);
      return true;
    }catch(err){}
  }
  try{
    const ta = document.createElement('textarea');
    ta.value = content;
    ta.setAttribute('readonly','');
    ta.style.position = 'fixed';
    ta.style.top = '0';
    ta.style.left = '0';
    ta.style.width = '1px';
    ta.style.height = '1px';
    ta.style.opacity = '0.01';
    ta.style.zIndex = '99999';
    document.body.appendChild(ta);
    ta.focus();
    ta.select();
    ta.setSelectionRange(0, ta.value.length);
    const ok = document.execCommand('copy');
    document.body.removeChild(ta);
    if(ok) return true;
  }catch(err){}
  return false;
}
function copyCurrentCarToEvcc(){
  try{
    openEvccConfigDialog();
  }catch(err){
    alert('Konfigurationen konnten nicht erzeugt werden: ' + (err.message || err));
  }
}

function showNotice(id, msg='') { const el = field(id); el.textContent = msg; el.style.display = msg ? 'block' : 'none'; }
function statusLabel(v){ if(v === 'reauth_required') return 'REAUTH REQUIRED'; if(v === 'remote') return 'REMOTE'; return v || 'idle'; }
function yesNo(v){ return v === true ? 'ja' : (v === false ? 'nein' : '—'); }
function metric(v,s=''){ return v === null || v === undefined || v === '' ? '—' : `${v}${s}`; }
function setGwmVerifyVisibility(show, autoOpen=false){
  editState.needsVerification = !!show;
  const panel = field('gwmVerifyPanel');
  const hint = field('gwmVerifyHint');
  const isGwm = (field('editManufacturer')?.value === 'gwm');
  if(!panel) return;
  panel.classList.toggle('hidden', !isGwm);
  if(hint){
    hint.textContent = show ? 'Code erforderlich' : 'Optional';
    hint.classList.toggle('chip-warn', !!show);
  }
}

function vehicleMetricsHtml(card){
  const vt = String(card.metrics?.vehicleType || '').toLowerCase() || (String(card.manufacturer || '').toUpperCase() === 'GWM' ? 'ev' : 'ev');
  if(vt === 'combustion'){
    return `<div class="vehicle-metrics"><div class="metric"><span>Tankinhalt</span><strong>${metric(card.metrics.fuelLevel,' %')}</strong></div><div class="metric"><span>Restreichweite</span><strong>${metric(card.metrics.fuelRange,' km')}</strong></div><div class="metric"><span>Kilometer</span><strong>${metric(card.metrics.odometer,' km')}</strong></div><div class="metric"><span>Antrieb</span><strong>Verbrenner</strong></div></div>`;
  }
  if(vt === 'hybrid'){
    return `<div class="vehicle-metrics"><div class="metric"><span>SoC</span><strong>${metric(card.metrics.soc,' %')}</strong></div><div class="metric"><span>E-Reichweite</span><strong>${metric(card.metrics.range,' km')}</strong></div><div class="metric"><span>Lädt</span><strong>${yesNo(card.metrics.charging)}</strong></div><div class="metric"><span>Angesteckt</span><strong>${yesNo(card.metrics.plugged)}</strong></div><div class="metric"><span>Kilometer</span><strong>${metric(card.metrics.odometer,' km')}</strong></div><div class="metric"><span>Ladelimit</span><strong>${metric(card.metrics.limitSoc,' %')}</strong></div><div class="metric"><span>Tankinhalt</span><strong>${metric(card.metrics.fuelLevel,' %')}</strong></div><div class="metric"><span>Restreichweite</span><strong>${metric(card.metrics.fuelRange,' km')}</strong></div></div>`;
  }
  return `<div class="vehicle-metrics"><div class="metric"><span>SoC</span><strong>${metric(card.metrics.soc,' %')}</strong></div><div class="metric"><span>Reichweite</span><strong>${metric(card.metrics.range,' km')}</strong></div><div class="metric"><span>Lädt</span><strong>${yesNo(card.metrics.charging)}</strong></div><div class="metric"><span>Angesteckt</span><strong>${yesNo(card.metrics.plugged)}</strong></div><div class="metric"><span>Kilometer</span><strong>${metric(card.metrics.odometer,' km')}</strong></div><div class="metric"><span>Ladelimit</span><strong>${metric(card.metrics.limitSoc,' %')}</strong></div></div>`;
}

function cardHtml(card){
  return `<article class="vehicle-card"><div class="vehicle-head"><div><div class="vehicle-title">${card.label}</div><div class="vehicle-subtitle">${card.manufacturer} · ${card.license_plate}</div></div><span class="status-badge ${card.status}">${statusLabel(card.status)}</span></div>${vehicleMetricsHtml(card)}<div class="card-footer"><div>${card.enabled === false ? 'Fahrzeug inaktiv — kein Remote-Login und kein Streaming.' : (card.status_detail || '')}</div><div class="topic-row">raw: ${card.topic}</div><div class="topic-row">mapped: ${card.mapped_topic}</div>${card.live?.mqtt_username ? `<div class="topic-row">BMW MQTT Username: ${card.live.mqtt_username}</div>` : ''}<div class="muted">${card.last_update || 'Noch keine Live-Daten'}</div><div class="card-actions"><button class="tiny-btn" onclick="editVehicle('${card.id}')">Bearbeiten</button>${card.remote ? '' : `<button class="danger-btn" onclick="deleteVehicle('${card.id}')">Löschen</button>`}</div></div></article>`;
}
function renderCards(){ field('cardsGrid').innerHTML = cards.map(cardHtml).join('') + `<button class="add-card" id="openWizardBtn"><span>＋</span><strong>Fahrzeug hinzufügen</strong></button>`; field('openWizardBtn').onclick = openWizard; }
function renderProviderList(){ const select = field('createManufacturer'); select.innerHTML = `<option value="">Bitte Hersteller wählen</option>` + providers.map(provider => `<option value="${provider.id}">${provider.name}</option>`).join(''); select.value = createState.manufacturer || ''; }
function fillManufacturerSelect(){ field('editManufacturer').innerHTML = providers.map(p => `<option value="${p.id}">${p.name}</option>`).join(''); }
const VAG_MANUFACTURERS = ['vw','vwcv','audi','skoda','seat','cupra','vag','byd','hyundai','mg','citroen','kia','lucid','mercedes','nissan','opel','peugeot','renault','tesla','toyota','volvo'];
function isVagManufacturer(manufacturer){ return VAG_MANUFACTURERS.includes(String(manufacturer || '').toLowerCase()); }

function setCreateManufacturerLayout(manufacturer){
  const note = field('createManufacturerNote');
  const isBmw = manufacturer === 'bmw';
  const isGwm = manufacturer === 'gwm';
  const isAcconia = manufacturer === 'acconia';
  const isVag = isVagManufacturer(manufacturer);
  if(isVag){ const api = field('vagApiMode'); if(api){ const defaults = {byd:'byd_cloud', hyundai:'bluelink', mg:'ismart', kia:'kia_connect', lucid:'lucid_community', mercedes:'mercedes_me', citroen:'stellantis_connected_car', opel:'stellantis_connected_car', peugeot:'stellantis_connected_car', renault:'myrenault', tesla:'tesla_fleet_api', toyota:'mytoyota', volvo:'volvo_connected_vehicle', nissan:'nissanconnect'}; const wanted = defaults[manufacturer] || 'brand_app'; if(api.value !== wanted) api.value = wanted; } }
  field('bmwHowtoCreateBtn')?.classList.toggle('hidden', !isBmw);
  field('bmwCreateSection').classList.toggle('hidden', !isBmw);
  field('gwmCreateSection').classList.toggle('hidden', !isGwm);
  field('acconiaCreateSection').classList.toggle('hidden', !isAcconia);
  field('vagCreateSection')?.classList.toggle('hidden', !isVag);
  if(note){
    if(!manufacturer){ note.textContent = ''; }
    else{
      const provider = providers.find(p => p.id === manufacturer);
      note.textContent = provider?.notes || '';
    }
  }
}

function toggleCreateSections(){ createState.manufacturer = field('createManufacturer').value || null; setCreateManufacturerLayout(createState.manufacturer); }

function setEditManufacturerLayout(manufacturer){
  const isBmw = manufacturer === 'bmw';
  const isGwm = manufacturer === 'gwm';
  const isAcconia = manufacturer === 'acconia';
  const isVag = isVagManufacturer(manufacturer);
  if(isVag){ const api = field('editVagApiMode'); if(api){ const defaults = {byd:'byd_cloud', hyundai:'bluelink', mg:'ismart', kia:'kia_connect', lucid:'lucid_community', mercedes:'mercedes_me', citroen:'stellantis_connected_car', opel:'stellantis_connected_car', peugeot:'stellantis_connected_car', renault:'myrenault', tesla:'tesla_fleet_api', toyota:'mytoyota', volvo:'volvo_connected_vehicle', nissan:'nissanconnect'}; const wanted = defaults[manufacturer] || 'brand_app'; if(api.value !== wanted) api.value = wanted; } }
  const editLabelWrap = field('editLabel')?.closest('.field');
  const editPlateWrap = field('editPlate')?.closest('.field');
  if(editLabelWrap) editLabelWrap.style.display = '';
  if(editPlateWrap) editPlateWrap.style.display = '';
  field('editBmwSection')?.classList.toggle('hidden', !isBmw);
  field('editGwmSection')?.classList.toggle('hidden', !isGwm);
  field('editAcconiaSection')?.classList.toggle('hidden', !isAcconia);
  field('editVagSection')?.classList.toggle('hidden', !isVag);
  field('bmwHowtoBtn')?.classList.toggle('hidden', !isBmw);
  const verifyPanel = field('gwmVerifyPanel');
  if(verifyPanel){
    verifyPanel.classList.toggle('hidden', !isGwm);
  }
}

function toggleEditSections(){ const man = field('editManufacturer').value; setEditManufacturerLayout(man); }
function toggleBmwReconnectMode(){
  const auto = field('editBmwAutoReconnect')?.checked;
  const wrap = field('editBmwManualReconnectWrap');
  if(wrap) wrap.classList.toggle('hidden', !!auto);
}

function toggleCreateGwmOptions(){
  const pollingEnabled = field('gwmPollingEnabled')?.checked;
  const delayedRetryEnabled = field('gwmDelayedRetryEnabled')?.checked;
  field('gwmPollIntervalWrap')?.classList.toggle('hidden', !pollingEnabled);
  field('gwmRetryDelayWrap')?.classList.toggle('hidden', !delayedRetryEnabled);
}
function toggleEditGwmOptions(){
  const pollingEnabled = field('editGwmPollingEnabled')?.checked;
  const delayedRetryEnabled = field('editGwmDelayedRetryEnabled')?.checked;
  field('editGwmPollIntervalWrap')?.classList.toggle('hidden', !pollingEnabled);
  field('editGwmRetryDelayWrap')?.classList.toggle('hidden', !delayedRetryEnabled);
}
function resetCreate(){ createState.manufacturer=null; createState.authSessionId=null; createState.authReady=false; ['vehicleLabel','vehiclePlate','bmwClientId','bmwMqttUsername','bmwVin','gwmAccount','gwmPassword','gwmVehicleId','gwmCapacity','gwmVerificationCode','acconiaAccount','acconiaPassword','acconiaApiKey','acconiaCapacity','vagAccount','vagPassword','vagPin','vagCapacity'].forEach(id=>field(id).value=''); field('gwmSourceTopicBase').value='GWM'; field('acconiaBatteryCount').value='2'; field('acconiaPollInterval').value='60'; field('vagApiMode').value='brand_app'; field('vagCountry').value='DE'; field('vagPowertrain').value='unknown'; field('vagPollInterval').value='60'; field('bmwRegion').value='EU'; field('gwmCountry').value='DE'; field('gwmLanguage').value='de'; field('gwmPollInterval').value='60'; field('gwmPollingEnabled').checked=true; field('gwmAutoReconnect').checked=true; field('gwmDelayedRetryEnabled').checked=true; field('gwmRetryDelayMinutes').value='55'; field('gwmFallbackOnSilence').checked=true; field('createDeviceTrackerEnabled').checked=false; toggleCreateGwmOptions(); field('authState').textContent='Noch nicht gestartet.'; field('authInfo').classList.add('hidden'); showNotice('wizardError'); renderProviderList(); field('createManufacturer').value=''; setCreateManufacturerLayout(null); }
function openWizard(){ resetCreate(); field('wizardDialog').showModal(); }
async function loadDashboard(){ const res = await fetch('./api/dashboard'); const data = await res.json(); cards = data.vehicles || []; renderCards(); }
function errorTextFromResponsePayload(data){
  const detail = data && Object.prototype.hasOwnProperty.call(data, 'detail') ? data.detail : data;
  if(typeof detail === 'string') return detail;
  if(Array.isArray(detail)) return detail.map(x => (typeof x === 'string' ? x : (x && x.msg) ? x.msg : JSON.stringify(x))).join('\n');
  if(detail && typeof detail === 'object'){
    if(detail.message) return String(detail.message);
    if(detail.error) return String(detail.error);
    try{ return JSON.stringify(detail, null, 2); }catch{ return String(detail); }
  }
  return 'Unbekannter Fehler';
}
async function postJson(url,payload,method='POST'){ const res = await fetch(url,{method,headers:{'Content-Type':'application/json'},body:JSON.stringify(payload||{})}); const text = await res.text(); let data={}; try{ data = text ? JSON.parse(text) : {}; }catch{ data = { detail: text }; } if(!res.ok) throw new Error(errorTextFromResponsePayload(data)); return data; }
async function fetchText(url){ const res = await fetch(url); const text = await res.text(); if(!res.ok) throw new Error(text || 'Unbekannter Fehler'); return text; }

field('closeWizardBtn').onclick = field('cancelWizardBtn').onclick = () => field('wizardDialog').close();

function openBmwHowtoDialog(){
  const dlg = field('bmwHowtoDialog');
  if(!dlg) return;
  try{
    dlg.showModal();
  }catch(e){
    dlg.setAttribute('open','open');
    dlg.style.display='flex';
  }
}
function closeBmwHowtoDialog(){
  const dlg = field('bmwHowtoDialog');
  if(!dlg) return;
  try{
    dlg.close();
  }catch(e){
    dlg.removeAttribute('open');
    dlg.style.display='none';
  }
}
const bmwHowtoBtn = field('bmwHowtoBtn');
if(bmwHowtoBtn) bmwHowtoBtn.onclick = (ev)=>{ ev.preventDefault(); openBmwHowtoDialog(); };
const bmwHowtoCreateBtn = field('bmwHowtoCreateBtn');
if(bmwHowtoCreateBtn) bmwHowtoCreateBtn.onclick = (ev)=>{ ev.preventDefault(); openBmwHowtoDialog(); };
const closeBmwHowtoBtn = field('closeBmwHowtoBtn');
if(closeBmwHowtoBtn) closeBmwHowtoBtn.onclick = (ev)=>{ ev.preventDefault(); closeBmwHowtoDialog(); };
const closeBmwHowtoBottomBtn = field('closeBmwHowtoBottomBtn');
if(closeBmwHowtoBottomBtn) closeBmwHowtoBottomBtn.onclick = (ev)=>{ ev.preventDefault(); closeBmwHowtoDialog(); };
const evccConfigBtn = field('copyConfigsBtn');
if(evccConfigBtn) evccConfigBtn.onclick = (ev)=>{ ev.preventDefault(); openEvccConfigDialog(); };
const closeEvccConfigBtn = field('closeEvccConfigBtn');
if(closeEvccConfigBtn) closeEvccConfigBtn.onclick = (ev)=>{ ev.preventDefault(); closeEvccConfigDialog(); };
const closeEvccConfigBottomBtn = field('closeEvccConfigBottomBtn');
if(closeEvccConfigBottomBtn) closeEvccConfigBottomBtn.onclick = (ev)=>{ ev.preventDefault(); closeEvccConfigDialog(); };
const copyEvccSectionBtn = field('copyEvccSectionBtn');
if(copyEvccSectionBtn) copyEvccSectionBtn.onclick = async (ev)=>{ ev.preventDefault(); await copyTextRobust(field('evccConfigTextarea')?.value || ''); };
const copyConfigurationSectionBtn = field('copyConfigurationSectionBtn');
if(copyConfigurationSectionBtn) copyConfigurationSectionBtn.onclick = async (ev)=>{ ev.preventDefault(); await copyTextRobust(field('configurationConfigTextarea')?.value || ''); };
const copyAutomationsSectionBtn = field('copyAutomationsSectionBtn');
if(copyAutomationsSectionBtn) copyAutomationsSectionBtn.onclick = async (ev)=>{ ev.preventDefault(); await copyTextRobust(field('automationsConfigTextarea')?.value || ''); };
const settingsBtn = field('settingsBtn');
if(settingsBtn) settingsBtn.onclick = (ev)=>{ ev.preventDefault(); openSettingsDialog(); };
const mqttClientsBtn = field('mqttClientsBtn');
if(mqttClientsBtn) mqttClientsBtn.onclick = (ev)=>{ ev.preventDefault(); openMqttClientsDialog(); };
const closeSettingsBtn = field('closeSettingsBtn');
if(closeSettingsBtn) closeSettingsBtn.onclick = (ev)=>{ ev.preventDefault(); closeSettingsDialog(); };
const closeSettingsBottomBtn = field('closeSettingsBottomBtn');
if(closeSettingsBottomBtn) closeSettingsBottomBtn.onclick = (ev)=>{ ev.preventDefault(); closeSettingsDialog(); };
const saveSettingsBtn = field('saveSettingsBtn');
if(saveSettingsBtn) saveSettingsBtn.onclick = async (ev)=>{
  ev.preventDefault();
  try{
    const select = field('settingsHomeZoneSelect');
    const trackerToggle = field('settingsDeviceTrackerEnabled');
    const resp = await postJson('api/settings/homezone', { helper_home_zone_entity_id: select ? select.value : '', device_tracker_enabled: !!(trackerToggle && trackerToggle.checked), ha_discovery_enabled: !!field('settingsHaDiscoveryEnabled')?.checked, ha_discovery_prefix: field('settingsHaDiscoveryPrefix')?.value || 'homeassistant', ha_discovery_retain: !!field('settingsHaDiscoveryRetain')?.checked, evcc_enabled: !!field('settingsEvccEnabled')?.checked, evcc_url: field('settingsEvccUrl')?.value || 'http://localhost:7070', evcc_password: field('settingsEvccPassword')?.value || '', evcc_auto_create: !!field('settingsEvccAutoCreate')?.checked, evcc_auto_update: !!field('settingsEvccAutoUpdate')?.checked, evcc_auto_delete: !!field('settingsEvccAutoDelete')?.checked, evcc_db_path: field('settingsEvccDbPath')?.value || '/data/evcc.db' });
    uiSettings = resp.ui_settings || {};
    helperHomezoneJson = resp.effective_homezone || helperHomezoneJson;
    const info = field('settingsHomeZoneInfo');
    if(info) info.textContent = describeHomezone(helperHomezoneJson);
    closeSettingsDialog();
  }catch(err){
    alert(err.message || 'Einstellungen konnten nicht gespeichert werden.');
  }
};
async function publishAllHaDiscovery(){
  try{
    const data = await postJson('./api/ha-discovery/publish', {});
    const el = field('settingsEvccStatus'); if(el) el.textContent = `Home Assistant Discovery veröffentlicht: ${data.published || 0} Entitäten.`;
  }catch(err){ alert(err.message || 'Discovery konnte nicht veröffentlicht werden.'); }
}
async function testEvccConnection(){
  try{
    const data = await postJson('./api/evcc/test', {});
    const el = field('settingsEvccStatus'); if(el) el.textContent = `EVCC OK. Fahrzeuge gefunden: ${(data.vehicles || []).length}${data.version ? ' · Version: '+data.version : ''}`;
  }catch(err){ const el = field('settingsEvccStatus'); if(el) el.textContent = err.message || 'EVCC Test fehlgeschlagen.'; }
}
async function loadEvccVehiclesStatus(){
  try{
    const res = await fetch('./api/evcc/vehicles'); const data = await res.json(); if(!res.ok) throw new Error(errorTextFromResponsePayload(data));
    const names = (data.vehicles || []).map(v => `${v.title || v.name || v.ref} (${v.ref || v.name || '-'})`).join(', ');
    const el = field('settingsEvccStatus'); if(el) el.textContent = names ? `EVCC Fahrzeuge: ${names}` : 'Keine EVCC Fahrzeuge gefunden.';
  }catch(err){ const el = field('settingsEvccStatus'); if(el) el.textContent = err.message || 'EVCC Fahrzeuge konnten nicht geladen werden.'; }
}
async function checkEvccDbStatus(){
  try{
    const data = await postJson('./api/evcc/db/check', {});
    const tableNames = (data.tables || []).map(t => `${t.name}(${t.count ?? '?'})`).join(', ');
    const candidateNames = (data.candidates || []).map(t => t.name).join(', ');
    const el = field('settingsEvccStatus');
    if(el){
      const auto = data.used_auto_path ? ` · Auto-Pfad genutzt statt ${data.requested_path || ''}` : '';
      const found = (data.found_paths || []).length ? ` · Gefunden: ${(data.found_paths || []).join(', ')}` : '';
      const docker = data.docker_snapshot && data.docker_snapshot.snapshot_path ? ` · Docker-Snapshot aus EVCC-Container: ${data.docker_snapshot.snapshot_path}` : (data.docker_snapshot && data.docker_snapshot.error ? ` · Docker-Fallback: ${data.docker_snapshot.error}` : "");
      const seen = data.docker_snapshot && data.docker_snapshot.containers_seen ? ` · Docker-Container gesehen: ${data.docker_snapshot.containers_seen.map(c => `${(c.names||[]).join("/") || c.id}:${c.image}`).join(", ") || "-"}` : "";
      const tried = data.docker_snapshot && data.docker_snapshot.remote_paths_tried ? ` · Pfade versucht: ${data.docker_snapshot.remote_paths_tried.join(", ")}` : "";
      el.textContent = data.exists ? `EVCC DB OK: ${data.path}${auto}${docker} · Tabellen: ${tableNames || "keine"}${candidateNames ? " · Kandidaten: " + candidateNames : ""}` : `EVCC DB nicht gefunden: ${data.path}${found}${docker}${seen}${tried}`;
    }
  }catch(err){ const el = field('settingsEvccStatus'); if(el) el.textContent = err.message || 'EVCC DB Prüfung fehlgeschlagen.'; }
}
async function backupEvccDbStatus(){
  try{
    const data = await postJson('./api/evcc/db/backup', {});
    const el = field('settingsEvccStatus'); if(el) el.textContent = `EVCC DB Backup erstellt: ${data.backup || 'ok'}${data.used_auto_path ? ' · Quelle automatisch gefunden: '+data.source : ''}`;
  }catch(err){ const el = field('settingsEvccStatus'); if(el) el.textContent = err.message || 'EVCC DB Backup fehlgeschlagen.'; }
}
async function syncCurrentVehicleToEvcc(){
  if(!editState.vehicleId) return;
  try{
    await postJson(`./api/vehicles/${editState.vehicleId}/evcc/config`, collectEvccVehicleConfigPayload());
    await loadDashboard();
    const data = await postJson(`./api/vehicles/${editState.vehicleId}/evcc/sync`, {});
    alert(`EVCC Sync erfolgreich: ${data.result?.action || 'ok'} ${data.result?.ref || ''}`);
    await loadDashboard(); await refreshVehicleLogs();
  }catch(err){ alert(err.message || 'EVCC Sync fehlgeschlagen.'); }
}
async function publishCurrentVehicleDiscovery(){
  if(!editState.vehicleId) return;
  try{
    const data = await postJson(`./api/vehicles/${editState.vehicleId}/ha-discovery/publish`, {});
    alert(`Home Assistant Discovery veröffentlicht: ${data.published || 0} Entitäten.`);
  }catch(err){ alert(err.message || 'Discovery fehlgeschlagen.'); }
}
async function saveCurrentEvccVehicleConfig(closeAfter=false){
  if(!editState.vehicleId) return false;
  try{
    const data = await postJson(`./api/vehicles/${editState.vehicleId}/evcc/config`, collectEvccVehicleConfigPayload());
    if(data.remote){
      alert('Lokale EVCC-Zuordnung gespeichert. EVCC ID und onIdentify bleiben lokal auf dieser Instanz.');
    }else{
      alert(`EVCC/MQTT-Konfiguration gespeichert. MQTT Topics veröffentlicht: ${data.published || 0}`);
    }
    await loadDashboard();
    const updated = getCurrentEditCard();
    if(updated) fillEvccVehicleConfigFields(updated);
    await refreshVehicleLogs();
    if(closeAfter){ stopLiveLogs(); field('editDialog').close(); }
    return true;
  }catch(err){ alert(err.message || 'EVCC/MQTT-Konfiguration konnte nicht gespeichert werden.'); return false; }
}
async function linkCurrentVehicleToEvcc(){
  if(!editState.vehicleId) return;
  let options = [];
  try{ const res = await fetch('./api/evcc/vehicles'); const data = await res.json(); if(res.ok) options = data.vehicles || []; }catch(err){}
  const hint = options.length ? '\n\nGefundene EVCC Fahrzeuge:\n' + options.map(v => `${v.ref || v.name || '-'} = ${v.title || v.name || ''}`).join('\n') : '\n\nKeine bestehenden EVCC-Fahrzeuge per API gefunden.';
  const ref = prompt('EVCC Fahrzeug-ID/Ref eintragen, z. B. db:19. Leer lassen bedeutet: keine ID-Zuordnung ändern.' + hint, field('editEvccRef')?.value || '');
  if(ref === null) return;
  if(!ref.trim()){ return; }
  const card = getCurrentEditCard();
  try{
    field('editEvccRef').value = ref.trim();
    const linkPayload = { evcc_ref: ref.trim(), evcc_managed: true, evcc_auto_sync: true };
    if(!(card && card.remote)){
      linkPayload.evcc_title = card?.label || '';
      linkPayload.evcc_capacity_kwh = card?.metrics?.capacityKwh || '';
    }
    await postJson(`./api/vehicles/${editState.vehicleId}/evcc/link`, linkPayload);
    alert('EVCC Zuordnung gespeichert. Danach kann EVCC Sync ausgeführt werden.');
    await refreshVehicleLogs();
  }catch(err){ alert(err.message || 'EVCC Zuordnung konnte nicht gespeichert werden.'); }
}
const publishHaDiscoveryBtn = field('publishHaDiscoveryBtn');
if(publishHaDiscoveryBtn) publishHaDiscoveryBtn.onclick = (ev)=>{ ev.preventDefault(); publishAllHaDiscovery(); };
const testEvccBtn = field('testEvccBtn');
if(testEvccBtn) testEvccBtn.onclick = (ev)=>{ ev.preventDefault(); testEvccConnection(); };
const loadEvccVehiclesBtn = field('loadEvccVehiclesBtn');
if(loadEvccVehiclesBtn) loadEvccVehiclesBtn.onclick = (ev)=>{ ev.preventDefault(); loadEvccVehiclesStatus(); };
const checkEvccDbBtn = field('checkEvccDbBtn');
if(checkEvccDbBtn) checkEvccDbBtn.onclick = (ev)=>{ ev.preventDefault(); checkEvccDbStatus(); };
const backupEvccDbBtn = field('backupEvccDbBtn');
if(backupEvccDbBtn) backupEvccDbBtn.onclick = (ev)=>{ ev.preventDefault(); backupEvccDbStatus(); };
const evccSyncBtn = field('evccSyncBtn');
if(evccSyncBtn) evccSyncBtn.onclick = (ev)=>{ ev.preventDefault(); syncCurrentVehicleToEvcc(); };
const publishVehicleDiscoveryBtn = field('publishVehicleDiscoveryBtn');
if(publishVehicleDiscoveryBtn) publishVehicleDiscoveryBtn.onclick = (ev)=>{ ev.preventDefault(); publishCurrentVehicleDiscovery(); };
const evccLinkBtn = field('evccLinkBtn');
if(evccLinkBtn) evccLinkBtn.onclick = (ev)=>{ ev.preventDefault(); linkCurrentVehicleToEvcc(); };
const saveEvccVehicleConfigBtn = field('saveEvccVehicleConfigBtn');
if(saveEvccVehicleConfigBtn) saveEvccVehicleConfigBtn.onclick = (ev)=>{ ev.preventDefault(); saveCurrentEvccVehicleConfig(false); };
const helperConfigBtn = field('copyHelperBtn');
if(helperConfigBtn) helperConfigBtn.onclick = (ev)=>{ ev.preventDefault(); openHelperConfigDialog(); };
const closeHelperConfigBtn = field('closeHelperConfigBtn');
if(closeHelperConfigBtn) closeHelperConfigBtn.onclick = (ev)=>{ ev.preventDefault(); closeHelperConfigDialog(); };
const closeHelperConfigBottomBtn = field('closeHelperConfigBottomBtn');
if(closeHelperConfigBottomBtn) closeHelperConfigBottomBtn.onclick = (ev)=>{ ev.preventDefault(); closeHelperConfigDialog(); };
const copyHelperConfigurationSectionBtn = field('copyHelperConfigurationSectionBtn');
if(copyHelperConfigurationSectionBtn) copyHelperConfigurationSectionBtn.onclick = async (ev)=>{ ev.preventDefault(); await copyTextRobust(field('helperConfigurationConfigTextarea')?.value || ''); };
const copyHelperAutomationsSectionBtn = field('copyHelperAutomationsSectionBtn');
if(copyHelperAutomationsSectionBtn) copyHelperAutomationsSectionBtn.onclick = async (ev)=>{ ev.preventDefault(); await copyTextRobust(field('helperAutomationsConfigTextarea')?.value || ''); };
const copyHelperScriptsSectionBtn = field('copyHelperScriptsSectionBtn');
if(copyHelperScriptsSectionBtn) copyHelperScriptsSectionBtn.onclick = async (ev)=>{ ev.preventDefault(); await copyTextRobust(field('helperScriptsConfigTextarea')?.value || ''); };


function openBmwHowto(){
  const dlg = field('bmwHowtoDialog');
  if(!dlg) return;
  try {
    if (typeof dlg.showModal === 'function') dlg.showModal();
    else dlg.setAttribute('open','open');
  } catch (e) {
    dlg.setAttribute('open','open');
  }
}

function openEvccConfigDialog(){
  const dlg = field('evccConfigDialog');
  const evccTa = field('evccConfigTextarea');
  const cfgTa = field('configurationConfigTextarea');
  const autoTa = field('automationsConfigTextarea');
  if(!dlg || !evccTa || !cfgTa || !autoTa) return;
  evccTa.value = buildEvccCustomTemplate();
  cfgTa.value = buildConfigurationYamlTemplate();
  autoTa.value = buildAutomationsYamlTemplate();
  try {
    dlg.showModal();
  } catch(e) {
    dlg.setAttribute('open','open');
    dlg.style.display = 'flex';
  }
}
function closeEvccConfigDialog(){
  const d = field('evccConfigDialog');
  if(d){
    try{ d.close(); }catch(e){ d.removeAttribute('open'); d.style.display = 'none'; }
  }
}
async function openHelperConfigDialog(){
  const dlg = field('helperConfigDialog');
  const cfgTa = field('helperConfigurationConfigTextarea');
  const autoTa = field('helperAutomationsConfigTextarea');
  const scriptsTa = field('helperScriptsConfigTextarea');
  if(!dlg || !cfgTa || !autoTa || !scriptsTa) return;
  cfgTa.value = buildHelperConfigurationYamlTemplate();
  let helperHomezone = helperHomezoneJson || null;
  try {
    const resp = await fetch('api/helper/homezone');
    if(resp.ok) helperHomezone = await resp.json();
  } catch(e) {}
  if(helperHomezone) helperHomezoneJson = helperHomezone;
  autoTa.value = buildHelperAutomationsYamlTemplate(helperHomezone);
  scriptsTa.value = buildHelperScriptsYamlTemplate();
  try {
    dlg.showModal();
  } catch(e) {
    dlg.setAttribute('open','open');
    dlg.style.display = 'flex';
  }
}
function closeHelperConfigDialog(){
  const d = field('helperConfigDialog');
  if(d){
    try{ d.close(); }catch(e){ d.removeAttribute('open'); d.style.display = 'none'; }
  }
}

function closeBmwHowto(){
  const dlg = field('bmwHowtoDialog');
  if(!dlg) return;
  try {
    if (typeof dlg.close === 'function') dlg.close();
    else dlg.removeAttribute('open');
  } catch (e) {
    dlg.removeAttribute('open');
  }
}
field('bmwHowtoBtn').onclick = openBmwHowto;
field('bmwHowtoCreateBtn').onclick = openBmwHowto;
field('closeBmwHowtoBtn').onclick = closeBmwHowto;
field('closeBmwHowtoBottomBtn').onclick = closeBmwHowto;

field('mqttTestBtn').onclick = async()=>{ try{ const d = await postJson('./api/mqtt/test'); alert(`MQTT ok: ${d.topic}`); } catch(err){ alert(err.message); } };
field('startAuthBtn').onclick = async()=>{ showNotice('wizardError'); try{ const d = await postJson('./api/providers/bmw/auth/start',{ client_id: field('bmwClientId').value.trim(), vin: field('bmwVin').value.trim(), license_plate: field('vehiclePlate').value.trim() }); createState.authSessionId = d.session_id; field('authState').textContent = d.message || 'BMW Login-Link erstellt.'; field('userCode').textContent = d.user_code; field('verificationUrl').href = d.verification_uri_complete; field('verificationUrl').textContent = d.verification_uri_complete; field('authInfo').classList.remove('hidden'); window.open(d.verification_uri_complete,'_blank'); } catch(err){ showNotice('wizardError', err.message); } };
field('pollAuthBtn').onclick = async()=>{ if(!createState.authSessionId) return showNotice('wizardError','Bitte zuerst Login-Link erzeugen.'); try{ const d = await postJson('./api/providers/bmw/auth/poll',{ session_id: createState.authSessionId }); if(d.state === 'authorized'){ createState.authReady = true; field('authState').textContent = 'BMW erfolgreich verbunden.'; } else { field('authState').textContent = d.message || d.state; } } catch(err){ showNotice('wizardError', err.message); } };
field('saveCreateBtn').onclick = async()=>{
  try{
    if(!createState.manufacturer) throw new Error('Bitte Hersteller auswählen.');
    if(!field('vehicleLabel').value.trim() || !field('vehiclePlate').value.trim()) throw new Error('Bitte Anzeigename und Kennzeichen ausfüllen.');
    const derivedId = normalizeVehicleIdFromPlate(field('vehiclePlate').value.trim());
    if(!derivedId) throw new Error('Aus dem Kennzeichen konnte keine interne ID erzeugt werden.');
    const payload = { id: derivedId, label: field('vehicleLabel').value.trim(), manufacturer: createState.manufacturer, license_plate: field('vehiclePlate').value.trim(), enabled: true, provider_config: {}, auth_session_id: createState.authSessionId, device_tracker_enabled: !!field('createDeviceTrackerEnabled')?.checked };
    if(createState.manufacturer === 'bmw'){
      if(!field('bmwClientId').value.trim() || !field('bmwVin').value.trim()) throw new Error('Bitte BMW Client ID und VIN eintragen.');
      if(!createState.authReady) throw new Error('Bitte BMW Authentifizierung abschließen.');
      payload.provider_config = { client_id: field('bmwClientId').value.trim(), mqtt_username: field('bmwClientId').value.trim(), vin: field('bmwVin').value.trim(), region: field('bmwRegion').value.trim(), auto_reconnect: true, manual_reconnect_minutes: 15 };
    }
    if(createState.manufacturer === 'acconia'){
      payload.provider_config = { account: field("acconiaAccount").value.trim(), password: field("acconiaPassword").value, api_key: field("acconiaApiKey").value.trim(), vehicle_id: derivedId, battery_count: field("acconiaBatteryCount").value, poll_interval: field("acconiaPollInterval").value.trim() || "60", capacity_kwh: field("acconiaCapacity").value.trim() };
      if(!payload.provider_config.account || !payload.provider_config.password || !payload.provider_config.api_key) throw new Error("Bitte Acconia/Silence Benutzerkonto, Passwort und Firebase API-Key eintragen.");
    }
    if(isVagManufacturer(createState.manufacturer)){
      payload.provider_config = { brand: createState.manufacturer, api_mode: field('vagApiMode').value, account: field('vagAccount').value.trim(), password: field('vagPassword').value, country: field('vagCountry').value.trim() || 'DE', pin: field('vagPin')?.value || '', powertrain: field('vagPowertrain').value, poll_interval: field('vagPollInterval').value.trim() || '60', capacity_kwh: field('vagCapacity').value.trim(), vehicle_id: derivedId };
     
    }
    if(createState.manufacturer === 'gwm'){
      payload.provider_config = { account: field('gwmAccount').value.trim(), password: field('gwmPassword').value.trim(), country: field('gwmCountry').value.trim(), language: field('gwmLanguage').value.trim(), polling_enabled: field('gwmPollingEnabled').checked, poll_interval: field('gwmPollInterval').value.trim(), vehicle_id: field('gwmVehicleId').value.trim() || derivedId, capacity_kwh: field('gwmCapacity').value.trim(), source_topic_base: field('gwmSourceTopicBase')?.value?.trim() || 'GWM', auto_reconnect: field('gwmAutoReconnect').checked, delayed_retry_enabled: field('gwmDelayedRetryEnabled').checked, retry_delay_minutes: field('gwmRetryDelayMinutes').value.trim() || '55', fallback_on_silence: field('gwmFallbackOnSilence').checked };
      if(!payload.provider_config.account || !payload.provider_config.password) throw new Error('Bitte ORA Benutzerkonto und Passwort eintragen.');
    }
    await postJson('./api/vehicles', payload);
    field('wizardDialog').close();
    await loadDashboard();
  }catch(err){ showNotice('wizardError', err.message); }
};

async function editVehicle(vehicleId){
  showNotice('editError');
  fillManufacturerSelect();
  const currentCard = cards.find(card => card.id === vehicleId) || null;
  const vehicle = currentCard && currentCard.remote ? {
    id: currentCard.id,
    label: currentCard.label,
    manufacturer: String(currentCard.manufacturer || '').toLowerCase(),
    license_plate: currentCard.license_plate,
    enabled: true,
    remote: true,
    provider_config: { vin: ((currentCard.live || {}).vin || '') },
    provider_state: { auth_state: currentCard.auth_state || 'authorized', auth_message: currentCard.status_detail || '' },
    status: currentCard.status || 'connected',
    status_detail: currentCard.status_detail || '',
    mqtt_client_ids: [],
    remote_server_name: currentCard.remote_server_name || ''
  } : await (await fetch(`./api/vehicles/${vehicleId}`)).json();
  stopLiveLogs(); editState.vehicleId = vehicleId; editState.reauthSessionId = null; editState.authReady = vehicle.provider_state?.auth_state === 'authorized'; editState.lastLogText = ''; setLiveLogUi();
  field('editManufacturer').value = vehicle.manufacturer; field('editLabel').value = vehicle.label; field('editPlate').value = vehicle.license_plate;
  field('editEnabled').checked = vehicle.enabled !== false;
  if(field('editDeviceTrackerEnabled')) field('editDeviceTrackerEnabled').checked = !!vehicle.device_tracker_enabled;
  setEditRemoteMode(!!vehicle.remote, currentCard);
  if(vehicle.remote){
    setEditManufacturerLayout('');
    fillEvccVehicleConfigFields(currentCard || vehicle);
    field('editDialog').showModal();
    return;
  }
  field('editBmwClientId').value = vehicle.provider_config.client_id || ''; field('editBmwMqttUsername').value = vehicle.provider_config.client_id || vehicle.provider_config.mqtt_username || ''; field('editBmwVin').value = vehicle.provider_config.vin || ''; field('editBmwRegion').value = vehicle.provider_config.region || 'EU'; field('editBmwAutoReconnect').checked = vehicle.provider_config.auto_reconnect !== false; field('editBmwManualReconnectMinutes').value = vehicle.provider_config.manual_reconnect_minutes || 15; toggleBmwReconnectMode();
  field('editGwmAccount').value = vehicle.provider_config.account || ''; field('editGwmPassword').value = vehicle.provider_config.password || ''; field('editGwmCountry').value = vehicle.provider_config.country || 'DE'; field('editGwmLanguage').value = vehicle.provider_config.language || 'de'; field('editGwmPollInterval').value = vehicle.provider_config.poll_interval || 60; field('editGwmVehicleId').value = vehicle.provider_config.vehicle_id || vehicle.id; field('editGwmCapacity').value = vehicle.provider_config.capacity_kwh || ''; const gwmSourceBase = vehicle.provider_config.source_topic_base || 'GWM';
  field('editGwmSourceTopicBase').value = (String(gwmSourceBase).startsWith('GWM/')) ? 'GWM' : gwmSourceBase;
  field("editAcconiaAccount").value = vehicle.provider_config.account || ""; field("editAcconiaPassword").value = vehicle.provider_config.password || ""; field("editAcconiaApiKey").value = vehicle.provider_config.api_key || ""; field("editAcconiaBatteryCount").value = String(vehicle.provider_config.battery_count || 2); field("editAcconiaPollInterval").value = String(vehicle.provider_config.poll_interval || 60); field("editAcconiaCapacity").value = vehicle.provider_config.capacity_kwh || ""; field("editVagApiMode").value = vehicle.provider_config.api_mode || "brand_app"; field("editVagAccount").value = vehicle.provider_config.account || ""; field("editVagPassword").value = vehicle.provider_config.password || ""; field("editVagPin").value = vehicle.provider_config.pin || ""; field("editVagCountry").value = vehicle.provider_config.country || "DE"; field("editVagPowertrain").value = vehicle.provider_config.powertrain || "unknown"; field("editVagPollInterval").value = String(vehicle.provider_config.poll_interval || 60); field("editVagCapacity").value = vehicle.provider_config.capacity_kwh || ""; field("editGwmVerificationCode").value = ""; field("editGwmPollingEnabled").checked = vehicle.provider_config.polling_enabled !== false; field("editGwmAutoReconnect").checked = vehicle.provider_config.auto_reconnect !== false; field("editGwmDelayedRetryEnabled").checked = vehicle.provider_config.delayed_retry_enabled !== false; field("editGwmRetryDelayMinutes").value = String(vehicle.provider_config.retry_delay_minutes || 55); field("editGwmFallbackOnSilence").checked = vehicle.provider_config.fallback_on_silence !== false; fillEvccVehicleConfigFields(vehicle); toggleEditGwmOptions();
  const gwmNeedsReauth = vehicle.manufacturer === 'gwm' && (/refresh token abgelaufen|reauth erforderlich/i.test(vehicle.status || '') || /refresh token abgelaufen|reauth erforderlich/i.test(vehicle.status_detail || '') || /refresh token/i.test(vehicle.provider_state?.last_error || '') || /reauth erforderlich/i.test(vehicle.provider_state?.auth_message || ''));
  field('editReauthTitle').textContent = vehicle.manufacturer === 'gwm' ? 'ORA ReAuth' : 'BMW Re-Auth';
  field('editAuthState').textContent = vehicle.enabled === false ? 'Fahrzeug ist inaktiv.' : (vehicle.manufacturer === 'gwm' ? (gwmNeedsReauth ? 'ReAuth erforderlich - gespeicherte Anmeldung ist abgelaufen.' : (vehicle.status === 'waiting_for_code' ? 'Verifikationscode erforderlich.' : (vehicle.provider_state?.auth_state === 'authorized' ? 'Bestehende Anmeldung aktiv.' : 'Anmeldung prüfen.'))) : (vehicle.provider_state?.auth_state === 'authorized' ? 'Bestehende Anmeldung aktiv.' : 'Anmeldung prüfen.'));
  field('editReauthStartBtn').disabled = vehicle.enabled === false || !['bmw','gwm'].includes(vehicle.manufacturer);
  field('editReauthStartBtn').textContent = vehicle.manufacturer === 'gwm' ? 'ReAuth starten' : 'Re-Auth starten';
  field('editReauthQuickBtn').disabled = field('editReauthStartBtn').disabled;
  field('editReauthQuickBtn').textContent = vehicle.manufacturer === 'gwm' ? 'ReAuth starten' : 'Re-Auth starten';
  field('editAuthInfo').classList.add('hidden');
  setEditManufacturerLayout(vehicle.manufacturer);
  const verifyNeeded = vehicle.manufacturer === 'gwm' && (
    !vehicle.provider_config?.access_token ||
    vehicle.status === 'waiting_for_code' ||
    /verification|verifikationscode|code erforderlich/i.test(vehicle.status_detail || '')
  );
  setGwmVerifyVisibility(verifyNeeded, verifyNeeded);
  renderEditMqttClientAssignments(vehicle);
  await refreshVehicleLogs();
  if(vehicle.manufacturer !== 'gwm'){
    setGwmVerifyVisibility(false, false);
  }
  field('editDialog').showModal();
}
window.editVehicle = editVehicle;

function setLiveLogUi(){ const state = field('liveLogState'); const btn = field('toggleLiveLogsBtn'); state.textContent = editState.liveLogsEnabled ? 'Live an' : 'Live aus'; state.classList.toggle('active', editState.liveLogsEnabled); btn.textContent = editState.liveLogsEnabled ? 'Live-Log stoppen' : 'Live-Log einschalten'; }
function stopLiveLogs(){ if(editState.liveLogTimer){ clearInterval(editState.liveLogTimer); editState.liveLogTimer = null; } editState.liveLogsEnabled = false; setLiveLogUi(); }
async function refreshVehicleLogs(){ if(!editState.vehicleId) return; try{ const text = await fetchText(`./api/vehicles/${editState.vehicleId}/logs`); const viewer = field('vehicleLogViewer'); const changed = text !== editState.lastLogText; viewer.textContent = text || 'Noch keine Logs vorhanden.'; if(changed){ viewer.scrollTop = viewer.scrollHeight; } editState.lastLogText = text; }catch(err){ field('vehicleLogViewer').textContent = err.message; } }
function startLiveLogs(){ if(!editState.vehicleId) return; stopLiveLogs(); editState.liveLogsEnabled = true; setLiveLogUi(); refreshVehicleLogs(); editState.liveLogTimer = setInterval(refreshVehicleLogs, 2000); }
field('refreshLogsBtn').onclick = refreshVehicleLogs;
async function submitGwmCode(){
  if(!editState.vehicleId) return;
  const code = field('editGwmVerificationCode').value.trim();
  if(!code){ alert('Bitte Verifikationscode eintragen.'); return; }
  try{
    await fetch(`./api/vehicles/${editState.vehicleId}/gwm/submit-code`, {
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify({ verification_code: code })
    }).then(async res => {
      if(!res.ok){
        const txt = await res.text();
        throw new Error(txt || `HTTP ${res.status}`);
      }
      return res.json();
    });
    await loadDashboard();
    await refreshVehicleLogs();
    field('editGwmVerificationCode').value = '';
    setGwmVerifyVisibility(false, false);
  }catch(err){
    alert(err.message);
  }
}
field('submitGwmCodeBtn').onclick = submitGwmCode;
async function runOraTestMap(){
  if(!editState.vehicleId) return;
  try{
    const res = await fetch(`./api/vehicles/${editState.vehicleId}/gwm/test-map`, {method:'POST'});
    const data = await res.json();
    if(!res.ok) throw new Error(errorTextFromResponsePayload(data));
    await loadDashboard();
    await refreshVehicleLogs();
    alert(`Test-Mapping abgeschlossen. Verarbeitete Nachrichten: ${data.processed}`);
  }catch(err){
    alert(err.message || String(err));
  }
}
if(field('runOraTestMapBtn')) field('runOraTestMapBtn').onclick = runOraTestMap;
field('clearLogsBtn').onclick = async()=>{ 
  if(!editState.vehicleId) return;
  if(!confirm('Aktuelle Fahrzeug-Logs wirklich löschen?')) return;
  try{
    const res = await fetch(`./api/vehicles/${editState.vehicleId}/logs/clear`, { method:'POST' });
    if(!res.ok){
      const txt = await res.text();
      throw new Error(txt || `HTTP ${res.status}`);
    }
    editState.lastLogText = '';
    field('vehicleLogViewer').textContent = 'Noch keine fahrzeugspezifischen Logs vorhanden.';
    await refreshVehicleLogs();
  }catch(err){
    alert('Logs konnten nicht gelöscht werden: ' + (err.message || err));
  }
};
field('toggleLiveLogsBtn').onclick = ()=>{ if(editState.liveLogsEnabled) stopLiveLogs(); else startLiveLogs(); };
field('editManufacturer').onchange = toggleEditSections;
field('gwmPollingEnabled').onchange = toggleCreateGwmOptions;
field('gwmDelayedRetryEnabled').onchange = toggleCreateGwmOptions;
field('editGwmPollingEnabled').onchange = toggleEditGwmOptions;
field('editGwmDelayedRetryEnabled').onchange = toggleEditGwmOptions;
field('closeEditBtn').onclick = field('cancelEditBtn').onclick = () => { stopLiveLogs(); field('editDialog').close(); };
field('editReauthStartBtn').onclick = async()=>{ if(!editState.vehicleId) return; showNotice('editError'); try{ const vehicle = await (await fetch(`./api/vehicles/${editState.vehicleId}`)).json(); if(vehicle.manufacturer === 'gwm'){ const d = await postJson(`./api/vehicles/${editState.vehicleId}/gwm/reauth/start`,{}); editState.authReady = false; field('editAuthState').textContent = d.message || 'ORA ReAuth gestartet.'; field('editAuthInfo').classList.add('hidden'); setGwmVerifyVisibility(true, false); await loadDashboard(); await refreshVehicleLogs(); return; } const d = await postJson(`./api/vehicles/${editState.vehicleId}/reauth/start`,{}); editState.reauthSessionId = d.session_id; editState.authReady = false; field('editAuthState').textContent = d.message || 'Re-Auth gestartet.'; field('editUserCode').textContent = d.user_code; field('editVerificationUrl').href = d.verification_uri_complete; field('editVerificationUrl').textContent = d.verification_uri_complete; field('editAuthInfo').classList.remove('hidden'); window.open(d.verification_uri_complete,'_blank'); await refreshVehicleLogs(); }catch(err){ showNotice('editError', err.message); } };
field('editReauthQuickBtn').onclick = ()=> field('editReauthStartBtn').click();
field('editPollAuthBtn').onclick = async()=>{ if(!editState.reauthSessionId) return showNotice('editError','Bitte zuerst Re-Auth starten.'); try{ const d = await postJson('./api/providers/bmw/auth/poll',{ session_id: editState.reauthSessionId }); if(d.state === 'authorized'){ editState.authReady = true; field('editAuthState').textContent = 'BMW Re-Auth erfolgreich abgeschlossen.'; await refreshVehicleLogs(); } else { field('editAuthState').textContent = d.message || d.state; } }catch(err){ showNotice('editError', err.message); } };
async function saveEdit(closeAfter){ try{ const manufacturer = field('editManufacturer').value; const derivedId = normalizeVehicleIdFromPlate(field('editPlate').value.trim()); const payload = { id: derivedId, label: field('editLabel').value.trim(), manufacturer, license_plate: field('editPlate').value.trim(), enabled: field('editEnabled').checked, provider_config: {}, auth_session_id: editState.reauthSessionId || null, mqtt_client_ids: Array.from(document.querySelectorAll('.edit-mqtt-client-check:checked')).map(el=>el.value), device_tracker_enabled: !!field('editDeviceTrackerEnabled')?.checked };
  if(!payload.label || !payload.license_plate || !derivedId) throw new Error('Bitte Titel und Kennzeichen ausfüllen.');
  if(manufacturer === 'bmw'){ payload.provider_config = { client_id: field('editBmwClientId').value.trim(), mqtt_username: field('editBmwClientId').value.trim(), vin: field('editBmwVin').value.trim(), region: field('editBmwRegion').value.trim(), auto_reconnect: field('editBmwAutoReconnect').checked, manual_reconnect_minutes: Math.max(15, Math.min(60, parseInt(field('editBmwManualReconnectMinutes').value || '15', 10))) }; if(!payload.provider_config.client_id || !payload.provider_config.vin) throw new Error('Bitte BMW Client ID und VIN eintragen.'); }
  if(manufacturer === 'acconia'){ payload.provider_config = { account: field("editAcconiaAccount").value.trim(), password: field("editAcconiaPassword").value, api_key: field("editAcconiaApiKey").value.trim(), vehicle_id: derivedId, battery_count: field("editAcconiaBatteryCount").value, poll_interval: field("editAcconiaPollInterval").value.trim() || "60", capacity_kwh: field("editAcconiaCapacity").value.trim() }; if(!payload.provider_config.account || !payload.provider_config.password || !payload.provider_config.api_key) throw new Error("Bitte Acconia/Silence Benutzerkonto, Passwort und Firebase API-Key eintragen."); }
  if(isVagManufacturer(manufacturer)){ payload.provider_config = { brand: manufacturer, api_mode: field('editVagApiMode').value, account: field('editVagAccount').value.trim(), password: field('editVagPassword').value, country: field('editVagCountry').value.trim() || 'DE', pin: field('editVagPin')?.value || '', powertrain: field('editVagPowertrain').value, poll_interval: field('editVagPollInterval').value.trim() || '60', capacity_kwh: field('editVagCapacity').value.trim(), vehicle_id: derivedId }; }
  if(manufacturer === 'gwm'){ payload.provider_config = { account: field('editGwmAccount').value.trim(), password: field('editGwmPassword').value.trim(), country: field('editGwmCountry').value.trim(), language: field('editGwmLanguage').value.trim(), polling_enabled: field('editGwmPollingEnabled').checked, poll_interval: field('editGwmPollInterval').value.trim(), vehicle_id: field('editGwmVehicleId').value.trim() || derivedId, capacity_kwh: field('editGwmCapacity').value.trim(), source_topic_base: field('editGwmSourceTopicBase').value.trim(), auto_reconnect: field('editGwmAutoReconnect').checked, delayed_retry_enabled: field('editGwmDelayedRetryEnabled').checked, retry_delay_minutes: field('editGwmRetryDelayMinutes').value.trim() || '55', fallback_on_silence: field('editGwmFallbackOnSilence').checked }; if(!payload.provider_config.account || !payload.provider_config.password) throw new Error('Bitte ORA Benutzerkonto und Passwort eintragen.'); }
  Object.assign(payload.provider_config, collectEvccVehicleConfigPayload());
  await postJson(`./api/vehicles/${editState.vehicleId}`, payload, 'PUT'); await loadDashboard(); if(closeAfter){ field('editDialog').close(); } } catch(err){ showNotice('editError', err.message); } }
field('saveEditKeepOpenBtn').onclick = ()=>{
  const card = getCurrentEditCard();
  if(card && card.remote) return saveCurrentEvccVehicleConfig(false);
  return saveEdit(false);
};
field('saveEditBtn').onclick = ()=>{
  const card = getCurrentEditCard();
  if(card && card.remote) return saveCurrentEvccVehicleConfig(true);
  return saveEdit(true);
};

async function deleteVehicle(vehicleId){ if(!confirm('Fahrzeug wirklich löschen?')) return; await fetch(`./api/vehicles/${vehicleId}`,{method:'DELETE'}); await loadDashboard(); }
window.deleteVehicle = deleteVehicle;

if (field('editOraSendVerificationBtn')) field('editOraSendVerificationBtn').onclick = sendOraVerificationCode;

field('closeMqttClientsBtn').onclick = ()=> { resetMqttClientForm(true); field('mqttClientsDialog').close(); };
field('cancelMqttClientEditBtn').onclick = ()=> resetMqttClientForm(true);
if (field('addMqttClientBtn')) field('addMqttClientBtn').onclick = openCreateMqttClient;

const remoteTrackerToggle = field('editRemoteDeviceTrackerEnabled');
if(remoteTrackerToggle){ remoteTrackerToggle.onchange = async()=>{ if(!editState.vehicleId) return; try{ await postJson(`./api/remote-vehicles/${editState.vehicleId}/device-tracker`, { device_tracker_enabled: !!remoteTrackerToggle.checked }); await loadDashboard(); const card = cards.find(c=>c.id===editState.vehicleId); if(card){ field('editRemoteDeviceTrackerEnabled').checked = !!card.device_tracker_enabled; } }catch(err){ alert(err.message || 'Device Tracker konnte nicht gespeichert werden.'); } }; }
field('saveMqttClientBtn').onclick = async()=>{
  try{
    const payload = { id: mqttClientState.editingId, name: field('mqttClientName').value.trim(), host: field('mqttClientHost').value.trim(), port: parseInt(field('mqttClientPort').value || '1883', 10), username: field('mqttClientUsername').value.trim(), password: field('mqttClientPassword').value, base_topic: field('mqttClientBaseTopic').value.trim(), enabled: field('mqttClientEnabled').checked, send_raw: field('mqttClientSendRaw').checked };
    if(!payload.host) throw new Error('Bitte Server eintragen.');
    await postJson('./api/mqtt-clients', payload);
    const res = await fetch('./api/mqtt-clients');
    mqttClients = (await res.json()).clients || [];
    renderMqttClientsGrid();
    const card = getCurrentEditCard(); if(card) renderEditMqttClientAssignments(card);
    resetMqttClientForm(true);
  }catch(err){ showNotice('mqttClientsError', err.message); }
};
field('editBmwAutoReconnect').onchange = toggleBmwReconnectMode;
toggleBmwReconnectMode();
field('createManufacturer').onchange = toggleCreateSections; setLiveLogUi(); renderCards(); renderProviderList(); fillManufacturerSelect(); setInterval(loadDashboard, 15000);
