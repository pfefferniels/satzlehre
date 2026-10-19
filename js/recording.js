/* One Spotify player at the foot of the slides marked <section data-spotify="track/…">. It stays loaded across
   them, so the music goes on while the slides turn. Spotify plays full tracks only to a signed-in browser. */
(() => {
  const sections = [...document.querySelectorAll(".reveal .slides section[data-spotify]")];
  if (!sections.length || /receiver/i.test(location.search)) return;

  const embed = (path) => `https://open.spotify.com/embed/${path}`;

  const player = document.createElement("iframe");
  player.className = "recording-player";
  player.allow = "autoplay; clipboard-write; encrypted-media; fullscreen; picture-in-picture";
  player.src = embed(sections[0].dataset.spotify);
  document.querySelector(".reveal .slides").append(player);

  function show() {
    const path = Reveal.getCurrentSlide()?.dataset.spotify;
    player.classList.toggle("visible", Boolean(path));
    if (path && player.src !== embed(path)) player.src = embed(path);
  }

  // Clicking into the player takes the keyboard from the slides; give it back.
  window.addEventListener("blur", () =>
    setTimeout(() => {
      if (document.activeElement === player) player.blur();
    })
  );

  Reveal.on("slidechanged", show);
  if (Reveal.isReady()) show();
  else Reveal.on("ready", show);
})();
