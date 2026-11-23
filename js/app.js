/* Machinist Hands — small script used on every page (js/app.js, as in HTML5 Boilerplate). */
(function () {
  'use strict';

  // Clickjacking guard: GitHub Pages cannot send X-Frame-Options, so leave any frame another site puts us in.
  if (window.top !== window.self) {
    try { window.top.location.replace(window.location.href); } catch (e) { document.documentElement.hidden = true; }
  }

  // Google AdSense: same ad units as the Mechanical Workshop site. Empty slot = that ad space is removed.
  // Student site: ask Google for its under-18 ("teen") treatment (0 = none, 1 = child, 2 = teen).
  const ADS = { client: 'ca-pub-7727895345119500', ageTreatment: '2',
    slots: { article: '1281073793', end: '6888623694', home: '7710750771' } };
  document.querySelectorAll('.ad[data-ad]').forEach((box) => {
    const slot = ADS.slots[box.dataset.ad];
    if (!slot) { box.remove(); return; }
    const ins = document.createElement('ins');
    ins.className = 'adsbygoogle';
    ins.style.display = 'block';
    Object.entries({ 'data-ad-client': ADS.client, 'data-ad-slot': slot, 'data-ad-format': 'auto',
      'data-full-width-responsive': 'true', 'data-tag-for-age-treatment': ADS.ageTreatment })
      .forEach(([k, v]) => ins.setAttribute(k, v));
    box.appendChild(ins);
    try { (window.adsbygoogle = window.adsbygoogle || []).push({}); } catch { box.remove(); }
    // Ad blocked or no ad: remove the empty space after 8 s
    setTimeout(() => { if (!ins.getAttribute('data-ad-status') && !ins.querySelector('iframe')) box.remove(); }, 8000);
  });

  // Footer year follows the visitor's clock (the page already shows the build year without JavaScript).
  document.getElementById('year-now').textContent = new Date().getFullYear();

  // Year / project pickers on project pages: go to the chosen page
  document.querySelectorAll('.nav-select').forEach((s) => {
    s.addEventListener('change', () => { location.href = s.value; });
  });

  // One Share button: opens the phone's own share menu (WhatsApp, Facebook, Gmail…);
  // on computers without that menu, it copies the link instead.
  document.querySelectorAll('.share-row').forEach((row) => {
    const { url, title } = row.dataset;
    const status = row.parentElement.querySelector('.share-status');
    const say = (m) => { if (status) status.textContent = m; };
    const copy = () => {
      try {
        navigator.clipboard.writeText(url).then(() => say('Link copied. Paste it anywhere to share.'), () => say(url));
      } catch (err) { say(url); }
    };
    row.querySelector('.share-btn').addEventListener('click', () => {
      if (!navigator.share) { copy(); return; }
      // If the share menu is blocked (not just closed by the visitor), copy the link instead
      navigator.share({ title, url }).catch((err) => { if (!err || err.name !== 'AbortError') copy(); });
    });
  });

  // ---- Firebase / Firestore (views, likes, dislikes; js/comments.js uses it too) ----
  // Project "worldskills-like-dislike-share". This web API key is public by design;
  // firestore.rules decides what visitors may change.
  const FIREBASE = {
    projectId: 'worldskills-like-dislike-share',
    apiKey: 'AIzaSyBILSaQCgx9XFSYkLhdapt7p1qFu0XQfVk',
    authDomain: 'worldskills-like-dislike-share.firebaseapp.com',
  };
  const DOCS = `projects/${FIREBASE.projectId}/databases/(default)/documents`;
  const API = `https://firestore.googleapis.com/v1/${DOCS}`;
  const post = (action, body, headers) => fetch(`${API}:${action}?key=${FIREBASE.apiKey}`, {
    method: 'POST', headers: { 'Content-Type': 'application/json', ...headers }, body: JSON.stringify(body),
  }).then((r) => { if (!r.ok) throw new Error(r.status); return r.json(); });
  // Add to counters of one page, e.g. bump('index', { views: 1 }) or bump(page, { likes: 1, dislikes: -1 })
  const bump = (id, changes) => post('commit', { writes: [{ transform: {
    document: `${DOCS}/pages/${id}`,
    fieldTransforms: Object.entries(changes).map(([fieldPath, n]) => ({ fieldPath, increment: { integerValue: String(n) } })),
  } }] });
  const count = (doc, k) => Number(doc?.fields?.[k]?.integerValue || 0);
  const store = (s) => ({
    get(k) { try { return s.getItem(k); } catch (e) { return null; } },
    set(k, v) { try { if (v == null) s.removeItem(k); else s.setItem(k, v); } catch (e) {} },
  });
  const local = store(window.localStorage), session = store(window.sessionStorage);
  // One view per page per browser session
  const firstView = (id) => {
    if (session.get(`viewed:${id}`)) return false;
    session.set(`viewed:${id}`, '1');
    return true;
  };
  window.MH = { FIREBASE, DOCS, API, post };

  // Home page: visits of the home page, and views of each project on its card (one request for all)
  const homeViews = document.querySelector('.site-views');
  if (homeViews) {
    const cards = [...document.querySelectorAll('.card-views')];
    const fresh = firstView('index');
    const fill = (el, n) => {
      if (!(n > 0)) return;
      el.querySelector('b').textContent = n.toLocaleString();
      const label = el.querySelector('span');
      if (label) label.textContent = n === 1 ? 'visit' : 'visits';
      el.title = `${n.toLocaleString()} ${n === 1 ? 'view' : 'views'}`;
      el.hidden = false;
    };
    post('batchGet', { documents: ['index', ...cards.map((c) => c.dataset.page)].map((id) => `${DOCS}/pages/${id}`) })
      .then((rows) => {
        const docs = {};
        rows.forEach((r) => { if (r.found) docs[r.found.name.split('/').pop()] = r.found; });
        fill(homeViews, count(docs.index, 'views') + (fresh ? 1 : 0));
        cards.forEach((c) => fill(c, count(docs[c.dataset.page], 'views')));
      })
      .catch(() => {});
    if (fresh) bump('index', { views: 1 }).catch(() => {});
  }

  // Project page: views, and like / dislike (tap again to take back, tap the other thumb to switch)
  const engage = document.querySelector('.engage');
  if (engage) {
    const page = engage.dataset.page;
    const status = engage.querySelector('.share-status');
    const views = engage.querySelector('.eng-views');
    const btns = engage.querySelectorAll('[data-vote]');
    const counts = { views: 0, likes: 0, dislikes: 0 };
    // Numbers appear only once there is something to count: no "0", no "–"
    const show = () => {
      engage.querySelectorAll('[data-count]').forEach((b) => {
        const n = counts[b.dataset.count];
        b.textContent = n > 0 ? n.toLocaleString() : '';
      });
      views.hidden = !(counts.views > 0);
      views.querySelector('.eng-label').textContent = counts.views === 1 ? 'view' : 'views';
    };
    // v2: votes saved before the counters went live are ignored
    const KEY = `vote-v2:${page}`;
    let vote = local.get(KEY);
    let busy = false;
    const mark = () => btns.forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.vote === vote)));
    mark();

    fetch(`${API}/pages/${page}?key=${FIREBASE.apiKey}`)
      .then((r) => (r.ok ? r.json() : {}))
      .then((d) => {
        Object.keys(counts).forEach((k) => { counts[k] = count(d, k); });
        if (firstView(page)) { counts.views += 1; bump(page, { views: 1 }).catch(() => {}); }
        show();
      })
      .catch(() => {});

    btns.forEach((b) => b.addEventListener('click', () => {
      if (busy) return;
      const v = b.dataset.vote, before = vote, changes = {};
      if (before === v) { changes[v] = -1; vote = null; }                    // take the vote back
      else { changes[v] = 1; if (before) changes[before] = -1; vote = v; }   // new vote, or switch
      const apply = (sign) => Object.entries(changes).forEach(([k, n]) => { counts[k] = Math.max(0, counts[k] + sign * n); });
      apply(1); mark(); show(); local.set(KEY, vote);
      status.textContent = '';
      busy = true;
      bump(page, changes)
        .catch(() => {
          apply(-1); vote = before; mark(); show(); local.set(KEY, before);
          status.textContent = 'Could not save your vote. Please try again.';
        })
        .finally(() => { busy = false; });
    }));
  }
})();
