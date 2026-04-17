const state = {
  providers: [],
  vehicles: [],
  editingId: null,
};

const els = {
  cards: document.getElementById('cards'),
  mappingPreview: document.getElementById('mappingPreview'),
  vehicleCount: document.getElementById('vehicleCount'),
  runningCount: document.getElementById('runningCount'),
  providerCount: document.getElementById('providerCount'),
  versionBadge: document.getElementById('versionBadge'),
  dialog: document.getElementById('vehicleDialog'),
  dialogTitle: document.getElementById('dialogTitle'),
  form: document.getElementById('vehicleForm'),
  providerFields: document.getElementById('providerFields'),
  providerDescription: document.getElementById('providerDescription'),
  manufacturerSelect: document.getElementById('manufacturerSelect'),
  template: document.getElementById('vehicleCardTemplate'),
};

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  });

  if (!response.ok) {
    const payload = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(payload.detail || response.statusText);
  }

  const contentType = response.headers.get('content-type') || '';
  return contentType.includes('application/json') ? response.json() : response.text();
}

function getProvider(manufacturer) {
  return state.providers.find((provider) => provider.manufacturer === manufacturer);
}

function renderProviderOptions() {
  els.manufacturerSelect.innerHTML = '';
  for (const provider of state.providers) {
    const option = document.createElement('option');
    option.value = provider.manufacturer;
    option.textContent = provider.name;
    els.manufacturerSelect.appendChild(option);
  }
}

function renderProviderFields(manufacturer, values = {}) {
  const provider = getProvider(manufacturer);
  els.providerFields.innerHTML = '';
  els.providerDescription.textContent = provider?.description || '';

  if (!provider) return;

  for (const field of provider.fields) {
    const label = document.createElement('label');
    label.innerHTML = `<span>${field.label}</span>`;

    const input = document.createElement('input');
    input.name = `provider:${field.key}`;
    input.type = field.kind === 'password' ? 'password' : field.kind === 'number' ? 'number' : 'text';
    input.placeholder = field.placeholder || '';
    input.required = !!field.required;
    input.value = values[field.key] ?? '';
    label.appendChild(input);

    if (field.help_text) {
      const hint = document.createElement('small');
      hint.className = 'subtle';
      hint.textContent = field.help_text;
      label.appendChild(hint);
    }

    els.providerFields.appendChild(label);
  }
}

function openDialog(vehicle = null) {
  state.editingId = vehicle?.config?.id || null;
  els.dialogTitle.textContent = vehicle ? 'Fahrzeug bearbeiten' : 'Fahrzeug hinzufügen';
  els.form.reset();

  els.form.elements.id.value = vehicle?.config?.id || '';
  els.form.elements.label.value = vehicle?.config?.label || '';
  els.form.elements.license_plate.value = vehicle?.config?.license_plate || '';
  els.form.elements.enabled.checked = vehicle?.config?.enabled ?? true;
  els.form.elements.manufacturer.value = vehicle?.config?.manufacturer || state.providers[0]?.manufacturer || 'bmw';
  renderProviderFields(els.form.elements.manufacturer.value, vehicle?.config?.provider_config || {});
  els.dialog.showModal();
}

function closeDialog() {
  els.dialog.close();
  state.editingId = null;
}

async function loadVersion() {
  const payload = await api('/api/version');
  els.versionBadge.textContent = `v${payload.version}`;
}

async function loadProviders() {
  state.providers = await api('/api/providers');
  els.providerCount.textContent = String(state.providers.length);
  renderProviderOptions();
}

function topicHint(vehicle) {
  return `car/${vehicle.config.manufacturer}/${vehicle.config.license_plate}/...`;
}

function renderCards() {
  els.cards.innerHTML = '';
  els.vehicleCount.textContent = String(state.vehicles.length);
  els.runningCount.textContent = String(state.vehicles.filter((item) => item.status === 'running').length);

  if (!state.vehicles.length) {
    const empty = document.createElement('article');
    empty.className = 'vehicle-card';
    empty.innerHTML = '<h3>Noch keine Fahrzeuge</h3><p class="subtle">Lege mit deiner ersten Instanz los.</p>';
    els.cards.appendChild(empty);
    return;
  }

  for (const vehicle of state.vehicles) {
    const node = els.template.content.cloneNode(true);
    node.querySelector('.manufacturer').textContent = vehicle.config.manufacturer.toUpperCase();
    node.querySelector('.label').textContent = vehicle.config.label;
    node.querySelector('.plate').textContent = vehicle.config.license_plate;
    node.querySelector('.vehicle-id').textContent = vehicle.config.id;
    node.querySelector('.last-seen').textContent = vehicle.last_seen || '—';
    node.querySelector('.message').textContent = vehicle.message;
    node.querySelector('.topic-hint').textContent = topicHint(vehicle);

    const statusPill = node.querySelector('.status-pill');
    statusPill.textContent = vehicle.status;
    statusPill.classList.add(vehicle.status);

    node.querySelector('.start').addEventListener('click', async () => {
      await api(`/api/vehicles/${vehicle.config.id}/start`, { method: 'POST' });
      await loadVehicles();
    });
    node.querySelector('.stop').addEventListener('click', async () => {
      await api(`/api/vehicles/${vehicle.config.id}/stop`, { method: 'POST' });
      await loadVehicles();
    });
    node.querySelector('.edit').addEventListener('click', () => openDialog(vehicle));
    node.querySelector('.delete').addEventListener('click', async () => {
      if (!confirm(`Fahrzeug ${vehicle.config.label} löschen?`)) return;
      await api(`/api/vehicles/${vehicle.config.id}`, { method: 'DELETE' });
      await loadVehicles();
    });

    els.cards.appendChild(node);
  }
}

async function loadVehicles() {
  state.vehicles = await api('/api/vehicles');
  renderCards();
}

async function loadMappingExample() {
  const payload = await api('/api/mapping/examples/bmw');
  els.mappingPreview.textContent = JSON.stringify(payload, null, 2);
}

function collectProviderConfig(formData) {
  const providerConfig = {};
  for (const [key, value] of formData.entries()) {
    if (!key.startsWith('provider:')) continue;
    const providerKey = key.replace('provider:', '');
    providerConfig[providerKey] = value;
  }
  return providerConfig;
}

async function handleSubmit(event) {
  event.preventDefault();
  const formData = new FormData(els.form);
  const payload = {
    id: formData.get('id').trim(),
    label: formData.get('label').trim(),
    manufacturer: formData.get('manufacturer'),
    license_plate: formData.get('license_plate').trim(),
    enabled: formData.get('enabled') === 'on',
    provider_config: collectProviderConfig(formData),
  };

  const target = state.editingId ? `/api/vehicles/${payload.id}` : '/api/vehicles';
  const method = state.editingId ? 'PUT' : 'POST';

  try {
    await api(target, { method, body: JSON.stringify(payload) });
    closeDialog();
    await loadVehicles();
  } catch (error) {
    alert(error.message);
  }
}

async function init() {
  await loadVersion();
  await loadProviders();
  await loadVehicles();
  await loadMappingExample();

  document.getElementById('addVehicleButton').addEventListener('click', () => openDialog());
  document.getElementById('closeDialogButton').addEventListener('click', closeDialog);
  document.getElementById('cancelDialogButton').addEventListener('click', closeDialog);
  els.manufacturerSelect.addEventListener('change', (event) => renderProviderFields(event.target.value));
  els.form.addEventListener('submit', handleSubmit);
}

init().catch((error) => {
  console.error(error);
  alert(error.message || 'Initialisierung fehlgeschlagen');
});
