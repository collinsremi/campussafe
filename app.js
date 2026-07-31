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

function getBadgeClass(restaurant) {
  if (restaurant.reports === 0) return 'unrated';
  if (restaurant.score < 25) return 'safe';
  if (restaurant.score < 55) return 'watch';
  return 'alert';
}

const prefersReducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

function animateLedgerValue(el, nextValue, suffix = '') {
  const prevValue = Number(el.dataset.value || 0);
  el.dataset.value = nextValue;

  if (prefersReducedMotion || prevValue === nextValue) {
    el.textContent = `${nextValue}${suffix}`;
    return;
  }

  const duration = 420;
  const start = performance.now();

  function tick(now) {
    const progress = Math.min(1, (now - start) / duration);
    const eased = 1 - Math.pow(1 - progress, 3);
    const current = Math.round(prevValue + (nextValue - prevValue) * eased);
    el.textContent = `${current}${suffix}`;
    if (progress < 1) requestAnimationFrame(tick);
  }
  requestAnimationFrame(tick);
}

let chatHistory = [];

function renderChatMessages() {
  const container = document.getElementById('chatMessages');
  if (!chatHistory.length) {
    container.innerHTML = '<div class="chat-empty">Ask about a specific restaurant, or the current campus-wide risk picture.</div>';
    return;
  }
  container.innerHTML = chatHistory.map((msg) => {
    if (msg.role === 'user') {
      return `<div class="chat-bubble user">${escapeHtml(msg.text)}</div>`;
    }
    if (msg.role === 'thinking') {
      return `<div class="chat-bubble assistant thinking" id="chatThinking"><span></span><span></span><span></span></div>`;
    }
    const caption = msg.source && msg.source !== 'gemma'
      ? `<div class="chat-caption">local summary — Gemma unavailable</div>`
      : '';
    return `<div class="chat-bubble assistant">${escapeHtml(msg.text)}${caption}</div>`;
  }).join('');
  container.scrollTop = container.scrollHeight;
}

function escapeHtml(str) {
  const div = document.createElement('div');
  div.textContent = str;
  return div.innerHTML;
}

async function submitAssistantQuestion(event) {
  event.preventDefault();
  const input = document.getElementById('assistantInput');
  const prompt = input.value.trim();
  if (!prompt) return;

  chatHistory.push({ role: 'user', text: prompt });
  chatHistory.push({ role: 'thinking' });
  renderChatMessages();
  input.value = '';

  try {
    const response = await fetch('/api/assistant', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ prompt })
    });
    const data = await response.json();
    chatHistory.pop(); // remove the thinking placeholder
    chatHistory.push({ role: 'assistant', text: data.answer || "I couldn't find an answer to that.", source: data.source });
  } catch (error) {
    chatHistory.pop();
    chatHistory.push({ role: 'assistant', text: 'The assistant could not reach the service. Please try again.' });
  }
  renderChatMessages();
}

function openChat() {
  document.getElementById('chatPanel').classList.remove('hidden');
  document.getElementById('chatFab').classList.add('active');
  renderChatMessages();
  document.getElementById('assistantInput').focus();
}

function closeChat() {
  document.getElementById('chatPanel').classList.add('hidden');
  document.getElementById('chatFab').classList.remove('active');
}

function toggleChat() {
  const isHidden = document.getElementById('chatPanel').classList.contains('hidden');
  if (isHidden) openChat(); else closeChat();
}

function getVoterId() {
  let id = localStorage.getItem('campussafe_voter_id');
  if (!id) {
    id = (crypto.randomUUID ? crypto.randomUUID() : `${Date.now()}-${Math.random().toString(16).slice(2)}`);
    localStorage.setItem('campussafe_voter_id', id);
  }
  return id;
}

function getMyVotes() {
  try {
    return JSON.parse(localStorage.getItem('campussafe_my_votes') || '{}');
  } catch {
    return {};
  }
}

function setMyVote(restaurantId, vote) {
  const votes = getMyVotes();
  votes[restaurantId] = vote;
  localStorage.setItem('campussafe_my_votes', JSON.stringify(votes));
}

