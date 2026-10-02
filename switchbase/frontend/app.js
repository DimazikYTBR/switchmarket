const API_BASE = window.location.origin.replace(/:\d+$/, ':8000');
const WS_BASE = API_BASE.replace(/^http/, 'ws');

const state = {
  token: null,
  user: null,
  route: 'catalog',
  listings: [],
  inventory: [],
  orders: {},
  currentOrder: null,
  socket: null,
};

const screenEl = document.getElementById('screen');
const balanceEl = document.getElementById('balanceValue');
const islandEl = document.getElementById('island');

const ROUTE_LABELS = {
  catalog: 'Маркет',
  deals: 'Сделки',
  gifts: 'Подарки',
  profile: 'Профиль',
  disputes: 'Споры',
};

const STATUS_LABELS = {
  awaiting_payment: 'Ожидание оплаты',
  escrow_locked: 'Средства заморожены гарантом',
  asset_transferred: 'Передача подарка',
  hold_period: 'Холд 24 часа',
  completed: 'Успешно завершено',
  disputed: 'Спор',
  refunded: 'Возврат покупателю',
  cancelled: 'Отменено',
};

let scrollHandler = null;

function updateIslandSegments() {
  const primaryBtn = document.getElementById('islandPrimaryBtn');
  const dealsBtn = document.getElementById('islandDealsBtn');
  if (!primaryBtn || !dealsBtn) return;
  const isArbiter = !!(state.user && state.user.role === 'arbiter');
  const primaryTarget = isArbiter ? 'disputes' : 'catalog';
  primaryBtn.textContent = isArbiter ? 'Споры' : 'Маркет';
  primaryBtn.dataset.target = primaryTarget;
  primaryBtn.classList.toggle('active', state.route === primaryTarget);
  dealsBtn.classList.toggle('active', state.route === 'deals');
}

function enterNavIslandMode(tabLabel) {
  if (scrollHandler) {
    window.removeEventListener('scroll', scrollHandler);
    scrollHandler = null;
  }
  islandEl.classList.remove('compact');
  updateIslandSegments();

  document.getElementById('islandTabName').textContent = tabLabel;
  document.getElementById('islandStatusDot').className = 'island-status-dot';
  document.getElementById('islandTopBtn').onclick = () => {
    window.scrollTo({ top: 0, behavior: 'smooth' });
  };

  scrollHandler = () => {
    islandEl.classList.toggle('compact', window.scrollY > 28);
  };
  window.addEventListener('scroll', scrollHandler, { passive: true });
}

function enterDealIslandMode(order) {
  if (scrollHandler) {
    window.removeEventListener('scroll', scrollHandler);
    scrollHandler = null;
  }
  islandEl.classList.add('compact');
  document.getElementById('islandTabName').textContent = STATUS_LABELS[order.status] || 'Сделка';

  let variant = 'pulse';
  if (order.status === 'disputed') variant = 'danger pulse';
  else if (order.status === 'awaiting_payment') variant = 'warning pulse';
  else if (order.status === 'completed' || order.status === 'refunded') variant = '';
  document.getElementById('islandStatusDot').className = 'island-status-dot' + (variant ? ' ' + variant : '');

  document.getElementById('islandTopBtn').onclick = () => {
    window.location.hash = '#/deals';
  };
}

function updateBalanceDisplay() {
  if (!state.user) return;
  balanceEl.textContent = state.user.available_balance.toFixed(2);
  const badge = document.getElementById('bottomBalanceBadge');
  if (badge) badge.textContent = `${Math.round(state.user.available_balance).toLocaleString('ru-RU')} GRAM`;
}

function shortenAddress(address) {
  if (!address || address.length < 12) return address;
  return `${address.slice(0, 6)}…${address.slice(-4)}`;
}

function showToast(message, isError, duration = 4200) {
  let stack = document.querySelector('.toast-stack');
  if (!stack) {
    stack = document.createElement('div');
    stack.className = 'toast-stack';
    document.body.appendChild(stack);
  }

  const toast = document.createElement('div');
  toast.className = 'toast' + (isError ? ' error' : '');

  const text = document.createElement('div');
  text.className = 'toast-message';
  text.textContent = message;

  const track = document.createElement('div');
  track.className = 'toast-progress-track';
  const fill = document.createElement('div');
  fill.className = 'toast-progress-fill';
  fill.style.animationDuration = `${duration}ms`;
  track.appendChild(fill);

  toast.appendChild(text);
  toast.appendChild(track);
  stack.appendChild(toast);

  const dismiss = () => {
    toast.classList.add('leaving');
    setTimeout(() => toast.remove(), 280);
  };
  setTimeout(dismiss, duration);
}

