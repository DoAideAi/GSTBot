/* Kept identical in GST frontend/public/ads.js. Only explicit, completed events
   are conversions. No tag request or advertising cookie before consent. */
(() => {
  const TAG = 'AW-18552515324';
  const LABELS = {
    demo_request_submitted: 'y6wTCMa3u7EdEPzVw45F',
    signup_complete: 'mnU7CMm3u7EdEPzVw45F',
    pilot_started: 'KLyQCMy3u7EdEPzVw45F',
    subscribe_success: 'i3C2CM-3u7EdEPzVw45F',
    product_used: 'ldqACNK3u7EdEPzVw45F',
  };
  const COOKIE = 'doaide_ad_measurement';
  const QUEUE = 'doaide_pending_conversions';
  const production = ['doaide.com', 'www.doaide.com', 'gst.doaide.com'].includes(location.hostname);
  let loaded = false;
  const inFlight = new Set();
  let consent = document.cookie.split('; ').find(v => v.startsWith(COOKIE + '='))?.split('=')[1];
  let pending = [];
  try { pending = JSON.parse(sessionStorage.getItem(QUEUE) || '[]').filter(e => e.at > Date.now() - 1800000).slice(-20); } catch (_) { /* Storage may be unavailable; the product still works. */ }
  function persist() { try { sessionStorage.setItem(QUEUE, JSON.stringify(pending)); } catch (_) { /* Storage may be unavailable; the product still works. */ } }
  function measurementUrl() {
    const safe = new URL(location.origin + '/');
    const query = new URLSearchParams(location.search);
    // Preserve Google's click attribution without forwarding arbitrary queries.
    for (const key of ['gclid', 'gbraid', 'wbraid']) {
      const value = query.get(key);
      if (/^[A-Za-z0-9_-]{1,200}$/.test(value || '')) safe.searchParams.set(key, value);
    }
    return safe.href;
  }
  function flush() {
    if (!loaded || consent !== 'yes') return;
    pending.slice().forEach(item => {
      if (inFlight.has(item.id) || !LABELS[item.event]) return;
      inFlight.add(item.id);
      // Drop URL queries, fragments and private record paths from ad requests.
      window.gtag('event', 'conversion', {
        send_to: TAG + '/' + LABELS[item.event],
        value: item.value, currency: 'INR', transaction_id: item.id,
        page_location: measurementUrl(), page_title: 'DoAide GST',
        event_callback: () => { pending = pending.filter(e => e.id !== item.id); persist(); },
      });
    });
  }
  function load() {
    if (loaded || consent !== 'yes' || !production || location.pathname.startsWith('/auth/')) return;
    loaded = true;
    window.dataLayer = window.dataLayer || [];
    window.gtag = function () { window.dataLayer.push(arguments); };
    window.gtag('consent', 'default', { ad_storage: 'granted', analytics_storage: 'denied', ad_user_data: 'granted', ad_personalization: 'denied' });
    window.gtag('js', new Date());
    window.gtag('set', { page_location: measurementUrl(), page_title: 'DoAide GST', allow_ad_personalization_signals: false });
    window.gtag('config', TAG, { send_page_view: false, allow_enhanced_conversions: false });
    const tag = document.createElement('script');
    tag.async = true;
    tag.src = 'https://www.googletagmanager.com/gtag/js?id=' + TAG;
    document.head.append(tag);
    flush();
  }
  function choose(value) {
    consent = value;
    document.cookie = COOKIE + '=' + value + '; Path=/; Max-Age=15552000; SameSite=Lax' + (production ? '; Domain=doaide.com; Secure' : '');
    document.getElementById('doaide-measurement-panel')?.remove();
    if (value === 'yes') {
      if (loaded) window.gtag('consent', 'update', { ad_storage: 'granted', ad_user_data: 'granted' });
      load(); flush();
    }
    else {
      pending = []; persist();
      if (loaded) window.gtag('consent', 'update', { ad_storage: 'denied', ad_user_data: 'denied', ad_personalization: 'denied' });
      document.cookie.split('; ').filter(v => /^_gcl_/.test(v)).forEach(v => {
        const name = v.split('=')[0];
        document.cookie = name + '=; Max-Age=0; Path=/';
        document.cookie = name + '=; Max-Age=0; Path=/; Domain=doaide.com; Secure';
      });
    }
  }
  function show() {
    if (document.getElementById('doaide-measurement-panel')) return;
    const panel = document.createElement('section');
    panel.id = 'doaide-measurement-panel';
    panel.setAttribute('aria-label', 'Ad measurement choice');
    panel.style.cssText = 'position:fixed;bottom:48px;left:12px;right:12px;max-width:540px;padding:18px;border:1px solid #94a3b8;border-radius:12px;background:#fff;color:#172033;box-shadow:0 4px 24px #0002;z-index:9999;font:14px/1.5 system-ui';
    panel.innerHTML = '<strong>Optional ad measurement</strong><p>Allow Google Ads cookies to help us see which ads bring signups and customers? Your choice applies to both DoAide sites. The service works either way.</p><p><a href="https://doaide.com/privacy/">Privacy and cookies</a></p>';
    [['Allow ad measurement', 'yes'], ['Decline', 'no']].forEach(([label, value]) => {
      const button = document.createElement('button');
      button.type = 'button'; button.textContent = label;
      button.style.cssText = 'padding:9px 12px;margin:0 8px 0 0;border:1px solid #64748b;border-radius:6px;background:#fff;color:#172033;font:inherit;cursor:pointer';
      button.addEventListener('click', () => choose(value)); panel.append(button);
    });
    document.body.append(panel);
  }
  window.doaideAds = {
    conversion(event, details = {}) {
      if (consent !== 'yes' || !LABELS[event] || !production) return;
      // Only the payment's value and opaque reference may be forwarded.
      const value = event === 'subscribe_success' && Number.isFinite(details.value) && details.value >= 0 ? details.value : 0;
      const id = /^[A-Za-z0-9_-]{1,100}$/.test(details.transaction_id || '') ? details.transaction_id : crypto.randomUUID();
      pending.push({ event, value, id, at: Date.now() }); pending = pending.slice(-20); persist();
      load(); flush();
    },
  };
  function ready() {
    const button = document.createElement('button');
    button.type = 'button'; button.textContent = 'Ad measurement';
    button.style.cssText = 'position:fixed;bottom:8px;left:8px;z-index:9998;padding:5px 9px;border:1px solid #94a3b8;border-radius:6px;background:#fff;color:#172033;font:12px system-ui;cursor:pointer';
    button.addEventListener('click', show); document.body.append(button);
    if (!consent) show();
    load();
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', ready, { once: true }); else ready();
})();
