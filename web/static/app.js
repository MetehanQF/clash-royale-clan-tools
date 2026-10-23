const playerList = document.getElementById('players');
const errorMessage = document.getElementById('error-message');
const refreshButton = document.getElementById('refresh-button');
const filters = [...document.querySelectorAll('.filter')];
const historyFilters = [...document.querySelectorAll('.history-filter')];
const weekTabs = [...document.querySelectorAll('.week-tab')];
const modal = document.getElementById('player-modal');
const modalPanel = modal.querySelector('.modal-panel');
let players = [];
let weeks = [];
let activeFilter = 'all';
let historyFilter = 'all';
let activeWeek = 'today';
let loading = false;
let historyLoading = false;
let historyLoaded = false;
let lastFocus = null;

const number = value => new Intl.NumberFormat('tr-TR').format(value);
const escapeHtml = value => String(value).replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
const medalPercent = fame => Math.min(100, fame / 2400 * 100);
const medalClass = fame => fame >= 2400 ? 'reached' : 'below';
const statusClass = player => player.decksUsedToday >= 4 ? 'done' : player.decksUsedToday === 0 ? 'idle' : 'pending';
const statusText = player => player.decksUsedToday >= 4 ? 'Günlük tamamlandı' : player.decksUsedToday === 0 ? 'Henüz başlamadı' : 'Günlük eksik';

function filteredPlayers() {
  if (activeWeek !== 'today') {
    const week = weeks[Number(activeWeek)];
    const list = week?.players || [];
    return list.filter(player => historyFilter === 'under2400' ? player.fame < 2400 : historyFilter === 'reached' ? player.fame >= 2400 : true);
  }
  return players.filter(player => {
    if (activeFilter === 'remaining') return player.remainingToday > 0;
    if (activeFilter === 'zero') return player.decksUsedToday === 0;
    if (activeFilter === 'under2400') return player.fame < 2400;
    if (activeFilter === 'completed') return player.decksUsedToday >= 4;
    return true;
  });
}

function medalMarkup(player) {
  const achieved = player.fame >= 2400;
  return `<div class="medal-head"><span class="metric-kicker"><span class="metric-icon">◈</span> HAFTALIK MADALYA</span><strong>${number(player.fame)} <small>/ 2.400</small></strong></div><div class="progress-track medal-track"><span class="progress-fill medal-fill ${medalClass(player.fame)}" style="width:${medalPercent(player.fame)}%"></span></div><span class="target-note ${medalClass(player.fame)}">${achieved ? '✦ 2400 hedefi geçildi' : '2400 hedefine ilerliyor'}</span>`;
}

function renderPlayers() {
  if (activeWeek !== 'today' && !historyLoaded) return;
  const shown = filteredPlayers();
  document.getElementById('visible-count').textContent = number(shown.length);
  if (!shown.length) {
    playerList.innerHTML = `<div class="empty-state">${activeWeek !== 'today' && !weeks[Number(activeWeek)] ? 'Bu hafta için API geçmiş kaydı bulunmuyor.' : 'Bu filtreye uyan oyuncu yok.'}</div>`;
    return;
  }
  playerList.innerHTML = shown.map((player, index) => {
    const history = activeWeek !== 'today';
    const daily = history ? 0 : Math.min(4, player.decksUsedToday);
    const state = history ? medalClass(player.fame) : statusClass(player);
    return `<article class="player-card ${state} ${history ? 'history-card' : ''}" tabindex="0" role="button" aria-label="${escapeHtml(player.name)} detayını aç" data-player-index="${index}">
      <div class="player-top"><div class="identity"><span class="rank">${String(index + 1).padStart(2, '0')}</span><span class="avatar">${escapeHtml(player.name.trim().charAt(0).toLocaleUpperCase('tr-TR') || '?')}</span><span class="identity-copy"><strong>${escapeHtml(player.name)}</strong><small>${escapeHtml(player.tag)}</small></span></div><span class="detail-link">DETAY <span>↗</span></span></div>
      <div class="player-body"><div class="medal-block">${medalMarkup(player)}</div>${history ? '' : `<div class="battle-block"><div class="battle-head"><span class="metric-kicker">⚔ BUGÜNKÜ SAVAŞ</span><strong>${daily}<small> / 4</small></strong></div><div class="battle-segments">${[0,1,2,3].map(i => `<span class="${i < daily ? 'used' : ''}"></span>`).join('')}</div><div class="battle-foot"><span class="remaining-badge">${player.remainingToday} HAK KALDI</span><span>Toplam deste <b>${number(player.decksUsed)}</b></span></div></div>`}</div>
      <div class="player-bottom"><span class="status-pill ${state}"><span class="status-dot"></span>${history ? player.fame >= 2400 ? 'Hedef geçildi' : 'Hedef altında' : statusText(player)}</span><span class="card-chevron">›</span></div>
    </article>`;
  }).join('');
  playerList.classList.remove('fresh');
  void playerList.offsetWidth;
  playerList.classList.add('fresh');
}