async function api(path, options = {}) {
  const headers = Object.assign({ 'Content-Type': 'application/json' }, options.headers || {});
  if (state.token) headers['Authorization'] = `Bearer ${state.token}`;

  const response = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers,
    body: options.body ? JSON.stringify(options.body) : undefined,
  });

  if (!response.ok) {
    const errorBody = await response.json().catch(() => ({}));
    const error = new Error(errorBody.detail || `Ошибка запроса: ${response.status}`);
    error.status = response.status;
    throw error;
  }

  if (response.status === 204) return null;
  return response.json();
}

async function authenticate() {
  const tg = window.Telegram && window.Telegram.WebApp;
  if (tg) {
    tg.ready();
    tg.expand();
  }

  const initData = tg && tg.initData ? tg.initData : '';

  if (!initData) {
    showToast('Откройте приложение через Telegram для авторизации', true);
    return false;
  }

  try {
    const auth = await api('/api/auth/telegram', {
      method: 'POST',
      body: { init_data: initData },
    });
    state.token = auth.access_token;
    state.user = await api('/api/auth/me');
    updateBalanceDisplay();
    if (state.user.role === 'arbiter') document.body.classList.add('is-arbiter');
    return true;
  } catch (err) {
    showToast(err.message, true);
    return false;
  }
}

let tonConnectUI = null;

function initTonConnect() {
  if (!window.TON_CONNECT_UI) return;

  tonConnectUI = new TON_CONNECT_UI.TonConnectUI({
    manifestUrl: `${window.location.origin}/tonconnect-manifest.json`,
  });

  tonConnectUI.onStatusChange(async (wallet) => {
    if (!wallet) return;
    const address = wallet.account.address;
    if (state.user && state.user.ton_wallet_address === address) return;

    try {
      await api(`/api/wallet/connect?address=${encodeURIComponent(address)}`, { method: 'POST' });
      state.user.ton_wallet_address = address;
      showToast('Кошелёк подключён');
      if (state.route === 'profile') await loadProfile();
    } catch (err) {
      showToast(err.message, true);
    }
  });
}

function badgeForRole(role) {
  if (role === 'verified') return '<span class="seller-badge verified">Проверен ✓</span>';
  if (role === 'arbiter') return '<span class="seller-badge verified">Арбитр</span>';
  return '<span class="seller-badge standard">Обычный</span>';
}

async function loadCatalog() {
  screenEl.innerHTML = `
    <div class="section-heading">
      <div>
        <h2>Маркет</h2>
        <p>Коллекционные предметы, доступные для безопасной сделки через Гарант</p>
      </div>
    </div>
    <div class="filter-row">
      <span class="chip active">Все</span>
      <span class="chip">По цене ↑</span>
      <span class="chip">По цене ↓</span>
      <span class="chip">Только проверенные</span>
    </div>
    <div class="listing-grid" id="listingGrid"></div>
  `;

  const grid = document.getElementById('listingGrid');
  try {
    state.listings = await api('/api/listings');
  } catch (err) {
    grid.innerHTML = `<div class="empty-state">${err.message}</div>`;
    return;
  }

  if (state.listings.length === 0) {
    grid.innerHTML = '<div class="empty-state">Пока нет активных лотов. Загляните позже.</div>';
    return;
  }

  const template = document.getElementById('tpl-listing-card');
  for (const listing of state.listings) {
    const node = template.content.cloneNode(true);
    node.querySelector('.listing-image').src = listing.item.preview_url || '';
    node.querySelector('.listing-rarity').textContent = listing.item.rarity_number ? `#${listing.item.rarity_number}` : '';
    node.querySelector('.listing-title').textContent = listing.item.title;
    node.querySelector('.seller-name').textContent = listing.seller.first_name;
    node.querySelector('.seller-badge').outerHTML = badgeForRole(listing.seller.role);
    node.querySelector('.price-value').textContent = listing.price.toFixed(2);
    node.querySelector('.btn-buy').addEventListener('click', () => purchaseListing(listing.id));
    grid.appendChild(node);
  }
}

