let artistList = [];
let allConcerts = [];
let favorites = JSON.parse(localStorage.getItem('concert_favorites') || '[]');
let currentPage = 'home';

// ─── INIT ───

(function init() {
  const params = new URLSearchParams(window.location.search);
  const token = params.get('token');
  if (token) {
    autoSearchFromDeezer(token);
    window.history.replaceState({}, '', '/');
  }

  // Sidebar navigation
  document.querySelectorAll('#nav-links .nav-link').forEach(link => {
    link.addEventListener('click', (e) => {
      e.preventDefault();
      navigateTo(link.dataset.page);
    });
  });

  // Header search
  document.getElementById('header-search').addEventListener('keydown', (e) => {
    if (e.key === 'Enter') {
      const q = e.target.value.trim();
      if (q) {
        addArtistDirect(q);
        navigateTo('artists');
        e.target.value = '';
      }
    }
  });

  navigateTo('home');
})();

// ─── NAVIGATION ───

function navigateTo(page) {
  currentPage = page;
  document.querySelectorAll('.page').forEach(p => p.classList.add('hidden'));
  const target = document.getElementById(`page-${page}`);
  if (target) target.classList.remove('hidden');

  document.querySelectorAll('#nav-links .nav-link').forEach(link => {
    link.classList.toggle('active', link.dataset.page === page);
  });

  if (page === 'favorites') renderFavorites();
}

// ─── DEEZER AUTO-SEARCH ───

async function autoSearchFromDeezer(token) {
  try {
    const res = await fetch(`/api/my-artists?token=${encodeURIComponent(token)}`);
    const data = await res.json();
    if (data.artists && data.artists.length > 0) {
      artistList = data.artists.map(a => a.name);
      renderTags();
      updateSearchButton();
      navigateTo('artists');
      showToast(`${artistList.length} artistes import\u00e9s depuis Deezer`);
      await searchAllConcerts();
    } else {
      showToast('Aucun artiste trouvé. Connecte au moins une playlist.');
      navigateTo('artists');
    }
  } catch (err) {
    console.error('Auto search error:', err);
    navigateTo('artists');
  }
}

// ─── ARTIST MANAGEMENT ───

function addArtist() {
  const input = document.getElementById('artist-input');
  const name = input.value.trim();
  if (!name) return;
  if (artistList.some(a => a.toLowerCase() === name.toLowerCase())) {
    showToast('Cet artiste est déjà dans la liste');
    input.value = '';
    return;
  }
  artistList.push(name);
  input.value = '';
  renderTags();
  updateSearchButton();
  input.focus();
}

function addArtistDirect(name) {
  if (artistList.some(a => a.toLowerCase() === name.toLowerCase())) {
    showToast('Déjà ajouté');
    return;
  }
  artistList.push(name);
  renderTags();
  updateSearchButton();
  navigateTo('artists');
  showToast(`${name} ajouté`);
}

function removeArtist(index) {
  artistList.splice(index, 1);
  renderTags();
  updateSearchButton();
}

function clearAllArtists() {
  artistList = [];
  renderTags();
  updateSearchButton();
  showToast('Tous les artistes supprimés');
}

function renderTags() {
  const container = document.getElementById('artist-tags');
  if (!container) return;
  container.innerHTML = artistList.map((a, i) =>
    `<span class="inline-flex items-center gap-2 px-3 py-1.5 rounded-full text-sm font-medium" style="background:rgba(255,84,71,0.12);border:1px solid rgba(255,84,71,0.3);color:#e7e0e6;">
      ${a}
      <button onclick="removeArtist(${i})" style="background:none;border:none;color:#ab8984;cursor:pointer;font-size:13px;line-height:1;">✕</button>
    </span>`
  ).join('');
  document.getElementById('artist-count').textContent =
    artistList.length > 0 ? `${artistList.length} artiste${artistList.length > 1 ? 's' : ''} dans la liste` : '';
}

function updateSearchButton() {
  const btn = document.getElementById('btn-search-main');
  if (btn) btn.style.opacity = artistList.length === 0 ? '0.5' : '1';
}

// ─── CONCERT SEARCH ───