function showError(message) { errorMessage.textContent = message; errorMessage.hidden = false; }
function clearError() { errorMessage.hidden = true; }
function updateView() {
  const history = activeWeek !== 'today';
  document.getElementById('today-summary').hidden = history;
  document.getElementById('today-filters').hidden = history;
  document.getElementById('history-filters').hidden = !history;
  refreshButton.hidden = history;
  document.getElementById('roster-eyebrow').innerHTML = history ? 'YARIŞ GEÇMİŞİ <span>✦</span>' : 'KLAN KADROSU <span>✦</span>';
  document.getElementById('roster-heading').innerHTML = `${history ? `${Number(activeWeek) + 1}. Hafta` : 'Savaşçılar'} <span id="visible-count" class="count-badge">0</span>`;
  document.getElementById('week-description').textContent = history ? 'Tamamlanmış yarışın haftalık madalya sonuçları' : 'Bugünkü savaş hakları ve haftalık madalyalar';
  weekTabs.forEach(tab => { const selected = tab.dataset.week === activeWeek; tab.classList.toggle('active', selected); selected ? tab.setAttribute('aria-current', 'page') : tab.removeAttribute('aria-current'); });
  clearError();
  if (history && !historyLoaded) { playerList.innerHTML = '<div class="empty-state">Yarış geçmişi yükleniyor…</div>'; document.getElementById('visible-count').textContent = '0'; }
  else renderPlayers();
}

async function loadHistory() {
  if (historyLoading) return;
  historyLoading = true;
  try {
    const response = await fetch('/api/history', {cache: 'no-store'});
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || 'Geçmiş yarış verileri alınamadı.');
    weeks = data.weeks || [];
    historyLoaded = true;
    if (activeWeek !== 'today') renderPlayers();
  } catch (error) {
    if (activeWeek !== 'today') { showError(error.message || 'Yarış geçmişi alınamadı.'); playerList.innerHTML = '<div class="empty-state">Geçmiş veriler yüklenemedi. Sekmeye tekrar dokunarak yeniden deneyin.</div>'; }
  } finally { historyLoading = false; }
}

async function loadData() {
  if (loading) return;
  loading = true;
  refreshButton.disabled = true;
  refreshButton.classList.add('loading');
  try {
    const response = await fetch('/api/river-race', {cache: 'no-store'});
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || 'Veriler alınamadı. Lütfen tekrar deneyin.');
    players = data.players;
    document.getElementById('clan-name').textContent = data.clanName;
    document.getElementById('clan-tag').textContent = data.clanTag;
    document.getElementById('race-state').textContent = data.state === 'warDay' ? 'Savaş günü · API aktif' : data.state === 'collectionDay' ? 'Hazırlık günü · API aktif' : 'Canlı API bağlantısı';
    for (const [key, value] of Object.entries(data.summary)) document.getElementById(`stat-${key}`).textContent = number(value);
    document.getElementById('last-updated').textContent = `Son güncelleme ${new Date().toLocaleTimeString('tr-TR', {hour:'2-digit', minute:'2-digit', second:'2-digit'})}`;
    if (activeWeek === 'today') { clearError(); renderPlayers(); document.querySelector('.hero').classList.remove('updated-pulse'); void document.querySelector('.hero').offsetWidth; document.querySelector('.hero').classList.add('updated-pulse'); }
  } catch (error) {
    if (activeWeek === 'today') { showError(error.message || 'Beklenmeyen bir hata oluştu. Yeniden deneyin.'); if (!players.length) playerList.innerHTML = '<div class="empty-state">Veriler yüklenemedi. Yenile butonuyla tekrar deneyin.</div>'; }
  } finally { loading = false; refreshButton.disabled = false; refreshButton.classList.remove('loading'); }
}