async function purchaseListing(listingId) {
  try {
    const order = await api('/api/orders', { method: 'POST', body: { listing_id: listingId } });
    showToast('Сделка создана, переходим в комнату сделки');
    window.location.hash = `#/deal/${order.public_code}`;
  } catch (err) {
    showToast(err.message, true);
  }
}

async function loadInventory() {
  screenEl.innerHTML = `
    <div class="section-heading">
      <div>
        <h2>Подарки</h2>
        <p>NFT-подарки Telegram из вашего TON-кошелька, доступные к выставлению на продажу</p>
      </div>
      <button class="btn btn-ghost" id="syncInventoryBtn">Синхронизировать</button>
    </div>
    <div class="listing-grid" id="inventoryGrid"></div>
  `;

  document.getElementById('syncInventoryBtn').addEventListener('click', syncInventory);
  await renderInventory();
}

async function renderInventory() {
  const grid = document.getElementById('inventoryGrid');
  try {
    state.inventory = await api('/api/inventory');
  } catch (err) {
    grid.innerHTML = `<div class="empty-state">${err.message}</div>`;
    return;
  }

  if (state.inventory.length === 0) {
    grid.innerHTML = '<div class="empty-state">Инвентарь пуст. Подключите кошелёк в профиле и нажмите «Синхронизировать».</div>';
    return;
  }

  grid.innerHTML = '';
  const template = document.getElementById('tpl-inventory-card');
  for (const item of state.inventory) {
    const node = template.content.cloneNode(true);
    node.querySelector('.listing-image').src = item.preview_url || '';
    node.querySelector('.listing-title').textContent = item.title;
    node.querySelector('.inventory-rarity').textContent = item.rarity_number ? `Номер #${item.rarity_number}` : '';
    const priceInput = node.querySelector('.price-input');
    const listBtn = node.querySelector('.btn-list');

    if (item.locked) {
      priceInput.disabled = true;
      priceInput.placeholder = 'Уже в активной сделке';
      listBtn.disabled = true;
      listBtn.textContent = 'В сделке';
    } else {
      listBtn.addEventListener('click', () => createListing(item.id, priceInput.value));
    }

    grid.appendChild(node);
  }
}

async function syncInventory() {
  try {
    await api('/api/inventory/sync', { method: 'POST' });
    showToast('Инвентарь обновлён');
    await renderInventory();
  } catch (err) {
    showToast(err.message, true);
  }
}

async function createListing(itemId, priceRaw) {
  const price = parseFloat(priceRaw);
  if (!price || price <= 0) {
    showToast('Укажите корректную цену в GRAM', true);
    return;
  }
  try {
    await api('/api/listings', { method: 'POST', body: { item_id: itemId, price } });
    showToast('Лот выставлен');
    await renderInventory();
  } catch (err) {
    showToast(err.message, true);
  }
}

async function loadDeals() {
  screenEl.innerHTML = `
    <div class="section-heading">
      <div>
        <h2>Мои сделки</h2>
        <p>Все сделки, где вы покупатель или продавец</p>
      </div>
    </div>
    <div class="deal-list" id="dealList"></div>
  `;

  const list = document.getElementById('dealList');
  const codes = Object.keys(state.orders);

  if (codes.length === 0) {
    list.innerHTML = '<div class="empty-state">Сделок пока нет. Купите лот на витрине, чтобы открыть комнату сделки.</div>';
    return;
  }

  list.innerHTML = '';
  for (const code of codes) {
    const order = state.orders[code];
    const row = document.createElement('div');
    row.className = 'deal-row';
    row.innerHTML = `
      <img src="${order.item.preview_url}" alt="">
      <div class="deal-row-main">
        <div class="deal-row-title">${order.item.title}</div>
        <div class="deal-row-sub">${order.price.toFixed(2)} GRAM · ${order.public_code}</div>
      </div>
      <span class="status-pill status-${order.status}">${STATUS_LABELS[order.status] || order.status}</span>
    `;
    row.addEventListener('click', () => { window.location.hash = `#/deal/${order.public_code}`; });
    list.appendChild(row);
  }
}

