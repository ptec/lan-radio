(() => {
  const popup = document.createElement('div'); popup.className = 'debug-suggestions'; popup.hidden = true;
  popup.id = 'debug-suggestions'; popup.setAttribute('role', 'listbox'); popup.setAttribute('aria-label', 'iTunes suggestions');
  document.body.append(popup);
  let timer, controller, version = 0, owner, results = [], active = -1, choose;
  function close() {
    clearTimeout(timer); controller?.abort(); version++; popup.hidden = true;
    owner?.setAttribute('aria-expanded', 'false'); owner?.removeAttribute('aria-activedescendant');
    owner = null; results = []; active = -1;
  }
  function attach(inputs, changed) {
    for (const field of [inputs.title, inputs.artist]) {
      field.autocomplete = 'off'; field.setAttribute('role','combobox'); field.setAttribute('aria-autocomplete','list');
      field.setAttribute('aria-controls', popup.id); field.setAttribute('aria-expanded','false');
      const search = () => {
        close(); owner = field;
        if ((inputs.title.value.trim()+inputs.artist.value.trim()).length < 2) return;
        const expected = version;
        timer = setTimeout(async () => {
          controller = new AbortController();
          const rect = field.getBoundingClientRect();
          popup.style.left = Math.max(8, Math.min(rect.left, window.innerWidth-368)) + 'px';
          popup.style.width = Math.min(Math.max(rect.width,360),window.innerWidth-16) + 'px';
          const below = window.innerHeight - rect.bottom;
          popup.style.top = below >= 180 ? rect.bottom+4+'px' : 'auto';
          popup.style.bottom = below >= 180 ? 'auto' : window.innerHeight-rect.top+4+'px';
          popup.style.maxHeight = Math.max(100,Math.min(280,below >=180 ? below-12 : rect.top-12))+'px';
          popup.textContent = 'Searching iTunes…'; popup.hidden = false; field.setAttribute('aria-expanded','true');
          try {
            const params = new URLSearchParams({title:inputs.title.value.trim(),artist:inputs.artist.value.trim()});
            const response = await fetch('/api/song-suggestions?'+params, {signal:controller.signal});
            if (!response.ok) throw Error();
            const body = await response.json(); if (expected !== version) return;
            results = body.songs;
            choose = index => { const song = results[index]; if (!song) return; inputs.title.value = song.title; inputs.artist.value = song.artist; changed(); close(); };
            popup.replaceChildren(...results.map((song,index) => {
              const item = document.createElement('div'); item.id = 'debug-option-'+index; item.setAttribute('role','option'); item.setAttribute('aria-selected','false');
              const title = document.createElement('strong'), artist = document.createElement('span'); title.textContent = song.title; artist.textContent = song.artist;
              item.append(title,artist); item.onmousedown = event => event.preventDefault(); item.onclick = () => choose(index); return item;
            }));
            if (!results.length) popup.textContent = 'No suggestions. You can edit the fields manually.';
          } catch (error) { if (expected === version && error.name !== 'AbortError') popup.textContent = 'Suggestions unavailable. Manual edits still work.'; }
        }, 400);
      };
      field.addEventListener('focus', search); field.addEventListener('input', search);
      field.addEventListener('blur', () => { if (owner === field) close(); });
      field.addEventListener('keydown', event => {
        if (owner !== field || popup.hidden) return;
        if (event.key === 'Escape') { event.preventDefault(); close(); }
        else if (results.length && ['ArrowDown','ArrowUp'].includes(event.key)) {
          event.preventDefault(); active = (active + (event.key === 'ArrowDown' ? 1 : active < 0 ? 0 : -1) + results.length) % results.length;
          [...popup.children].forEach((item,index) => item.setAttribute('aria-selected',String(index === active)));
          field.setAttribute('aria-activedescendant',popup.children[active].id); popup.children[active].scrollIntoView({block:'nearest'});
        } else if (event.key === 'Enter' && active >= 0) { event.preventDefault(); choose(active); }
      });
    }
  }
  window.addEventListener('resize', close);
  document.addEventListener('scroll', event => { if (!popup.contains(event.target)) close(); }, true);
  window.debugSuggestions = {attach,close};
})();
