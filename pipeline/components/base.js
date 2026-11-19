function weNext(section) {
  const steps = Array.from(section.querySelectorAll('.we-step'));
  const panels = Array.from(section.querySelectorAll('.we-panel'));
  const lines = Array.from(section.querySelectorAll('.we-line'));
  const cur = steps.findIndex(s => s.classList.contains('current'));
  if (cur === -1 || cur === steps.length - 1) return;
  const nxt = cur + 1;
  steps[cur].classList.replace('current', 'done');
  if (lines[cur]) lines[cur].classList.add('done');
  steps[nxt].disabled = false;
  steps[nxt].classList.remove('locked');
  steps[nxt].classList.add('current');
  panels[cur].hidden = true;
  panels[nxt].hidden = false;
  section.querySelector('.we-progress').textContent = `Step ${nxt + 1} of ${steps.length}`;
  if (nxt === steps.length - 1) {
    const btn = section.querySelector('.we-next-btn');
    btn.textContent = 'Done ✓';
    btn.disabled = true;
  }
}
function weActivate(btn) {
  if (btn.disabled) return;
  const section = btn.closest('.slide-worked-example');
  const step = parseInt(btn.dataset.step);
  section.querySelectorAll('.we-step').forEach(b => b.classList.toggle('current', b === btn));
  section.querySelectorAll('.we-panel').forEach((p, i) => p.hidden = (i !== step));
  section.querySelector('.we-progress').textContent =
    `Step ${step + 1} of ${section.querySelectorAll('.we-step').length}`;
}
function checkAnswer(event, form) {
  event.preventDefault();
  const inputs = Array.from(form.querySelectorAll('input'));
  const selected = inputs.filter(i => i.checked);
  const allCorrect = inputs.every(i => !i.checked || i.dataset.correct === 'true');
  const allRequired = inputs.filter(i => i.dataset.correct === 'true').every(i => i.checked);
  const correct = allCorrect && allRequired && selected.length > 0;
  const fb = form.querySelector('.kc-feedback');
  const detail = selected
    .map(i => (i.dataset.feedback || '').trim())
    .filter(Boolean)
    .join('\n\n');
  fb.hidden = false;
  fb.classList.toggle('is-correct', correct);
  fb.classList.toggle('is-incorrect', !correct);
  fb.querySelector('.kc-feedback-outcome').textContent = correct ? 'Correct' : 'Not quite';
  form.querySelector('.kc-feedback-detail').textContent = detail;
  form.querySelector('.submit-btn').disabled = true;
  inputs.forEach(i => i.disabled = true);
  fb.focus();
}

function activateTab(button) {
  const section = button.closest('.slide-tabs');
  section.querySelectorAll('[role="tab"]').forEach(tab => {
    const active = tab === button;
    tab.setAttribute('aria-selected', active ? 'true' : 'false');
    tab.tabIndex = active ? 0 : -1;
    section.querySelector('#' + tab.getAttribute('aria-controls')).hidden = !active;
  });
}

function tabKey(event, button) {
  if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
  event.preventDefault();
  const tabs = Array.from(button.closest('[role="tablist"]').querySelectorAll('[role="tab"]'));
  let index = tabs.indexOf(button);
  if (event.key === 'Home') index = 0;
  else if (event.key === 'End') index = tabs.length - 1;
  else index = (index + (event.key === 'ArrowRight' ? 1 : -1) + tabs.length) % tabs.length;
  activateTab(tabs[index]);
  tabs[index].focus();
}

function toggleCaptions(button) {
  const frame = button.closest('.video-frame');
  const video = frame ? frame.querySelector('video') : null;
  const tracks = video && video.textTracks ? Array.from(video.textTracks) : [];
  if (!tracks.length) return;

  const turningOn = button.getAttribute('aria-pressed') !== 'true';
  tracks.forEach(track => { track.mode = turningOn ? 'showing' : 'disabled'; });
  button.setAttribute('aria-pressed', turningOn ? 'true' : 'false');
  button.setAttribute('aria-label', turningOn ? 'Turn captions off' : 'Turn captions on');
}