async function loadDisputes() {
  screenEl.innerHTML = `
    <div class="section-heading">
      <div>
        <h2>Споры</h2>
        <p>Сделки с открытым спором, ожидающие решения арбитра</p>
      </div>
    </div>
    <div class="deal-list" id="disputesList"></div>
  `;

  const list = document.getElementById('disputesList');
  let disputes;
  try {
    disputes = await api('/api/orders/queue/disputes');
  } catch (err) {
    list.innerHTML = `<div class="empty-state">${err.message}</div>`;
    return;
  }

  if (disputes.length === 0) {
    list.innerHTML = '<div class="empty-state">Открытых споров нет.</div>';
    return;
  }

  list.innerHTML = '';
  for (const order of disputes) {
    state.orders[order.public_code] = order;
    const row = document.createElement('div');
    row.className = 'deal-row';
    row.innerHTML = `
      <img src="${order.item.preview_url}" alt="">
      <div class="deal-row-main">
        <div class="deal-row-title">${order.item.title}</div>
        <div class="deal-row-sub">${order.buyer.first_name} ↔ ${order.seller.first_name} · ${order.price.toFixed(2)} GRAM</div>
      </div>
      <span class="status-pill status-disputed">Спор</span>
    `;
    row.addEventListener('click', () => { window.location.hash = `#/deal/${order.public_code}`; });
    list.appendChild(row);
  }
}

async function loadProfile() {
  let instructions = { platform_wallet_address: '—', memo: state.user.deposit_memo };
  try {
    instructions = await api('/api/wallet/deposit/instructions');
  } catch (err) {
    showToast(err.message, true);
  }

  screenEl.innerHTML = `
    <div class="glass-card" style="max-width:560px;margin-bottom:18px">
      <div class="profile-header">
        <div class="profile-avatar">${state.user.first_name.charAt(0).toUpperCase()}</div>
        <div>
          <h2 class="profile-name">${state.user.first_name} ${state.user.last_name || ''}</h2>
          <p class="profile-role">${state.user.username ? '@' + state.user.username : 'Без юзернейма'} · ${state.user.role}</p>
        </div>
      </div>
      <div style="display:flex;gap:24px;flex-wrap:wrap">
        <div>
          <p style="color:var(--text-dim);font-size:12.5px;margin-bottom:4px">Доступно</p>
          <p class="deal-amount" style="font-size:24px">${state.user.available_balance.toFixed(2)}<span class="deal-amount-unit"> GRAM</span></p>
        </div>
        <div>
          <p style="color:var(--text-dim);font-size:12.5px;margin-bottom:4px">В холде (pending)</p>
          <p class="deal-amount" style="font-size:24px;color:var(--accent-amber)">${state.user.pending_balance.toFixed(2)}<span class="deal-amount-unit"> GRAM</span></p>
        </div>
      </div>
      <div style="margin-top:20px">
        <p style="color:var(--text-dim);font-size:13px;margin-bottom:6px">TON-кошелёк</p>
        <div class="wallet-row">
          <div class="price-input" style="display:flex;align-items:center;color:${state.user.ton_wallet_address ? 'var(--text-primary)' : 'var(--text-dim)'}">
            ${state.user.ton_wallet_address ? shortenAddress(state.user.ton_wallet_address) : 'Кошелёк не подключён'}
          </div>
          <button class="btn btn-primary" id="tonConnectBtn">${state.user.ton_wallet_address ? 'Сменить' : 'Подключить'}</button>
        </div>
      </div>
    </div>

    <div class="glass-card" style="max-width:560px;margin-bottom:18px">
      <h3 style="margin:0 0 6px">Пополнение баланса</h3>
      <p style="color:var(--text-dim);font-size:13px;margin:0 0 14px">
        Переведите TON на кошелёк платформы ниже, обязательно указав memo-комментарий к переводу.
        Без правильного memo зачисление не произойдёт.
      </p>
      <div class="wallet-row" style="margin-bottom:8px">
        <input class="price-input" readonly value="${instructions.platform_wallet_address}">
      </div>
      <div class="wallet-row">
        <input class="price-input" readonly value="${instructions.memo}">
        <button class="btn btn-primary" id="syncDepositBtn">Проверить платёж</button>
      </div>
    </div>

    <div class="glass-card" style="max-width:560px">
      <h3 style="margin:0 0 6px">Вывод средств</h3>
      <p style="color:var(--text-dim);font-size:13px;margin:0 0 14px">
        Выводить можно только доступный баланс. Заявка проходит проверку арбитра платформы перед отправкой.
      </p>
      <div class="wallet-row" style="margin-bottom:8px">
        <input class="price-input" id="withdrawAmount" type="number" min="1" step="0.01" placeholder="Сумма в GRAM">
        <input class="price-input" id="withdrawAddress" placeholder="Адрес TON-кошелька" value="${state.user.ton_wallet_address || ''}">
      </div>
      <button class="btn btn-primary btn-block" id="withdrawBtn">Запросить вывод</button>
    </div>
  `;

  document.getElementById('tonConnectBtn').addEventListener('click', () => {
    if (!tonConnectUI) {
      showToast('TonConnect не удалось загрузить. Проверьте подключение к интернету', true);
      return;
    }
    tonConnectUI.openModal();
  });

  document.getElementById('syncDepositBtn').addEventListener('click', async () => {
    try {
      state.user = await api('/api/wallet/deposit/sync', { method: 'POST' });
      updateBalanceDisplay();
      showToast('Баланс обновлён');
      await loadProfile();
    } catch (err) {
      showToast(err.message, true);
    }
  });

  document.getElementById('withdrawBtn').addEventListener('click', async () => {
    const amount = parseFloat(document.getElementById('withdrawAmount').value);
    const destination_address = document.getElementById('withdrawAddress').value.trim();
    if (!amount || amount <= 0 || !destination_address) {
      showToast('Укажите сумму и адрес назначения', true);
      return;
    }
    try {
      await api('/api/wallet/withdraw', { method: 'POST', body: { amount, destination_address } });
      showToast('Заявка на вывод отправлена на проверку арбитру');
      state.user = await api('/api/auth/me');
      updateBalanceDisplay();
      await loadProfile();
    } catch (err) {
      showToast(err.message, true);
    }
  });
}