async function searchAllConcerts() {
  if (artistList.length === 0) {
    showToast('Ajoute au moins un artiste');
    return;
  }

  navigateTo('concerts');

  const loading = document.getElementById('loading-state');
  const results = document.getElementById('concerts-results');
  const empty = document.getElementById('concerts-empty');
  const noConcerts = document.getElementById('no-concerts');

  loading.classList.remove('hidden');
  results.classList.add('hidden');
  empty.classList.add('hidden');
  noConcerts.classList.add('hidden');

  document.getElementById('artist-summary').textContent = `${artistList.length} artiste${artistList.length > 1 ? 's' : ''} en cours de recherche...`;

  allConcerts = [];
  const total = artistList.length;

  for (let i = 0; i < total; i++) {
    const artist = artistList[i];
    const progress = document.getElementById('progress-fill');
    progress.style.width = `${((i + 1) / total) * 100}%`;
    document.getElementById('loading-text').textContent = `Recherche : ${artist} (${i + 1}/${total})...`;

    try {
      const res = await fetch(`/api/concerts/${encodeURIComponent(artist)}`);
      const data = await res.json();
      if (data.concerts && data.concerts.length > 0) {
        allConcerts.push(...data.concerts);
      }
    } catch (err) {
      console.error(`Error searching ${artist}:`, err);
    }
  }

  document.getElementById('progress-fill').style.width = '100%';
  document.getElementById('loading-text').textContent = 'Terminé !';

  setTimeout(() => {
    loading.classList.add('hidden');
    results.classList.remove('hidden');

    document.getElementById('artist-summary').textContent =
      allConcerts.length > 0
        ? `${allConcerts.length} concert${allConcerts.length > 1 ? 's' : ''} trouvé${allConcerts.length > 1 ? 's' : ''}`
        : '';

    renderConcerts(allConcerts);
  }, 400);
}

function renderConcerts(concerts) {
  const container = document.getElementById('concerts-container');
  const noConcerts = document.getElementById('no-concerts');
  container.innerHTML = '';

  if (concerts.length === 0) {
    noConcerts.classList.remove('hidden');
    return;
  }
  noConcerts.classList.add('hidden');

  // Group by artist
  const grouped = {};
  for (const concert of concerts) {
    if (!grouped[concert.artist]) grouped[concert.artist] = [];
    grouped[concert.artist].push(concert);
  }

  for (const [artist, artistConcerts] of Object.entries(grouped)) {
    // Artist header
    const header = document.createElement('div');
    header.className = 'flex items-center justify-between mb-space-sm mt-space-lg first:mt-0 pb-space-xs border-b border-surface-container-high';
    header.innerHTML = `
      <div class="flex items-center gap-space-sm">
        <h4 class="font-headline-sm text-headline-sm text-on-surface">${artist}</h4>
        <span class="px-2 py-0.5 rounded-full text-xs font-bold" style="background:rgba(255,84,71,0.12);color:#ff5447;">${artistConcerts.length} concert${artistConcerts.length > 1 ? 's' : ''}</span>
      </div>
    `;
    container.appendChild(header);

    for (const c of artistConcerts) {
      const card = createConcertCard(c);
      container.appendChild(card);
    }
  }
}

