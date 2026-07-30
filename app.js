// appState is the one shared source of truth, fetched from the server.
// Every visitor who loads this page sees the same restaurants and reports —
// this replaces the old localStorage version, where every browser had its
// own private copy and nobody ever saw anyone else's reports.
let appState = null;

async function refreshState() {
  const res = await fetch('/api/state');
  appState = await res.json();
  renderAll();
}

function getBadgeClass(score) {
  if (score >= 85) return 'safe';
  if (score >= 70) return 'watch';
  return 'alert';
}

async function submitAssistantQuestion(event) {
  event.preventDefault();
  const input = document.getElementById('assistantInput');
  const prompt = input.value.trim();
  if (!prompt) return;

  const responseBox = document.getElementById('assistantResponse');
  const statusBox = document.getElementById('assistantStatus');
  responseBox.textContent = 'Thinking…';
  statusBox.textContent = 'Contacting Gemma…';

  try {
    const response = await fetch('/api/assistant', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ prompt })
    });

    const data = await response.json();
    responseBox.textContent = data.answer || 'No answer returned.';
    statusBox.textContent = data.source === 'gemma' ? 'Live Gemma response' : 'Local fallback response';
  } catch (error) {
    responseBox.textContent = 'The assistant could not reach the service. Please try again.';
    statusBox.textContent = 'Service unavailable';
  }
}

function renderRestaurants() {
  const searchTerm = document.getElementById('searchInput').value.trim().toLowerCase();
  const filtered = appState.restaurants.filter((restaurant) => {
    const haystack = `${restaurant.name} ${restaurant.campus}`.toLowerCase();
    return haystack.includes(searchTerm);
  });

  const container = document.getElementById('restaurantList');
  if (!filtered.length) {
    container.innerHTML = '<div class="empty-state">No restaurants match that search.</div>';
    return;
  }

  container.innerHTML = filtered.map((restaurant) => {
    const badgeClass = getBadgeClass(restaurant.score);
    return `
      <article class="placard">
        <div class="placard-top">
          <div>
            <h4>${restaurant.name}</h4>
            <p>${restaurant.campus}</p>
          </div>
          <span class="stamp ${badgeClass}">${restaurant.score}</span>
        </div>
        <hr class="placard-rule" />
        <div class="placard-readout">
          <div class="readout-line">
            <span>Status</span>
            <span class="badge ${badgeClass}">${restaurant.safety}</span>
          </div>
          <div class="readout-line">
            <span>Open incidents</span>
            <span>${restaurant.reports}</span>
          </div>
          <div class="readout-line">
            <span>Escalations</span>
            <span>${restaurant.alerts}</span>
          </div>
        </div>
      </article>
    `;
  }).join('');
}

function renderReports() {
  const feed = document.getElementById('reportFeed');
  const visibleReports = appState.reports.filter((report) => report.status !== 'dismissed').slice(0, 5);

  if (!visibleReports.length) {
    feed.innerHTML = '<div class="empty-state">No new reports yet.</div>';
    return;
  }

  feed.innerHTML = visibleReports.map((report) => `
    <div class="feed-card">
      <strong>${report.restaurant}</strong>
      <div class="meta">${report.concern} • ${report.severity} • ${report.time}</div>
      <div>${report.details}</div>
    </div>
  `).join('');
}

function renderReviewQueue() {
  const queue = document.getElementById('reviewQueue');
  const pendingReports = appState.reports.slice().sort((a, b) => (a.status === 'pending' ? -1 : 1));

  if (!pendingReports.length) {
    queue.innerHTML = '<div class="empty-state">The docket is clear.</div>';
    return;
  }

  queue.innerHTML = pendingReports.map((report) => `
    <div class="review-card">
      <div class="review-top">
        <div>
          <h4>${report.restaurant}</h4>
          <p>${report.concern} • ${report.severity}</p>
        </div>
        <span class="status-pill ${report.status}">${report.status}</span>
      </div>
      <div class="meta">${report.details}</div>
      <div class="review-actions">
        ${report.status === 'pending' ? `
          <button class="action-btn approve" data-action="approve" data-id="${report.id}" type="button">Approve</button>
          <button class="action-btn escalate" data-action="escalate" data-id="${report.id}" type="button">Escalate</button>
          <button class="action-btn dismiss" data-action="dismiss" data-id="${report.id}" type="button">Dismiss</button>
        ` : ''}
      </div>
    </div>
  `).join('');
}

