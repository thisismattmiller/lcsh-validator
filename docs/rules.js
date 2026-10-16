/* Rule citations in the verdict ("H 1095 sec. E.3", "Appendix D") become hover targets that show the cited
   sheet: its title, the cited section's text (or the list entry for the subdivision named in the citation),
   otherwise the summary and the numbered validation rules. Sheets are fetched lazily from rules/<file>.json
   (written by scripts/export_rules_json.py). Exposed as window.LcshRules; parseCitations is DOM-free so it
   can be unit-tested with node. */
(function (root) {
  "use strict";
  const SHEET = String.raw`(?:H\s?\d{2,4}(?:\.\d+)?|Appendix\s+[A-H]|Glossary)`;
  // a sheet token, optionally followed by "sec(s)./section(s) X" or ", sec. X" (only the first label is kept)
  const CITE = new RegExp(String.raw`\b(${SHEET})\b((?:,?\s*\(?\s*(?:sec(?:tion)?s?\.?|§)\s*([A-Za-z0-9](?:[\w-]|\.(?=\w)|\(\d+\))*))?)`, "g");
  const STOP = "usage|entry|scope|is|are|was|were|has|does|may|list|under|for|in|on|to|with|by|as|at|which|that|because|but|so|not|would|could|should|must|cannot|from|when|where|whose|only|also|here|there|exists|covers|names|applies|after|before|then|than";
  const SUB = new RegExp(String.raw`--([A-Z][^;,()"'\[\]]*?)(?=\s*[;,()"'\]]|\s+(?:${STOP})\b|\s*$)`);

  function normSheet(s) {
    s = s.replace(/\s+/g, " ").trim();
    const m = /^H\s?(\d+)(?:\.(\d+))?$/i.exec(s);
    if (m) return "H " + parseInt(m[1], 10) + (m[2] ? "." + m[2] : "");
    return s.replace(/^appendix/i, "Appendix").toUpperCase() === "GLOSSARY" ? "Glossary" : s.replace(/^appendix\s+([a-h])$/i, (x, l) => "Appendix " + l.toUpperCase());
  }
  function normSection(s) {
    if (!s) return null;
    s = s.replace(/[.,;:]+$/, "").replace(/^\(|\)$/g, "");
    // "D.2" / "2.b" / "C.4" / "1-2" -> first label only
    const m = /^([A-Za-z]|\d{1,2})((?:\.(?:\d{1,2}|[a-z]|\(\d+\)))*)/.exec(s);
    return m ? m[0] : null;
  }
  /* "See H 1095 sec. E.3 and H 1642." -> [{text}, {ref, sheet, section, label}, ...] */
  function parseCitations(text) {
    const out = [];
    let last = 0;
    const whole = SUB.exec(text);
    for (const m of String(text).matchAll(CITE)) {
      if (m.index > last) out.push({ text: text.slice(last, m.index) });
      // the subdivision named in the same clause as the citation, else the first one in the text
      const cs = text.lastIndexOf(";", m.index) + 1, ce = (text.indexOf(";", m.index) + 1 || text.length + 1) - 1;
      const local = SUB.exec(text.slice(cs, ce)) || whole;
      out.push({ ref: true, label: m[0], sheet: normSheet(m[1]), section: normSection(m[3]), subdivision: local ? "--" + local[1].trim().toLowerCase() : null });
      last = m.index + m[0].length;
    }
    if (last < text.length) out.push({ text: text.slice(last) });
    return out;
  }

  // ------------------------------------------------------------------ data
  const cache = new Map();
  let indexPromise = null;
  function base() { return (root.LCSH_RULES_BASE || "rules/"); }
  function loadIndex() {
    if (!indexPromise) indexPromise = fetch(base() + "index.json").then((r) => r.ok ? r.json() : {}).catch(() => ({}));
    return indexPromise;
  }
  async function loadSheet(sheet) {
    const idx = await loadIndex();
    const entry = idx[sheet];
    if (!entry) return null;
    if (!cache.has(sheet)) cache.set(sheet, fetch(base() + entry.file + ".json").then((r) => r.ok ? r.json() : null).catch(() => null));
    return cache.get(sheet);
  }
  function findSection(doc, label) {
    if (!label || !doc.sections) return null;
    const want = label.toLowerCase();
    let hit = doc.sections.find((s) => (s.id || "").toLowerCase() === want);
    if (!hit) hit = doc.sections.find((s) => (s.id || "").toLowerCase().startsWith(want + "."));
    if (!hit) { const first = want.split(".")[0]; hit = doc.sections.find((s) => (s.id || "").toLowerCase() === first); }
    return hit || null;
  }
  function findEntry(doc, subdivision) {
    if (!subdivision || !doc.list || !doc.list.entries) return null;
    const ents = doc.list.entries;
    if (ents[subdivision]) return ents[subdivision];
    // the citation text may run past the label ("--Directories under topical headings"): try shorter word prefixes
    const words = subdivision.slice(2).split(/\s+/);
    for (let k = words.length - 1; k >= 1; k--) { const key = "--" + words.slice(0, k).join(" "); if (ents[key]) return ents[key]; }
    // multiples on the list: "--paraphrases, english, [french, etc.]" match a value in the slot
    for (const key of Object.keys(ents)) {
      if (key.includes("[") && key.split(",")[0] === subdivision.split(",")[0]) return ents[key];
    }
    return null;
  }

  // ------------------------------------------------------------------ popup
  let pop = null, hideTimer = null, pinned = null;
  function popup() {
    if (pop) return pop;
    pop = document.createElement("div");
    pop.id = "rule-pop";
    pop.hidden = true;
    pop.addEventListener("mouseenter", () => clearTimeout(hideTimer));
    pop.addEventListener("mouseleave", () => { if (!pinned) scheduleHide(); });
    document.body.append(pop);
    document.addEventListener("keydown", (e) => { if (e.key === "Escape") hide(true); });
    document.addEventListener("click", (e) => { if (pinned && !pop.contains(e.target) && !e.target.closest(".rule-ref")) hide(true); });
    return pop;
  }
  function scheduleHide() { clearTimeout(hideTimer); hideTimer = setTimeout(() => hide(false), 260); }
  function hide(force) {
    if (pinned && !force) return;
    pinned = null;
    if (pop) pop.hidden = true;
  }
  function el(tag, cls, text) {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text != null) e.textContent = text;
    return e;
  }
  function clip(s, n) { s = String(s || "").trim(); return s.length > n ? s.slice(0, n).replace(/\s+\S*$/, "") + " …" : s; }
  function md(text) {
    // the sheets are light Markdown: keep paragraphs, tables as preformatted, *emphasis* as plain text
    const box = document.createDocumentFragment();
    const blocks = String(text).split(/\n{2,}/);
    for (const b of blocks) {
      if (!b.trim()) continue;
      if (/^\s*[|`]/.test(b) || /\n\s*\d{3} [#_0-9]/.test(b)) box.append(el("pre", null, b.replace(/```\w*\n?|```/g, "")));
      else box.append(el("p", null, b.replace(/\*([^*]+)\*/g, "$1").replace(/`([^`]+)`/g, "$1")));
    }
    return box;
  }
  function render(ref, doc) {
    const p = popup();
    p.replaceChildren();
    if (!doc) {
      p.append(el("div", "rp-title", ref.sheet), el("p", "rp-warn", "No such sheet in the Subject Headings Manual corpus. If a verdict cites it, the citation is not to a real rule."));
      return;
    }
    p.append(el("div", "rp-title", `${doc.sheet} — ${doc.title || ""}`));
    const entry = findEntry(doc, ref.subdivision);
    const sec = findSection(doc, ref.section);
    if (entry) {
      for (const e of entry) {
        const h = el("div", "rp-sub", (e.subdivision || e.pattern || ref.subdivision) + (e.subfield ? ` ($${e.subfield})` : "") + (e.may_subd_geog ? " (May Subd Geog)" : ""));
        p.append(h);
        if (e.use_under) p.append(el("p", null, "Use under " + e.use_under));
        if (e.rule) p.append(el("p", null, e.rule));
        if (e.notes) p.append(el("p", "rp-note", e.notes));
        if (e.endnote) p.append(el("p", "rp-note", e.endnote));
        if (e.see_also && e.see_also.length) p.append(el("p", "rp-note", "See also " + e.see_also.join("; ")));
        if (e.consult && e.consult.length) p.append(el("p", "rp-note", "Consult " + e.consult.join("; ")));
      }
    }
    if (sec && !(entry && /^[FG]$/.test(sec.id || ""))) {
      p.append(el("div", "rp-sec", `sec. ${sec.id}` + (sec.heading && !sec.heading.startsWith(sec.own + ".") ? ` — ${sec.heading}` : ` — ${sec.heading.slice(sec.own.length + 1).trim()}`)));
      p.append(md(clip(sec.text, 2400)));
    } else if (!entry) {
      if (ref.section) p.append(el("p", "rp-warn", `Section "${ref.section}" was not found on this sheet; showing the sheet summary.`));
      if (doc.summary) p.append(el("p", null, doc.summary));
      if (doc.validation_rules && doc.validation_rules.length) {
        const ol = el("ol", "rp-rules");
        for (const r of doc.validation_rules.slice(0, 8)) ol.append(el("li", null, clip(r, 360)));
        p.append(ol);
        if (doc.validation_rules.length > 8) p.append(el("p", "rp-note", `… ${doc.validation_rules.length - 8} more rules on this sheet.`));
      }
    }
    p.append(el("p", "rp-foot", "Click the citation to keep this open · Esc closes"));
  }
  function place(target) {
    const p = popup();
    p.hidden = false;
    const r = target.getBoundingClientRect();
    const w = Math.min(560, window.innerWidth - 24);
    p.style.width = w + "px";
    let left = Math.max(12, Math.min(r.left, window.innerWidth - w - 12));
    let top = r.bottom + 6;
    p.style.left = left + window.scrollX + "px";
    p.style.top = top + window.scrollY + "px";
    const ph = p.getBoundingClientRect().height;
    if (top + ph > window.innerHeight - 8 && r.top - ph - 6 > 8) p.style.top = r.top - ph - 6 + window.scrollY + "px";
  }
  async function show(target, pin) {
    clearTimeout(hideTimer);
    const ref = { sheet: target.dataset.sheet, section: target.dataset.section || null, subdivision: target.dataset.subdivision || null };
    if (pin) pinned = target;
    const p = popup();
    p.replaceChildren(el("div", "rp-title", ref.sheet), el("p", "rp-note", "Loading…"));
    place(target);
    const doc = await loadSheet(ref.sheet);
    if (pinned && pinned !== target) return;
    render(ref, doc);
    place(target);
  }

  /* Build a DocumentFragment where every citation in `text` is a hover target. */
  function renderText(text) {
    const frag = document.createDocumentFragment();
    for (const part of parseCitations(String(text ?? ""))) {
      if (!part.ref) { frag.append(document.createTextNode(part.text)); continue; }
      const s = el("span", "rule-ref", part.label);
      s.tabIndex = 0;
      s.dataset.sheet = part.sheet;
      if (part.section) s.dataset.section = part.section;
      if (part.subdivision) s.dataset.subdivision = part.subdivision;
      s.title = "Show the rule";
      s.addEventListener("mouseenter", () => { if (!pinned) show(s, false); });
      s.addEventListener("mouseleave", () => { if (!pinned) scheduleHide(); });
      s.addEventListener("focus", () => { if (!pinned) show(s, false); });
      s.addEventListener("blur", () => { if (!pinned) scheduleHide(); });
      s.addEventListener("click", (e) => { e.preventDefault(); if (pinned === s) hide(true); else show(s, true); });
      frag.append(s);
    }
    return frag;
  }

  root.LcshRules = { parseCitations, renderText, loadSheet, normSheet, normSection };
})(typeof window !== "undefined" ? window : globalThis);
