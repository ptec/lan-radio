(() => {
  const form = document.querySelector('#song');
  const picker = document.querySelector('#song-picker');
  const panel = document.querySelector('#request-panel');
  const list = document.querySelector('#song-suggestions');
  const status = document.querySelector('#suggestion-status');
  const fields = ['title', 'artist'].map(name => form.querySelector(`[name="${name}"]`));
  let timer, controller, version = 0, results = [], active = -1;

  function close() {
    clearTimeout(timer); controller?.abort(); version++;
    list.hidden = true; results = []; active = -1;
    status.textContent = '';
    for (const field of fields) {
      field.setAttribute('aria-expanded', 'false');
      field.removeAttribute('aria-activedescendant');
    }
  }
  function choose(index) {
    const song = results[index];
    if (!song) return;
    fields[0].value = song.title; fields[1].value = song.artist;
    close();
    status.textContent = `Selected ${song.title} by ${song.artist}.`;
  }
  function highlight(field) {
    [...list.children].forEach((option, index) => option.setAttribute('aria-selected', String(index === active)));
    for (const input of fields) input.removeAttribute('aria-activedescendant');
    if (active >= 0) {
      field.setAttribute('aria-activedescendant', list.children[active].id);
      list.children[active].scrollIntoView({block: 'nearest'});
    }
  }
  async function search(expected) {
    controller = new AbortController();
    status.textContent = 'Searching iTunes…';
    const params = new URLSearchParams({title: fields[0].value.trim(), artist: fields[1].value.trim()});
    try {
      const response = await fetch('/api/song-suggestions?' + params, {signal: controller.signal});
      if (!response.ok) throw Error('Search unavailable');
      const body = await response.json();
      if (version !== expected || panel.hidden) return;
      results = body.songs; active = -1;
      list.replaceChildren(...results.map((song, index) => {
        const option = document.createElement('li');
        option.id = `song-suggestion-${index}`;
        option.setAttribute('role', 'option'); option.setAttribute('aria-selected', 'false');
        const title = document.createElement('strong'), artist = document.createElement('span');
        title.textContent = song.title; artist.textContent = song.artist;
        option.append(title, artist);
        // Keep keyboard focus in the input while clicking/tapping a result.
        option.addEventListener('mousedown', event => event.preventDefault());
        option.addEventListener('click', () => choose(index));
        return option;
      }));
      list.hidden = !results.length;
      for (const field of fields) field.setAttribute('aria-expanded', String(!!results.length));
      status.textContent = results.length ? `${results.length} iTunes suggestions. Use arrow keys and Enter to select.` : 'No suggestions found. You can enter the song manually.';
    } catch (error) {
      if (version === expected && error.name !== 'AbortError') status.textContent = 'Suggestions unavailable. You can still enter the title and artist manually.';
    }
  }
  for (const field of fields) {
    field.addEventListener('input', () => {
      close();
      if (fields.map(input => input.value.trim()).join('').length < 2) return;
      const expected = version;
      timer = setTimeout(() => search(expected), 500);
    });
    field.addEventListener('focus', () => highlight(field));
    field.addEventListener('keydown', event => {
      if (event.key === 'Escape') { close(); return; }
      if (list.hidden) return;
      if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
        event.preventDefault();
        active = (active + (event.key === 'ArrowDown' ? 1 : active < 0 ? 0 : -1) + results.length) % results.length;
        highlight(field);
      } else if (event.key === 'Enter' && active >= 0) {
        event.preventDefault(); choose(active);
      }
    });
  }
  picker.addEventListener('focusout', event => {
    if (!picker.contains(event.relatedTarget)) close();
  });
  document.addEventListener('pointerdown', event => { if (!picker.contains(event.target)) close(); });
  form.addEventListener('reset', close);
  form.addEventListener('submit', close);
  new MutationObserver(() => { if (panel.hidden) close(); }).observe(panel, {attributes: true, attributeFilter: ['hidden']});
})();