function renderTimeline(order) {
  const steps = [
    { key: 'awaiting_payment', label: 'Ожидание оплаты', sub: 'Покупатель вносит средства на депонирование' },
    { key: 'escrow_locked', label: 'Средства заморожены гарантом', sub: 'GRAM удержаны до завершения сделки' },
    { key: 'asset_transferred', label: 'Передача подарка', sub: 'Продавец передаёт предмет покупателю' },
    { key: 'hold_period', label: 'Холд 24 часа', sub: 'Период для проверки перед финальным зачислением' },
    { key: 'completed', label: 'Успешно завершено', sub: 'Средства зачислены продавцу' },
  ];

  const order_index = steps.findIndex(s => s.key === order.status);
  const isDisputed = order.status === 'disputed';
  const isRefunded = order.status === 'refunded';

  return steps.map((step, idx) => {
    let cls = '';
    if (isDisputed || isRefunded) {
      cls = idx < steps.length ? '' : '';
    } else if (order_index > idx) {
      cls = 'done';
    } else if (order_index === idx) {
      cls = 'current';
    }
    return `
      <div class="timeline-step ${cls}">
        <span class="timeline-dot"></span>
        <div>
          <div class="timeline-label">${step.label}</div>
          <div class="timeline-sub">${step.sub}</div>
        </div>
      </div>
    `;
  }).join('') + (isDisputed ? `
    <div class="timeline-step danger current">
      <span class="timeline-dot"></span>
      <div>
        <div class="timeline-label">Открыт спор</div>
        <div class="timeline-sub">${order.dispute_reason || ''}</div>
      </div>
    </div>
  ` : '') + (isRefunded ? `
    <div class="timeline-step danger done">
      <span class="timeline-dot"></span>
      <div>
        <div class="timeline-label">Средства возвращены покупателю</div>
        <div class="timeline-sub">Решение арбитра по спору</div>
      </div>
    </div>
  ` : '');
}

