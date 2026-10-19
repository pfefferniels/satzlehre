/* Score excerpts that play a recording from the note clicked.

   A slide <section data-recording="scores/….json"> holds <img class="aligned" src="img/….svg">, an excerpt that
   scores/render.py renders with timing (data-on, data-off: quarter notes from the start of the piece). The image is
   replaced by the inline SVG. One Spotify embed plays the recording; the JSON maps score time to seconds through
   its anchors.

   Click a note: play from there; the notes sounding light up, and the next excerpt follows on its own.
   Shift-click a note the moment it sounds: correct the timing from there on (remembered in this browser).
   K: play / pause.

   Needs http(s): the SVGs and the JSON are fetched, and Spotify plays full tracks only to a signed-in browser. */
(() => {
  const PREROLL = 0.4; // seconds of music before the note clicked
  const REACTION = 0.25; // a shift-click comes this late after the note sounds
  const SPOTIFY_API = "https://open.spotify.com/embed/iframe-api/v1";

  const sections = [...document.querySelectorAll(".reveal .slides section[data-recording]")];
  if (!sections.length || /receiver/i.test(location.search)) return;

  const recordings = {}; // JSON url → promise of the recording
  const recording = (url) =>
    (recordings[url] ??= fetch(url).then((response) => response.json()).then((data) => ({ url, ...data })));

  // Piecewise linear through sorted (x, y) pairs, continued with the outer slopes.
  function interpolate(points, x, from = 0, to = 1) {
    let i = 1;
    while (i < points.length - 1 && points[i][from] < x) i++;
    const [a, b] = [points[i - 1], points[i]];
    return a[to] + ((x - a[from]) * (b[to] - a[to])) / (b[from] - a[from]);
  }

  // Corrections ---------------------------------------------------------------------------------------------------

  const storageKey = (rec) => `aligned-score:${rec.url}`;

  function loadPins(rec) {
    try {
      return JSON.parse(localStorage.getItem(storageKey(rec))) ?? [];
    } catch {
      return [];
    }
  }

  function savePins(rec, pins) {
    try {
      if (pins.length) localStorage.setItem(storageKey(rec), JSON.stringify(pins));
      else localStorage.removeItem(storageKey(rec));
    } catch {}
  }

  /* The anchors with the pins (score time, seconds) worked in. A pin shifts everything after it, and the stretch back
     to the previous pin or measured block is stretched to match. A pin inside a block (bars measured among
     themselves) moves the whole block. */
  function corrected(rec, pins) {
    let anchors = rec.anchors.map((anchor) => [...anchor]);
    let fixed = -Infinity;
    for (const [q, t] of [...pins].sort((a, b) => a[0] - b[0])) {
      const delta = t - interpolate(anchors, q);
      const block = rec.blocks.find(([first, last]) => first <= q && q <= last);
      const start = block ? block[0] : q;
      const from = Math.max(fixed, ...rec.blocks.filter(([, last]) => last < start).map(([, last]) => last));
      const moved = anchors.map(([aq, at]) => {
        if (aq >= start) return [aq, at + delta];
        if (aq > from && from > -Infinity) return [aq, at + (delta * (aq - from)) / (start - from)];
        return [aq, at];
      });
      if (!block) moved.push([q, t]);
      moved.sort((a, b) => a[0] - b[0]);
      if (moved.some((anchor, i) => i && anchor[1] <= moved[i - 1][1])) continue; // a pin out of order
      anchors = moved;
      fixed = block ? block[1] : q;
    }
    return anchors;
  }

  // Player --------------------------------------------------------------------------------------------------------

  const player = document.createElement("div");
  player.className = "recording-player";
  player.innerHTML = `<div class="recording-embed"><div></div></div>
    <p class="recording-status"><span class="message"></span><button type="button" hidden></button></p>`;
  document.querySelector(".reveal .slides").append(player);
  const message = player.querySelector(".message");
  const reset = player.querySelector("button");

  let controller = null; // Spotify's EmbedController, once ready
  let loaded = null; // the recording in the embed
  let anchors = null; // its anchors, corrected
  let state = { position: 0, isPaused: true, isBuffering: false, duration: 0, at: 0 };
  let started = false;
  let pendingSeek = null;
  let messageTimer = null;
  let warned = false;

  function say(text, lasting = false) {
    message.textContent = text;
    clearTimeout(messageTimer);
    if (!lasting) messageTimer = setTimeout(() => (message.textContent = ""), 3500);
  }

  function showPins() {
    const n = loaded ? loadPins(loaded).length : 0;
    reset.hidden = !n;
    reset.textContent = n === 1 ? "1 Korrektur löschen" : `${n} Korrekturen löschen`;
  }

  const seconds = (q) => interpolate(anchors, q);
  const scoreTime = (t) => interpolate(anchors, t, 1, 0);
  const playing = () => started && !state.isPaused && !state.isBuffering;
  const now = () => state.position / 1000 + (playing() ? (performance.now() - state.at) / 1000 : 0);

  function use(rec) {
    if (loaded === rec) return;
    loaded = rec;
    anchors = corrected(rec, loadPins(rec));
    started = false;
    if (controller) controller.loadUri(rec.spotify);
    showPins();
  }

  function playFrom(q) {
    if (!controller) return say("Spotify lädt noch …");
    const t = Math.max(0, seconds(q) - PREROLL);
    if (!started) {
      pendingSeek = t;
      controller.play();
    } else {
      controller.seek(t);
      if (state.isPaused) controller.resume();
    }
  }

  function pin(q) {
    if (!playing()) return say("Zum Korrigieren während der Wiedergabe Shift-klicken");
    const t = now() - REACTION;
    const pins = loadPins(loaded).filter(([pq]) => Math.abs(pq - q) >= 1);
    pins.push([q, Math.round(t * 100) / 100]);
    savePins(loaded, pins);
    anchors = corrected(loaded, pins);
    showPins();
    say(`T. ${Math.floor(q / 4) + 1}, Zz. ${Math.floor(q % 4) + 1} liegt bei ${t.toFixed(1)} s`);
    console.info("aligned-score: corrected anchors", JSON.stringify(anchors));
  }

  reset.addEventListener("click", () => {
    savePins(loaded, []);
    anchors = corrected(loaded, []);
    showPins();
    say("Korrekturen gelöscht");
  });

  window.onSpotifyIframeApiReady = (api) => {
    const first = loaded;
    api.createController(player.querySelector(".recording-embed > div"), { uri: first.spotify, width: "100%", height: 80 }, (c) => {
      c.addListener("playback_update", ({ data }) => {
        state = { ...data, at: performance.now() };
        if (!data.isPaused && data.position > 0) started = true;
        if (started && pendingSeek !== null) {
          const t = pendingSeek;
          pendingSeek = null;
          c.seek(t);
        }
        if (data.duration && data.duration < 60000 && !warned) {
          warned = true;
          say("Nur die 30-s-Vorschau: bitte im Browser bei Spotify anmelden", true);
        }
      });
      controller = c;
      if (loaded !== first) c.loadUri(loaded.spotify);
    });
  };

  // Clicking into the embed takes the keyboard from the slides; give it back.
  window.addEventListener("blur", () =>
    setTimeout(() => {
      if (document.activeElement?.tagName === "IFRAME") document.activeElement.blur();
    })
  );

  // Scores --------------------------------------------------------------------------------------------------------

  const slides = new Map(); // section → { rec, notes: [{ element, on, off }], first, last }

  function nearestNote(svg, x, y) {
    const systems = [...svg.querySelectorAll("g.system")].map((system) => ({ system, box: system.getBoundingClientRect() }));
    const distance = ({ box }) => (y < box.top ? box.top - y : y > box.bottom ? y - box.bottom : 0);
    const { system } = systems.reduce((best, s) => (distance(s) < distance(best) ? s : best));
    let nearest = null;
    let gap = Infinity;
    for (const note of system.querySelectorAll("g.note")) {
      const box = note.getBoundingClientRect();
      const d = Math.abs((box.left + box.right) / 2 - x);
      if (d < gap || (d === gap && +note.dataset.on < +nearest.dataset.on)) [nearest, gap] = [note, d];
    }
    return nearest;
  }

  async function inline(img) {
    const response = await fetch(img.src);
    const svg = new DOMParser().parseFromString(await response.text(), "image/svg+xml").documentElement;
    svg.setAttribute("class", img.className);
    svg.setAttribute("style", img.getAttribute("style") ?? "");
    svg.setAttribute("role", "img");
    svg.setAttribute("aria-label", img.alt);
    img.replaceWith(svg);
    return svg;
  }

  async function prepare(section) {
    const rec = await recording(section.dataset.recording);
    const svgs = await Promise.all([...section.querySelectorAll("img.aligned")].map(inline));
    const notes = svgs.flatMap((svg) =>
      [...svg.querySelectorAll("g.note[data-on]")].map((element) => ({ element, on: +element.dataset.on, off: +element.dataset.off }))
    );
    slides.set(section, { rec, notes, first: Math.min(...notes.map((n) => n.on)), last: Math.max(...notes.map((n) => n.off)) });
    for (const svg of svgs) {
      svg.addEventListener("click", (event) => {
        if (event.altKey || event.ctrlKey || event.metaKey) return;
        const note = event.target.closest("g.note[data-on]") ?? nearestNote(svg, event.clientX, event.clientY);
        if (!note) return;
        use(rec);
        if (event.shiftKey) pin(+note.dataset.on);
        else playFrom(+note.dataset.on);
      });
    }
  }

  // The notes sounding light up; at the end of an excerpt the next one follows.
  function frame() {
    requestAnimationFrame(frame);
    const slide = slides.get(Reveal.getCurrentSlide());
    if (!slide || slide.rec !== loaded || !anchors) return;
    const q = started ? scoreTime(now()) : -1;
    for (const note of slide.notes) note.element.classList.toggle("sounding", note.on <= q && q < note.off);
    if (!playing() || q < slide.last) return;
    const next = slides.get(Reveal.getSlides()[Reveal.getSlidePastCount() + 1]);
    if (next && next.rec === loaded && next.first <= q && q < next.last) Reveal.next();
  }

  function showPlayer() {
    const slide = slides.get(Reveal.getCurrentSlide());
    player.classList.toggle("visible", Boolean(slide));
    if (slide && !controller && !loaded) use(slide.rec);
  }

  Promise.all(sections.map(prepare)).then(() => {
    use(slides.get(sections[0]).rec);
    const script = document.createElement("script");
    script.src = SPOTIFY_API;
    script.async = true;
    document.head.append(script);
    Reveal.on("slidechanged", showPlayer);
    if (Reveal.isReady()) showPlayer();
    else Reveal.on("ready", showPlayer);
    Reveal.addKeyBinding({ keyCode: 75, key: "K", description: "Aufnahme: Wiedergabe / Pause" }, () => {
      if (!controller) return;
      if (!started) playFrom(0);
      else controller.togglePlay();
    });
    requestAnimationFrame(frame);
  });
})();