function renderAnalytics() {
  const concerns = appState.reports.reduce((acc, report) => {
    acc[report.concern] = (acc[report.concern] || 0) + 1;
    return acc;
  }, {});
  const topConcern = Object.entries(concerns).sort((a, b) => b[1] - a[1])[0] || ['Food poisoning', 0];
  const escalated = appState.reports.filter((report) => report.status === 'escalated').length;
  const reviewed = appState.reports.filter((report) => report.status === 'reviewed').length;
  const responseTime = Math.max(8, 18 - Math.min(10, appState.reports.length));

  document.getElementById('activeReports').textContent = appState.reports.filter((report) => report.status !== 'dismissed').length;
  document.getElementById('riskSpots').textContent = appState.restaurants.filter((restaurant) => restaurant.score < 75).length;
  document.getElementById('responseTime').textContent = `${responseTime}m`;

  const analytics = document.getElementById('analyticsCards');
  analytics.innerHTML = `
    <div class="analytics-card">
      <span>Reviewed reports</span>
      <strong>${reviewed}</strong>
    </div>
    <div class="analytics-card">
      <span>Escalated alerts</span>
      <strong>${escalated}</strong>
    </div>
    <div class="analytics-card">
      <span>Top concern pattern</span>
      <strong>${topConcern[0]}</strong>
    </div>
  `;

  const riskList = document.getElementById('riskList');
  const ranked = [...appState.restaurants].sort((a, b) => a.score - b.score).slice(0, 3);
  riskList.innerHTML = ranked.map((restaurant) => `
    <div class="risk-card">
      <div class="restaurant-top">
        <div>
          <h4>${restaurant.name}</h4>
          <p>${restaurant.campus}</p>
        </div>
        <span class="badge ${getBadgeClass(restaurant.score)}">${restaurant.score}</span>
      </div>
    </div>
  `).join('');
}

function populateRestaurantOptions() {
  const select = document.getElementById('restaurantSelect');
  select.innerHTML = appState.restaurants.map((restaurant) => `<option value="${restaurant.id}">${restaurant.name}</option>`).join('');
}

function openModal() {
  document.getElementById('reportModal').classList.remove('hidden');
}

function closeModal() {
  document.getElementById('reportModal').classList.add('hidden');
  document.getElementById('reportForm').reset();
}

function openRegisterModal() {
  document.getElementById('registerModal').classList.remove('hidden');
}

function closeRegisterModal() {
  document.getElementById('registerModal').classList.add('hidden');
  document.getElementById('registerForm').reset();
}

async function handleSubmit(event) {
  event.preventDefault();
  const form = event.target;
  const restaurantId = Number(form.restaurantSelect.value);

  const submitBtn = form.querySelector('button[type="submit"]');
  submitBtn.disabled = true;
  submitBtn.textContent = 'Submitting…';

  try {
    const res = await fetch('/api/reports', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        restaurantId,
        concern: form.concernSelect.value,
        severity: form.severitySelect.value,
        details: form.detailsInput.value.trim()
      })
    });
    appState = await res.json();
    renderAll();
    closeModal();
  } catch (err) {
    alert('Could not submit the report — check your connection and try again.');
  } finally {
    submitBtn.disabled = false;
    submitBtn.textContent = 'Submit report';
  }
}

async function handleRegisterSubmit(event) {
  event.preventDefault();
  const form = event.target;
  const submitBtn = form.querySelector('button[type="submit"]');
  submitBtn.disabled = true;
  submitBtn.textContent = 'Adding…';

  try {
    const res = await fetch('/api/restaurants', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        name: form.restaurantNameInput.value.trim(),
        campus: form.restaurantCampusInput.value.trim()
      })
    });

    if (!res.ok) {
      const err = await res.json();
      alert(err.error || 'Could not register that restaurant.');
      return;
    }

    appState = await res.json();
    renderAll();
    closeRegisterModal();
  } catch (err) {
    alert('Could not reach the server — check your connection and try again.');
  } finally {
    submitBtn.disabled = false;
    submitBtn.textContent = 'Add to board';
  }
}

async function handleReviewAction(event) {
  const button = event.target.closest('[data-action]');
  if (!button) return;
  button.disabled = true;

  try {
    const res = await fetch(`/api/reports/${button.dataset.id}/review`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action: button.dataset.action })
    });
    appState = await res.json();
    renderAll();
  } catch (err) {
    alert('Could not update the report — check your connection and try again.');
    button.disabled = false;
  }
}

function renderAll() {
  renderRestaurants();
  renderReports();
  renderReviewQueue();
  renderAnalytics();
  populateRestaurantOptions();
}

document.getElementById('openReportBtn').addEventListener('click', openModal);
document.getElementById('closeModalBtn').addEventListener('click', closeModal);
document.getElementById('cancelBtn').addEventListener('click', closeModal);
document.getElementById('reportModal').addEventListener('click', (event) => {
  if (event.target.id === 'reportModal') closeModal();
});
document.getElementById('reportForm').addEventListener('submit', handleSubmit);

document.getElementById('openRegisterBtn').addEventListener('click', openRegisterModal);
document.getElementById('closeRegisterModalBtn').addEventListener('click', closeRegisterModal);
document.getElementById('cancelRegisterBtn').addEventListener('click', closeRegisterModal);
document.getElementById('registerModal').addEventListener('click', (event) => {
  if (event.target.id === 'registerModal') closeRegisterModal();
});
document.getElementById('registerForm').addEventListener('submit', handleRegisterSubmit);

document.getElementById('searchInput').addEventListener('input', renderRestaurants);
document.getElementById('reviewQueue').addEventListener('click', handleReviewAction);
document.getElementById('assistantForm').addEventListener('submit', submitAssistantQuestion);

refreshState();