function openModal(player) {
  lastFocus = document.activeElement;
  const history = activeWeek !== 'today';
  const state = history ? medalClass(player.fame) : statusClass(player);
  document.getElementById('modal-content').innerHTML = `<div class="modal-hero"><span class="modal-avatar">${escapeHtml(player.name.trim().charAt(0).toLocaleUpperCase('tr-TR') || '?')}</span><div><p class="eyebrow">OYUNCU KARTI ✦</p><h2 id="modal-name">${escapeHtml(player.name)}</h2><span class="modal-tag">${escapeHtml(player.tag)}</span></div></div><div class="modal-medals"><div class="modal-section-head"><span>◈ HAFTALIK MADALYA</span><strong>${number(player.fame)} <small>/ 2.400</small></strong></div><div class="progress-track"><span class="progress-fill medal-fill ${medalClass(player.fame)}" style="width:${medalPercent(player.fame)}%"></span></div><span class="target-note ${medalClass(player.fame)}">${player.fame >= 2400 ? '✦ 2400 hedefi geçildi' : '2400 hedefinin altında'}</span></div>${history ? '' : `<div class="modal-stats"><div><span>BUGÜNKÜ SAVAŞ</span><strong>${Math.min(4, player.decksUsedToday)} <small>/ 4</small></strong></div><div><span>KALAN HAK</span><strong>${number(player.remainingToday)}</strong></div><div><span>TOPLAM DESTE</span><strong>${number(player.decksUsed)}</strong></div></div>`}<div class="modal-result"><span>DURUM</span><span class="status-pill ${state}"><span class="status-dot"></span>${history ? player.fame >= 2400 ? 'Hedef geçildi' : 'Hedef altında' : statusText(player)}</span></div>`;
  modal.hidden = false;
  document.body.classList.add('modal-open');
  modalPanel.focus();
}
function closeModal() { modal.hidden = true; document.body.classList.remove('modal-open'); lastFocus?.focus(); }

filters.forEach(button => button.addEventListener('click', () => { activeFilter = button.dataset.filter; filters.forEach(filter => { const selected = filter === button; filter.classList.toggle('active', selected); filter.setAttribute('aria-pressed', String(selected)); }); renderPlayers(); }));
historyFilters.forEach(button => button.addEventListener('click', () => { historyFilter = button.dataset.historyFilter; historyFilters.forEach(filter => { const selected = filter === button; filter.classList.toggle('active', selected); filter.setAttribute('aria-pressed', String(selected)); }); renderPlayers(); }));
weekTabs.forEach(button => button.addEventListener('click', () => { activeWeek = button.dataset.week; updateView(); if (activeWeek !== 'today' && !historyLoaded) loadHistory(); }));
playerList.addEventListener('click', event => { const card = event.target.closest('[data-player-index]'); if (card) openModal(filteredPlayers()[Number(card.dataset.playerIndex)]); });
playerList.addEventListener('keydown', event => { if (event.key === 'Enter' || event.key === ' ') { const card = event.target.closest('[data-player-index]'); if (card) { event.preventDefault(); openModal(filteredPlayers()[Number(card.dataset.playerIndex)]); } } });
modal.addEventListener('click', event => { if (event.target.closest('[data-close-modal]')) closeModal(); });
document.addEventListener('keydown', event => { if (event.key === 'Escape' && !modal.hidden) closeModal(); });
refreshButton.addEventListener('click', loadData);
loadData();
setInterval(loadData, 30000);