function createConcertCard(c) {
  const date = new Date(c.date);
  const day = date.getDate();
  const month = date.toLocaleDateString('fr-FR', { month: 'short' });
  const year = date.getFullYear();
  const fullDate = date.toLocaleDateString('fr-FR', {
    weekday: 'long', day: 'numeric', month: 'long', year: 'numeric'
  });
  const hourStr = c.date.includes('T')
    ? date.toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' })
    : '';
  const location = [c.city, c.country].filter(Boolean).join(', ');
  const capacity = c.capacity ? `<span class="px-2 py-0.5 rounded-md text-xs" style="background:rgba(255,84,71,0.1);color:#ff5447;">~${Number(c.capacity).toLocaleString('fr-FR')} places</span>` : '';
  const source = c.source ? `<span class="px-2 py-0.5 rounded-md text-xs text-on-surface-variant" style="background:rgba(255,255,255,0.05);">${c.source}</span>` : '';

  const favKey = `${c.artist}-${c.date}-${c.venue}`;
  const isFav = favorites.some(f => f.key === favKey);

  const card = document.createElement('div');
  card.className = 'concert-card flex items-center gap-space-md p-space-md fade-in';
  card.innerHTML = `
    <div class="text-center shrink-0 px-3 py-2 rounded-lg" style="background:rgba(255,84,71,0.08);border:1px solid rgba(255,84,71,0.2);">
      <div class="text-2xl font-bold leading-none text-on-surface">${day}</div>
      <div class="text-xs uppercase tracking-wider mt-0.5" style="color:#ff5447;">${month}</div>
      <div class="text-xs text-on-surface-variant">${year}</div>
    </div>
    <div class="flex-1 min-w-0">
      <div class="text-base font-semibold text-on-surface truncate">${c.venue}</div>
      <div class="text-sm text-on-surface-variant mb-1.5">${location}</div>
      <div class="flex flex-wrap gap-1.5">
        <span class="px-2 py-0.5 rounded-md text-xs text-on-surface-variant" style="background:rgba(255,255,255,0.05);">${fullDate}</span>
        ${hourStr ? `<span class="px-2 py-0.5 rounded-md text-xs text-on-surface-variant" style="background:rgba(255,255,255,0.05);">${hourStr}</span>` : ''}
        ${capacity}
        ${source}
      </div>
    </div>
    <div class="flex items-center gap-space-xs shrink-0">
      <button class="fav-btn w-9 h-9 rounded-full flex items-center justify-center text-on-surface-variant hover:text-primary-container transition-all ${isFav ? 'active' : ''}" onclick="toggleFavorite(this, '${favKey}', ${JSON.stringify(c).replace(/"/g, '&quot;')})" title="Ajouter aux favoris">
        <span class="material-symbols-outlined text-[20px]" style="${isFav ? 'font-variation-settings: \'FILL\' 1; color: #ff5447;' : ''}">favorite</span>
      </button>
      ${c.ticketUrl ? `<a href="${c.ticketUrl}" target="_blank" class="px-4 py-2 rounded-lg text-sm font-semibold transition-opacity hover:opacity-85" style="background:#e7e0e6;color:#151317;">Billets</a>` : ''}
    </div>
  `;
  return card;
}

// ─── FAVORITES ───

function toggleFavorite(btn, key, concert) {
  const idx = favorites.findIndex(f => f.key === key);
  if (idx >= 0) {
    favorites.splice(idx, 1);
    btn.classList.remove('active');
    btn.querySelector('.material-symbols-outlined').style.fontVariationSettings = "'FILL' 0";
    btn.querySelector('.material-symbols-outlined').style.color = '';
    showToast('Retiré des favoris');
  } else {
    favorites.push({ key, ...concert });
    btn.classList.add('active');
    btn.querySelector('.material-symbols-outlined').style.fontVariationSettings = "'FILL' 1";
    btn.querySelector('.material-symbols-outlined').style.color = '#ff5447';
    showToast('Ajouté aux favoris');
  }
  localStorage.setItem('concert_favorites', JSON.stringify(favorites));
}

function renderFavorites() {
  const container = document.getElementById('favorites-container');
  const empty = document.getElementById('favorites-empty');
  container.innerHTML = '';

  if (favorites.length === 0) {
    empty.classList.remove('hidden');
    return;
  }
  empty.classList.add('hidden');

  for (const fav of favorites) {
    const card = createConcertCard(fav);
    container.appendChild(card);
  }
}

// ─── FILTER ───

function filterConcerts(query) {
  if (!query.trim()) {
    renderConcerts(allConcerts);
    return;
  }
  const q = query.toLowerCase();
  const filtered = allConcerts.filter(c =>
    c.artist.toLowerCase().includes(q) ||
    c.venue.toLowerCase().includes(q) ||
    c.city.toLowerCase().includes(q) ||
    c.country.toLowerCase().includes(q)
  );
  renderConcerts(filtered);
}

// ─── NOTIFICATIONS ───

function requestNotifPermission() {
  if ('Notification' in window) {
    Notification.requestPermission().then(perm => {
      if (perm === 'granted') {
        showToast('Notifications activées');
        document.getElementById('btn-enable-notif').textContent = 'Notifications activées ✓';
      } else {
        showToast('Notifications refusées');
      }
    });
  } else {
    showToast('Notifications non supportées par ce navigateur');
  }
}

// ─── TOAST ───

function showToast(message) {
  const container = document.getElementById('toast-container');
  const toast = document.createElement('div');
  toast.className = 'toast-item';
  toast.innerHTML = `${message}<button class="toast-close" onclick="this.parentElement.remove()">✕</button>`;
  container.appendChild(toast);
  setTimeout(() => toast.remove(), 3000);
}