async function handleRateAction(event) {
  const button = event.target.closest('[data-rate-action]');
  if (!button) return;
  const restaurantId = Number(button.dataset.id);
  const vote = button.dataset.rateAction;
  button.disabled = true;

  try {
    const res = await fetch(`/api/restaurants/${restaurantId}/rate`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ voterId: getVoterId(), vote })
    });
    appState = await res.json();
    setMyVote(restaurantId, vote);
    renderAll();
  } catch (err) {
    alert('Could not submit your rating — check your connection and try again.');
  } finally {
    button.disabled = false;
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
    const badgeClass = getBadgeClass(restaurant);
    const stampLabel = badgeClass === 'unrated' ? 'NEW' : restaurant.score;
    const myVote = getMyVotes()[restaurant.id];
    return `
      <article class="placard">
        <div class="placard-top">
          <div>
            <h4>${restaurant.name}</h4>
            <p>${restaurant.campus}</p>
          </div>
          <span class="stamp ${badgeClass}">${stampLabel}</span>
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
        <div class="rate-row">
          <button class="rate-btn up ${myVote === 'up' ? 'active' : ''}" data-rate-action="up" data-id="${restaurant.id}" type="button" aria-label="Thumbs up">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none"><path d="M12 5v14M5 12l7-7 7 7" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>
            ${restaurant.upvotes || 0}
          </button>
          <button class="rate-btn down ${myVote === 'down' ? 'active' : ''}" data-rate-action="down" data-id="${restaurant.id}" type="button" aria-label="Thumbs down">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none"><path d="M12 19V5M5 12l7 7 7-7" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>
            ${restaurant.downvotes || 0}
          </button>
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

  animateLedgerValue(document.getElementById('activeReports'), appState.reports.filter((report) => report.status !== 'dismissed').length);
  animateLedgerValue(document.getElementById('riskSpots'), appState.restaurants.filter((restaurant) => restaurant.reports > 0 && restaurant.score >= 55).length);
  animateLedgerValue(document.getElementById('responseTime'), responseTime, 'm');

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
  const ranked = appState.restaurants.filter((r) => r.reports > 0).sort((a, b) => b.score - a.score).slice(0, 3);
  if (!ranked.length) {
    riskList.innerHTML = '<div class="empty-state">No incidents reported yet.</div>';
  } else {
    riskList.innerHTML = ranked.map((restaurant) => `
      <div class="risk-card">
        <div class="restaurant-top">
          <div>
            <h4>${restaurant.name}</h4>
            <p>${restaurant.campus}</p>
          </div>
          <span class="badge ${getBadgeClass(restaurant)}">${restaurant.score}</span>
        </div>
      </div>
    `).join('');
  }
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
document.getElementById('restaurantList').addEventListener('click', handleRateAction);
document.getElementById('reviewQueue').addEventListener('click', handleReviewAction);
document.getElementById('chatFab').addEventListener('click', toggleChat);
document.getElementById('closeChatBtn').addEventListener('click', closeChat);
document.getElementById('assistantForm').addEventListener('submit', submitAssistantQuestion);

// Orchestrated entrance: the masthead/hero/console are pure CSS (animate on
// paint), but the panels below the fold get a scroll-triggered reveal so the
// page doesn't just dump every section on-screen at once.
if (!prefersReducedMotion && 'IntersectionObserver' in window) {
  const revealTargets = document.querySelectorAll('.panel');
  const observer = new IntersectionObserver((entries) => {
    entries.forEach((entry) => {
      if (entry.isIntersecting) {
        entry.target.classList.add('in-view');
        observer.unobserve(entry.target);
      }
    });
  }, { threshold: 0.15 });
  revealTargets.forEach((el) => {
    el.classList.add('reveal');
    observer.observe(el);
  });
} else {
  document.querySelectorAll('.panel').forEach((el) => el.classList.add('in-view'));
}

requestAnimationFrame(() => document.body.classList.add('loaded'));

refreshState();
