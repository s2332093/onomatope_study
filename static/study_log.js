(() => {
  const prefix = document.body.dataset.studyPrefix;
  if (!prefix) return;
  const pageId = crypto.randomUUID();
  const started = performance.now();
  let queue = [], sequence = 0, clicks = 0, activeMs = 0;
  let activeSince = document.hidden ? null : performance.now();
  const active = () => activeMs + (activeSince === null ? 0 : performance.now() - activeSince);
  function flush() {
    if (!queue.length) return;
    const batch = queue.slice(0, 100);
    const body = JSON.stringify({events: batch});
    if (navigator.sendBeacon(prefix + '/api/events', new Blob([body], {type:'application/json'}))) {
      queue.splice(0, batch.length);
    }
  }
  window.studyEvent = (type, detail = {}) => {
    queue.push({event_id: pageId + ':' + sequence++, page_id: pageId,
      client_time: new Date().toISOString(), elapsed_ms: Math.round(performance.now() - started),
      event_type: type, detail: {...detail, path: location.pathname}});
    if (queue.length >= 20) flush();
  };
  document.addEventListener('click', e => {
    clicks++;
    const el = e.target.closest('a,button,input,summary,[data-key]');
    window.studyEvent('click', {target: el ? (el.id || el.name || el.getAttribute('href') || el.tagName) : e.target.tagName,
      click_count: clicks});
  }, true);
  document.addEventListener('change', e => {
    if (e.target.matches('input[type=radio],input[type=checkbox],select'))
      window.studyEvent('answer_change', {name: e.target.name, value: e.target.value});
  });
  document.addEventListener('submit', e => {
    if (e.defaultPrevented) return;
    window.studyEvent('submit', {form: e.target.id || e.target.getAttribute('action'), active_ms: Math.round(active()), click_count: clicks});
    flush();
  });
  document.addEventListener('visibilitychange', () => {
    if (document.hidden) {
      if (activeSince !== null) activeMs += performance.now() - activeSince;
      activeSince = null;
      window.studyEvent('page_hidden', {active_ms: Math.round(active()), click_count: clicks});
      flush();
    } else {
      activeSince = performance.now();
      window.studyEvent('page_visible');
    }
  });
  addEventListener('pagehide', () => {
    window.studyEvent('page_leave', {active_ms: Math.round(active()), click_count: clicks}); flush();
  });
  window.studyEvent('page_view');
  setInterval(() => {
    if (!document.hidden) window.studyEvent('heartbeat', {active_ms: Math.round(active()), click_count: clicks});
    flush();
  }, 10000);
})();