function renderDealActions(order) {
  const isBuyer = order.buyer.id === state.user.id;
  const isSeller = order.seller.id === state.user.id;
  const isArbiter = state.user.role === 'arbiter';
  const buttons = [];

  if (isBuyer && order.status === 'awaiting_payment') {
    buttons.push(`<button class="btn btn-primary" data-action="pay">Оплатить и заморозить в Гаранте</button>`);
  }
  if (isSeller && order.status === 'escrow_locked') {
    buttons.push(`<button class="btn btn-primary" data-action="confirm-transfer">Подтвердить передачу</button>`);
  }
  if (isBuyer && order.status === 'asset_transferred') {
    buttons.push(`<button class="btn btn-primary" data-action="confirm-receipt">Подтвердить получение</button>`);
  }
  if ((isBuyer || isSeller) && !['completed', 'cancelled', 'refunded', 'disputed'].includes(order.status)) {
    buttons.push(`<button class="btn btn-danger" data-action="dispute">Открыть спор</button>`);
  }
  if (isArbiter && order.status === 'disputed') {
    buttons.push(`<button class="btn btn-primary" data-action="resolve-seller">Решить в пользу продавца</button>`);
    buttons.push(`<button class="btn btn-danger" data-action="resolve-buyer">Вернуть покупателю</button>`);
  }

  return buttons.join('');
}

async function loadDeal(code) {
  screenEl.innerHTML = '<div class="empty-state">Загрузка сделки…</div>';

  let order;
  try {
    order = await api(`/api/orders/${code}`);
  } catch (err) {
    if (err.status === 403) {
      screenEl.innerHTML = `
        <div class="glass-card access-blocked">
          <div class="icon">🔒</div>
          <h2>Доступ ограничен</h2>
          <p>Вы не являетесь участником этой сделки.</p>
        </div>
      `;
      return;
    }
    screenEl.innerHTML = `<div class="empty-state">${err.message}</div>`;
    return;
  }

  state.orders[order.public_code] = order;
  state.currentOrder = order;
  enterDealIslandMode(order);

  screenEl.innerHTML = `
    <div class="deal-page">
      <div>
        <div class="glass-card" style="margin-bottom:18px">
          <div class="deal-asset-image"><img src="${order.item.preview_url}" alt=""></div>
          <h3 style="margin:0 0 4px">${order.item.title}</h3>
          <p class="deal-amount">${order.price.toFixed(2)}<span class="deal-amount-unit"> GRAM</span></p>
          <div class="deal-parties">
            <div>Покупатель: <b>${order.buyer.first_name}</b></div>
            <div>Продавец: <b>${order.seller.first_name}</b></div>
            <div>Код сделки: <b>${order.public_code}</b></div>
          </div>
        </div>
        <div class="glass-card">
          <div class="timeline">${renderTimeline(order)}</div>
          <div class="deal-actions" id="dealActions">${renderDealActions(order)}</div>
        </div>
      </div>
      <div class="glass-card deal-chat">
        <div class="chat-messages" id="chatMessages"></div>
        <div class="chat-input-row">
          <input class="chat-input" id="chatInput" placeholder="Написать сообщение…">
          <button class="btn btn-primary" id="chatSendBtn">Отправить</button>
        </div>
      </div>
    </div>
  `;

  bindDealActions(order);
  await loadChatHistory(order.public_code);
  connectChatSocket(order.public_code);

  document.getElementById('chatSendBtn').addEventListener('click', () => sendChatMessage(order.public_code));
  document.getElementById('chatInput').addEventListener('keydown', (e) => {
    if (e.key === 'Enter') sendChatMessage(order.public_code);
  });
}

function bindDealActions(order) {
  const container = document.getElementById('dealActions');
  container.querySelectorAll('button').forEach(btn => {
    btn.addEventListener('click', async () => {
      const action = btn.dataset.action;
      try {
        if (action === 'pay') {
          await api(`/api/orders/${order.public_code}/pay`, { method: 'POST' });
        } else if (action === 'confirm-transfer') {
          await api(`/api/orders/${order.public_code}/confirm-transfer`, { method: 'POST' });
        } else if (action === 'confirm-receipt') {
          await api(`/api/orders/${order.public_code}/confirm-receipt`, { method: 'POST' });
        } else if (action === 'dispute') {
          const reason = prompt('Опишите суть проблемы для арбитра:');
          if (!reason) return;
          await api(`/api/orders/${order.public_code}/dispute`, { method: 'POST', body: { reason } });
        } else if (action === 'resolve-seller') {
          await api(`/api/orders/${order.public_code}/dispute/resolve`, { method: 'POST', body: { resolution: 'release_seller' } });
        } else if (action === 'resolve-buyer') {
          await api(`/api/orders/${order.public_code}/dispute/resolve`, { method: 'POST', body: { resolution: 'refund_buyer' } });
        }
        showToast('Статус сделки обновлён');
        await loadDeal(order.public_code);
      } catch (err) {
        showToast(err.message, true);
      }
    });
  });
}

