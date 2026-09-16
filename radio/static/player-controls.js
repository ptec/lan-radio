(() => {
  const audio = document.querySelector('#audio');
  const volume = document.querySelector('#volume');
  const mute = document.querySelector('#mute');
  function renderVolume() {
    const silent = audio.muted || audio.volume === 0;
    volume.value = audio.volume;
    mute.textContent = silent ? 'Unmute' : 'Mute';
    mute.setAttribute('aria-label', silent ? 'Unmute audio' : 'Mute audio');
    mute.setAttribute('aria-pressed', String(silent));
  }
  volume.addEventListener('input', () => { audio.volume = Number(volume.value); audio.muted = false; renderVolume(); });
  mute.addEventListener('click', () => {
    if (audio.muted || audio.volume === 0) { audio.muted = false; if (!audio.volume) audio.volume = 0.5; }
    else audio.muted = true;
    renderVolume();
  });
  audio.addEventListener('volumechange', renderVolume);
  renderVolume();

  const drawer = document.querySelector('#station-drawer');
  const sidebar = document.querySelector('.sidebar');
  const shell = document.querySelector('.shell');
  const open = document.querySelector('#stations-open');
  const close = document.querySelector('#stations-close');
  const mobile = matchMedia('(max-width: 680px)');
  function layout() {
    if (drawer.open) drawer.close();
    if (mobile.matches) drawer.append(sidebar);
    else shell.prepend(sidebar);
  }
  open.addEventListener('click', () => { drawer.showModal(); close.focus(); });
  close.addEventListener('click', () => drawer.close());
  drawer.addEventListener('click', event => {
    if (event.target !== drawer) return;
    const rect = drawer.getBoundingClientRect();
    if (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) drawer.close();
  });
  document.querySelector('#stations').addEventListener('click', event => {
    if (drawer.open && event.target.closest('.station-card') && !event.target.closest('button:disabled')) drawer.close();
  });
  mobile.addEventListener('change', layout);
  layout();
})();
