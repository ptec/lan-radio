(() => {
  const $ = id => document.getElementById(id);
  const audio = $('preview'), toggle = $('preview-toggle'), seek = $('preview-seek');
  const dock = document.querySelector('.debug-dock');
  const measureDock = () => document.documentElement.style.setProperty('--debug-player-height', dock.getBoundingClientRect().height + 'px');
  new ResizeObserver(measureDock).observe(dock);
  measureDock();
  const format = seconds => { const n = Number.isFinite(seconds) ? Math.max(0, Math.floor(seconds)) : 0; return Math.floor(n/60)+':'+String(n%60).padStart(2,'0'); };
  function update() {
    toggle.disabled = !audio.getAttribute('src');
    toggle.textContent = audio.paused ? 'Play' : 'Pause';
    toggle.setAttribute('data-playing', String(!audio.paused));
    const duration = Number.isFinite(audio.duration) ? audio.duration : 0;
    seek.disabled = !duration; seek.max = duration; seek.value = audio.currentTime || 0;
    $('preview-time').textContent = format(audio.currentTime);
    $('preview-duration').textContent = format(duration);
  }
  toggle.onclick = () => { if (audio.paused) audio.play().catch(() => { $('message').textContent = 'Preview could not start. Select Preview on the song to retry.'; }); else audio.pause(); };
  seek.oninput = () => { if (!seek.disabled) audio.currentTime = Number(seek.value); update(); };
  $('preview-volume').oninput = () => { audio.volume = Number($('preview-volume').value); audio.muted = false; };
  $('preview-mute').onclick = () => { if (audio.muted || audio.volume === 0) { audio.muted = false; if (!audio.volume) audio.volume = 0.5; } else audio.muted = true; };
  audio.addEventListener('volumechange', () => {
    const muted = audio.muted || audio.volume === 0;
    $('preview-mute').textContent = muted ? 'Unmute' : 'Mute';
    $('preview-mute').setAttribute('aria-pressed', String(muted));
    $('preview-volume').value = audio.volume;
  });
  for (const event of ['loadstart','loadedmetadata','durationchange','timeupdate','play','pause','ended','emptied','error']) audio.addEventListener(event, update);
  update();
})();
