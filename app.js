const form = document.querySelector('#dispatch-form');
const submitButton = document.querySelector('#submit-button');
const resultPanel = document.querySelector('#result-panel');
const historyBody = document.querySelector('#history-body');
const historyCount = document.querySelector('#history-count');
let historyItems = [];

async function loadProducts() {
  const select = document.querySelector('#product-select');
  const error = document.querySelector('#product-error');
  try {
    const response = await fetch('/api/products');
    if (!response.ok) throw new Error('No se pudo cargar el catálogo.');
    const data = await response.json();
    const products = Array.isArray(data.productos) ? data.productos : [];
    select.replaceChildren(new Option('Selecciona un producto', ''));
    for (const product of products) {
      if (!product.codigo || !product.nombre) continue;
      select.add(new Option(`${product.codigo} · ${product.nombre}`, product.codigo));
    }
    if (select.options.length === 1) throw new Error('El catálogo no contiene productos.');
    select.disabled = false;
  } catch {
    select.replaceChildren(new Option('Catálogo no disponible', ''));
    error.textContent = 'No se pudo cargar la lista. Revisa products.json y vuelve a cargar la página.';
  }
}
loadProducts();

const outcomeLabels = {
  APROBADO: 'Aprobado',
  'APROBADO CON ALERTA': 'Aprobado con alerta',
  RECHAZADO: 'Rechazado',
  'RUTA DE RESPALDO': 'Ruta de respaldo'
};

function showResult(kind, title, message) {
  resultPanel.className = `result-panel ${kind}`;
  resultPanel.replaceChildren();
  const icon = document.createElement('span');
  icon.className = 'result-icon';
  icon.textContent = kind === 'approved' ? '✓' : kind === 'pending' ? '…' : '!';
  const content = document.createElement('div');
  const heading = document.createElement('h3');
  heading.textContent = title;
  const body = document.createElement('p');
  body.textContent = message;
  content.append(heading, body);
  resultPanel.append(icon, content);
  resultPanel.hidden = false;
}

function validateForm() {
  let valid = true;
  for (const field of form.elements) {
    if (!field.name) continue;
    const error = field.parentElement.querySelector('.field-error');
    let message = '';
    if (!field.value.trim()) message = 'Este campo es obligatorio.';
    else if (field.name === 'correo' && !field.validity.valid) message = 'Ingresa un correo válido.';
    else if (field.name === 'cantidad' && (!Number.isFinite(Number(field.value)) || Number(field.value) <= 0)) message = 'La cantidad debe ser un número positivo.';
    else if (field.name === 'codigo_producto' && !/^[A-Za-z0-9-]+$/.test(field.value.trim())) message = 'Selecciona un producto válido.';
    field.setAttribute('aria-invalid', message ? 'true' : 'false');
    error.textContent = message;
    if (message) valid = false;
  }
  return valid;
}

function outcomeStyle(result) {
  if (result === 'APROBADO') return 'approved';
  if (result === 'APROBADO CON ALERTA') return 'alert';
  if (result === 'RECHAZADO') return 'rejected';
  return 'backup';
}

function showOutcome(data) {
  const result = String(data.resultado || data.result || '').toUpperCase();
  const known = Object.hasOwn(outcomeLabels, result);
  if (!known) {
    showResult('error', 'Respuesta no reconocida', 'La automatización devolvió una respuesta que no podemos interpretar. Verifica el historial o contacta al administrador.');
    return;
  }
  const balance = data.saldo_posterior ?? data.saldo;
  const details = [data.mensaje || data.observacion || 'La solicitud fue procesada por la automatización.'];
  if (balance !== undefined && balance !== null) details.push(`Saldo posterior: ${balance}.`);
  showResult(outcomeStyle(result), outcomeLabels[result], details.join(' '));
  if (result === 'APROBADO' || result === 'APROBADO CON ALERTA') loadHistory();
}

