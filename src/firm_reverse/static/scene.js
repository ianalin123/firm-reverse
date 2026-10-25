(() => {
  const fr = window.firmReverse;
  const { el } = fr;
  const style = document.createElement("style");
  style.textContent = `
    .scene-card { background: var(--panel); border: 2px solid var(--ink); border-radius: 4px; padding: 14px 16px; margin-top: 18px; }
    .scene-card .lede { color: var(--muted); font-size: 15.5px; margin: 0 0 12px; max-width: 68ch; }
    .scene-card button { min-height: 48px; }
    .iters { display: flex; flex-direction: column; gap: 14px; margin-top: 14px; }
    .iters:empty { display: none; }
    .scene-card .status:empty { min-height: 0; margin: 0; }
    .iter { display: grid; grid-template-columns: minmax(0, 2fr) minmax(0, 3fr); gap: 16px; border-top: 1px solid var(--rule); padding-top: 12px; }
    .iter .renders { display: grid; grid-template-columns: 1fr 1fr; gap: 6px; align-content: start; }
    .iter img { width: 100%; border-radius: 2px; border: 2px solid var(--ink); background: #eef1ec; display: block; }
    .iter h3 { font: 700 22px/1 var(--cond); margin: 0 0 6px; }
    .iter .score { display: inline-block; font: 700 18px/1 var(--cond); color: var(--good); background: var(--good-wash); border: 1.5px solid currentColor; border-radius: 2px; padding: 4px 8px 3px; }
    .iter ul { margin: 8px 0 0; padding-left: 20px; font-size: 15px; }
    .iter li { margin: 2px 0; }
    .iter .fixing { color: var(--trace); font-weight: 600; font-size: 15px; margin-top: 8px; }
    .scene-frame { width: 100%; height: 520px; border: 2px solid var(--ink); border-radius: 4px; margin-top: 14px; display: block;
      background: #eef1ec radial-gradient(circle, #cdd3cd 1px, transparent 1.2px) 0 0 / 24px 24px; }
    @media (max-width: 760px) { .iter { grid-template-columns: 1fr; } .scene-frame { height: 380px; } }
  `;
  document.head.append(style);

  const button = el("button", { className: "quiet", textContent: "Build the 3D model" });
  const status = el("div", { className: "status" });
  const iters = el("div", { className: "iters" });
  const frameSlot = el("div");
  document.getElementById("sceneSlot").append(el("section", { className: "scene-card" },
    el("h2", { textContent: "3D reconstruction, checked against your shots" }),
    el("p", { className: "lede", textContent: "Argon writes a 3D model, a headless browser renders it, and Argon compares the render with your real shots. It fixes every mismatch and renders again until they match." }),
    button, status, iters, frameSlot));

  const rows = {};
  const row = (n) => {
    if (!rows[n]) {
      rows[n] = { renders: el("div", { className: "renders" }), notes: el("div", {}, el("h3", { textContent: `Pass ${n}` })) };
      iters.append(el("div", { className: "iter" }, rows[n].renders, rows[n].notes));
    }
    return rows[n];
  };

  const observer = new MutationObserver(() => { button.disabled = fr.shots() === 0 || building; });
  observer.observe(document.getElementById("film"), { childList: true });
  let building = false;
  button.disabled = true;

  button.addEventListener("click", async () => {
    building = true;
    button.disabled = true;
    iters.replaceChildren();
    frameSlot.replaceChildren();
    Object.keys(rows).forEach((k) => delete rows[k]);
    status.textContent = "Argon is writing the first model. This takes a minute or two.";
    status.className = "status";
    try {
      const res = await fr.api(`/api/guide/${fr.session()}/scene`, { method: "POST" });
      await fr.readEvents(res, (ev) => {
        if (ev.kind === "render") {
          const r = row(ev.iteration);
          r.renders.replaceChildren(...Object.entries(ev.images).map(([view, src]) => el("img", { src, alt: `Pass ${ev.iteration}, ${view} view` })));
          status.textContent = `Pass ${ev.iteration} rendered. Argon is comparing it with your shots.`;
        }
        if (ev.kind === "critique") {
          const c = ev.critique;
          const r = row(ev.iteration);
          r.notes.append(
            el("div", { className: "score", textContent: `Match ${Math.round((Number(c.match_score) || 0) * 100)}%` }),
            el("div", { textContent: c.verdict || "" }),
            el("ul", {}, ...(c.mismatches || []).slice(0, 6).map((m) => el("li", { textContent: `${m.part}: ${m.problem}${m.evidence ? ` (${m.evidence})` : ""}` }))));
        }
        if (ev.kind === "patched") {
          row(ev.iteration).notes.append(el("div", { className: "fixing", textContent: "Patching the model and rendering again…" }));
          status.textContent = `Fixing what pass ${ev.iteration} got wrong.`;
        }
        if (ev.kind === "error") throw new Error(ev.message);
        if (ev.kind === "done") {
          status.textContent = `Best match: pass ${ev.iteration} at ${Math.round(ev.match_score * 100)}%. Drag to orbit, slide to explode.`;
          frameSlot.replaceChildren(el("iframe", { className: "scene-frame", src: `/api/guide/${fr.session()}/scene.html`, title: "Interactive 3D model", sandbox: "allow-scripts" }));
        }
      });
    } catch (e) {
      status.textContent = `The 3D build stopped: ${e.message}`;
      status.className = "status error";
    } finally {
      building = false;
      button.disabled = fr.shots() === 0;
    }
  });
})();