async function loadChatHistory(code) {
  const box = document.getElementById('chatMessages');
  try {
    const messages = await api(`/api/orders/${code}/messages`);
    box.innerHTML = '';
    messages.forEach(m => appendChatMessage(m));
  } catch (err) {
    box.innerHTML = `<div class="empty-state">${err.message}</div>`;
  }
}

function appendChatMessage(message) {
  const box = document.getElementById('chatMessages');
  if (!box) return;
  const bubble = document.createElement('div');
  bubble.className = 'chat-bubble' + (message.sender_id === state.user.id ? ' mine' : '');
  const time = new Date(message.created_at).toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' });
  bubble.innerHTML = `<div>${escapeHtml(message.body)}</div><div class="chat-bubble-meta">${time}</div>`;
  box.appendChild(bubble);
  box.scrollTop = box.scrollHeight;
}

function escapeHtml(text) {
  const div = document.createElement('div');
  div.textContent = text;
  return div.innerHTML;
}

function connectChatSocket(code) {
  if (state.socket) {
    state.socket.close();
    state.socket = null;
  }

  const socket = new WebSocket(`${WS_BASE}/api/orders/${code}/ws?token=${encodeURIComponent(state.token)}`);
  socket.onmessage = (event) => {
    const data = JSON.parse(event.data);
    if (data.type === 'message') {
      appendChatMessage(data);
    } else if (data.type === 'status_changed') {
      loadDeal(code);
    }
  };
  state.socket = socket;
}

function sendChatMessage(code) {
  const input = document.getElementById('chatInput');
  const body = input.value.trim();
  if (!body) return;
  if (state.socket && state.socket.readyState === WebSocket.OPEN) {
    state.socket.send(JSON.stringify({ body }));
  } else {
    api(`/api/orders/${code}/messages`, { method: 'POST', body: { body } }).catch(err => showToast(err.message, true));
  }
  input.value = '';
}

function setActiveNav(route) {
  document.querySelectorAll('.nav-item, .bottom-btn').forEach(el => {
    el.classList.toggle('active', el.dataset.route === route);
  });
}

async function router() {
  const hash = window.location.hash;
  const dealMatch = hash.match(/^#\/deal\/(.+)$/);

  if (dealMatch) {
    await loadDeal(dealMatch[1]);
    return;
  }

  let route = hash.replace('#/', '') || 'catalog';
  if (route === 'collection') route = 'gifts';
  state.route = route;
  setActiveNav(route);
  enterNavIslandMode(ROUTE_LABELS[route] || 'SwitchMarket');

  if (route === 'catalog') await loadCatalog();
  else if (route === 'deals') await loadDeals();
  else if (route === 'gifts') await loadInventory();
  else if (route === 'profile') await loadProfile();
  else if (route === 'disputes') await loadDisputes();
  else await loadCatalog();
}

function bindNav() {
  document.querySelectorAll('.nav-item, .bottom-btn').forEach(el => {
    el.addEventListener('click', () => {
      window.location.hash = `#/${el.dataset.route}`;
    });
  });

  document.getElementById('islandPrimaryBtn').addEventListener('click', (e) => {
    window.location.hash = `#/${e.currentTarget.dataset.target || 'catalog'}`;
  });
  document.getElementById('islandDealsBtn').addEventListener('click', () => {
    window.location.hash = '#/deals';
  });
}

async function bootstrap() {
  bindNav();
  const ok = await authenticate();
  if (!ok) {
    screenEl.innerHTML = `
      <div class="glass-card access-blocked">
        <div class="icon">🔐</div>
        <h2>Требуется авторизация Telegram</h2>
        <p>Откройте SwitchMarket через кнопку в Telegram-боте, чтобы продолжить.</p>
      </div>
    `;
    return;
  }

  initTonConnect();
  window.addEventListener('hashchange', router);
  await router();
}

bootstrap();