form.addEventListener('submit', async (event) => {
  event.preventDefault();
  if (!validateForm()) {
    showResult('error', 'Revisa los datos', 'Hay campos por corregir antes de enviar la solicitud.');
    form.querySelector('[aria-invalid="true"]')?.focus();
    return;
  }
  const payload = Object.fromEntries(new FormData(form).entries());
  payload.cantidad = Number(payload.cantidad);
  submitButton.disabled = true;
  submitButton.textContent = 'Procesando…';
  showResult('pending', 'Procesando solicitud', 'Consultando inventario. Espera la respuesta de la automatización.');
  try {
    const response = await fetch('/api/dispatch', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload), signal: AbortSignal.timeout(40000)
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.error || 'No fue posible procesar la solicitud.');
    showOutcome(data);
    if (Object.hasOwn(outcomeLabels, String(data.resultado || data.result || '').toUpperCase())) form.reset();
  } catch (error) {
    const timedOut = error.name === 'TimeoutError';
    showResult('error', timedOut ? 'La respuesta tardó demasiado' : 'No se pudo conectar', timedOut
      ? 'No recibimos respuesta dentro del tiempo esperado. Comprueba el historial antes de volver a enviar para evitar duplicados.'
      : `${error.message || 'Ocurrió un error de conexión.'} La solicitud no se marcará como aprobada.`);
  } finally {
    submitButton.disabled = false;
    submitButton.innerHTML = '<span class="button-icon">↗</span> Registrar solicitud';
  }
});

function formatDate(value) {
  if (!value) return '—';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? String(value) : new Intl.DateTimeFormat('es-CO', { dateStyle: 'short', timeStyle: 'short' }).format(date);
}

function renderHistory(items = historyItems) {
  const search = document.querySelector('#history-search').value.trim().toLocaleLowerCase('es');
  const filtered = items.filter(item => [item.codigo_producto, item.producto, item.solicitante, item.destino].some(v => String(v || '').toLocaleLowerCase('es').includes(search)));
  historyCount.textContent = `${filtered.length} ${filtered.length === 1 ? 'movimiento' : 'movimientos'}`;
  historyBody.replaceChildren();
  if (!filtered.length) {
    const row = document.createElement('tr'); const cell = document.createElement('td');
    cell.colSpan = 6; cell.className = 'empty-state'; cell.textContent = items.length ? 'No hay coincidencias para esa búsqueda.' : 'Todavía no hay movimientos registrados.';
    row.append(cell); historyBody.append(row); return;
  }
  for (const item of filtered) {
    const row = document.createElement('tr');
    const values = [formatDate(item.fecha_hora), `${item.codigo_producto || '—'}${item.producto ? ` · ${item.producto}` : ''}`, item.solicitante || '—', item.cantidad ?? '—', item.destino || '—'];
    for (const value of values) { const cell = document.createElement('td'); cell.textContent = value; row.append(cell); }
    const resultCell = document.createElement('td'); const pill = document.createElement('span');
    const result = String(item.resultado || '').toUpperCase(); pill.className = `pill ${outcomeStyle(result)}`; pill.textContent = outcomeLabels[result] || result || '—';
    resultCell.append(pill); row.append(resultCell); historyBody.append(row);
  }
}

async function loadHistory() {
  try {
    const response = await fetch('/api/history');
    if (!response.ok) throw new Error('No se pudo cargar el historial.');
    const data = await response.json();
    historyItems = Array.isArray(data.movimientos) ? data.movimientos : [];
    renderHistory();
  } catch {
    historyCount.textContent = 'Historial no disponible';
    historyBody.innerHTML = '<tr><td colspan="6" class="empty-state">No se pudo conectar con el historial. Intenta actualizar.</td></tr>';
  }
}

document.querySelectorAll('[data-view]').forEach(link => link.addEventListener('click', () => {
  const target = link.dataset.view;
  document.querySelectorAll('[data-view]').forEach(item => item.classList.toggle('active', item === link));
  document.querySelectorAll('.view').forEach(view => view.classList.toggle('active', view.id === `view-${target}`));
  document.querySelector('#crumb-current').textContent = target === 'historial' ? 'Historial de movimientos' : 'Registro de despacho';
  if (target === 'historial') loadHistory();
}));
document.querySelector('#refresh-history').addEventListener('click', loadHistory);
document.querySelector('#history-search').addEventListener('input', () => renderHistory());
