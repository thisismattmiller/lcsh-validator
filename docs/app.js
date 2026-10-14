/* LCSH Heading Validator web UI. Talks to the Lambda Function URL (config.js / Settings) and to
   id.loc.gov directly (it sends Access-Control-Allow-Origin: *) for LCCN -> record -> subjects. */
(() => {
  "use strict";
  const $ = (sel, el = document) => el.querySelector(sel);
  const NS = {
    bf: "http://id.loc.gov/ontologies/bibframe/",
    bflc: "http://id.loc.gov/ontologies/bflc/",
    mads: "http://www.loc.gov/mads/rdf/v1#",
    rdfs: "http://www.w3.org/2000/01/rdf-schema#",
    rdf: "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
  };
  const EXAMPLES = [
    "Taxation--France--Paris",
    "Music--Canada--Toronto",
    "Joints--Dislocation",
    "Salmon--Diseases--Treatment",
    "Shakespeare, William, 1564-1616--Biography",
    "650 _0 $a Tacos $x History $y 20th century",
    "Atlanta Metropolitan Area (Ga.)",
  ];

  // ---------------------------------------------------------------- API URL
  function apiUrl() {
    const q = new URLSearchParams(location.search).get("api");
    if (q) return q;
    return window.LCSH_API_URL || "";
  }

  // ---------------------------------------------------------------- helpers
  function el(tag, attrs = {}, ...children) {
    const e = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs)) {
      if (k === "class") e.className = v;
      else if (k === "text") e.textContent = v;
      else if (k.startsWith("on")) e.addEventListener(k.slice(2), v);
      else e.setAttribute(k, v);
    }
    for (const c of children) if (c != null) e.append(c);
    return e;
  }
  function pretty(s) {
    if (typeof s !== "string") return JSON.stringify(s, null, 1);
    try { return JSON.stringify(JSON.parse(s), null, 1); } catch (e) { return s; }
  }
  function statusClass(st) {
    st = String(st || "").toLowerCase();
    if (st.startsWith("invalid")) return "bad";
    if (st.startsWith("uncertain") || st.startsWith("questionable")) return "unsure";
    return "ok";
  }
  function fmtTokens(u) {
    if (!u) return "";
    return `tokens in ${u.input_tokens} · cache read ${u.cache_read_input_tokens} · cache write ${u.cache_creation_input_tokens} · out ${u.output_tokens}`;
  }

  // ---------------------------------------------------------------- validation
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  async function callApi(heading, effort, onRetry) {
    const url = apiUrl();
    if (!url) throw new Error("No API URL configured: deploy the Lambda (lambda/deploy.sh writes docs/config.js) or pass ?api=.");
    // 429/502/503 are transient (Lambda throttling, model rate limits, cold-start hiccups): retry with backoff
    for (let attempt = 0; ; attempt++) {
      let resp, text;
      try {
        resp = await fetch(url, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ heading, effort }) });
        text = await resp.text();
      } catch (e) {
        if (attempt >= 5) throw e;
        if (onRetry) onRetry(attempt + 1, "network error");
        await sleep(1500 * 2 ** attempt);
        continue;
      }
      if ([429, 502, 503, 504].includes(resp.status) && attempt < 6) {
        if (onRetry) onRetry(attempt + 1, `HTTP ${resp.status}`);
        await sleep(1500 * 2 ** attempt + Math.random() * 1000);
        continue;
      }
      let data;
      try { data = JSON.parse(text); } catch (e) { throw new Error(`API returned ${resp.status}: ${text.slice(0, 300)}`); }
      if (!resp.ok || data.error) throw new Error(data.error || `API returned ${resp.status}`);
      return data;
    }
  }

  function newResultCard(heading) {
    const node = $("#result-template").content.firstElementChild.cloneNode(true);
    $(".heading-string", node).textContent = heading;
    const badge = $(".verdict-badge", node);
    badge.textContent = "running";
    badge.classList.add("pending");
    const status = $(".status", node);
    const t0 = Date.now();
    status.append(el("span", { class: "spinner" }), el("span", { class: "elapsed", text: "contacting validator…" }));
    const timer = setInterval(() => {
      const s = Math.round((Date.now() - t0) / 1000);
      $(".elapsed", status).textContent = `working… ${s}s` + (s > 6 ? " (a cold start of the function can take ~10 s)" : "");
    }, 1000);
    node._timer = timer;
    $(".report", node).hidden = true;
    $(".close", node).addEventListener("click", () => { clearInterval(timer); node.remove(); });
    $("#results").prepend(node);
    node.scrollIntoView({ behavior: "smooth", block: "nearest" });
    return node;
  }

  function renderTranscript(container, transcript) {
    container.replaceChildren();
    if (!transcript || !transcript.length) { container.append(el("p", { class: "hint", text: "No tool calls were needed." })); return; }
    for (const t of transcript) {
      if (t.type === "text") {
        if (t.final) continue; // the final JSON verdict is rendered above
        container.append(el("div", { class: "turn model" }, el("div", { class: "who", text: `turn ${t.turn} · model` }), el("div", { class: "text", text: t.text })));
      } else {
        const input = Object.entries(t.input || {}).map(([k, v]) => `${k}=${JSON.stringify(v)}`).join(", ");
        const d = el("details", { class: "turn tool" },
          el("summary", {}, `${t.tool}(${input})`, " ", el("span", { class: "meta", text: `turn ${t.turn} · ${t.chars} chars · ${t.secs}s${t.is_error ? " · ERROR" : ""}${t.truncated ? " · result truncated" : ""}` })),
          el("pre", { text: pretty(t.result ?? "") }));
        container.append(d);
      }
    }
  }

  function renderResult(node, data) {
    clearInterval(node._timer);
    const v = data.verdict || {};
    const badge = $(".verdict-badge", node);
    badge.className = "verdict-badge " + (v.verdict || "uncertain");
    badge.textContent = (v.verdict || "uncertain").toUpperCase();
    if (v.verdict === "questionable") badge.title = "Constructed from authorized elements, but a usage statement does not clearly cover this heading type; a cataloger should check it.";
    $(".heading-type", node).textContent = [v.heading_type, v.confidence != null ? `confidence ${v.confidence}` : ""].filter(Boolean).join(" · ");
    $(".status", node).replaceChildren();
    const norm = $(".normalized", node);
    if (v.normalized_string && v.normalized_string !== data.heading.replace(/\.$/, "")) {
      norm.append(el("span", { class: "hint", text: v.verdict === "valid" ? "normalized form: " : "suggested form: " }), el("code", { text: v.normalized_string }));
    }
    $(".explanation", node).textContent = v.explanation || "";
    const tb = $("table.elements tbody", node);
    for (const e of v.elements || []) {
      tb.append(el("tr", {}, el("td", { text: e.element }), el("td", { text: e.role }),
        el("td", {}, el("span", { class: "st " + statusClass(e.status), text: e.status })), el("td", { text: e.basis })));
    }
    if (!(v.elements || []).length) $("table.elements", node).remove();
    const issues = $("ul.issues", node);
    for (const i of v.issues || []) {
      issues.append(el("li", {}, el("span", { class: "sev " + i.severity, text: (i.severity || "").toUpperCase() }),
        el("span", {}, `${i.element ? i.element + ": " : ""}${i.problem}`),
        i.rule ? el("span", { class: "rule", text: ` (${i.rule})` }) : null,
        i.fix ? el("div", { class: "hint", text: "Fix: " + i.fix }) : null));
    }
    for (const n of v.lc_practice_notes || []) $("ul.lc-practice", node).append(el("li", { text: n }));
    for (const s of v.suggested_alternatives || []) $("ul.alternatives", node).append(el("li", { text: s }));
    renderTranscript($(".transcript", node), data.transcript);
    $(".facts pre", node).textContent = JSON.stringify(data.facts, null, 1);
    $(".raw pre", node).textContent = JSON.stringify(data, null, 1);
    const tools = (data.transcript || []).filter((t) => t.type === "tool").map((t) => t.tool);
    const cost = data.cost && data.cost.usd != null ? ` · cost $${data.cost.usd.toFixed(4)}` : "";
    $(".stats", node).textContent = `effort ${data.effort} · ${data.turns} turns · ${tools.length} tool calls · ${data.elapsed}s · ${fmtTokens(data.usage)}${cost}`;
    $(".report", node).hidden = false;
    wireReport(node, data);
  }

  // ---------------------------------------------------------------- feedback
  async function postReport(payload) {
    const url = window.LCSH_FEEDBACK_URL || "";
    if (!url) throw new Error("reporting is not configured (no feedback URL)");
    const resp = await fetch(url, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(payload) });
    const out = await resp.json().catch(() => ({}));
    if (!resp.ok || !out.ok) throw new Error(out.error || `feedback service returned ${resp.status}`);
    return out;
  }
  function wireReport(node, data) {
    const btn = $(".report-btn", node), form = $(".report-form", node), status = $(".report-status", node);
    const base = () => ({ heading: data.heading, result: data, page: location.href });
    let sent = null; // {id, key} of the stored report, so a comment updates the same object
    btn.addEventListener("click", async () => {
      btn.disabled = true;
      status.textContent = "Sending report…";
      try {
        sent = await postReport({ ...base(), comment: "" });
        btn.textContent = "Reported as wrong";
        status.textContent = `Thanks, report ${sent.id} recorded.`;
        form.hidden = false;
        $(".report-comment", node).focus();
      } catch (e) {
        btn.disabled = false;
        status.textContent = "Could not send the report: " + (e.message || e);
      }
    });
    form.addEventListener("submit", async (ev) => {
      ev.preventDefault();
      const comment = $(".report-comment", node).value.trim();
      if (!comment) return;
      const send = $("button[type=submit]", form);
      send.disabled = true;
      try {
        await postReport({ ...base(), comment, id: sent && sent.id, key: sent && sent.key });
        form.hidden = true;
        status.textContent = `Thanks, report ${sent ? sent.id : ""} recorded with your comment.`;
      } catch (e) {
        send.disabled = false;
        status.textContent = "Could not add the comment: " + (e.message || e);
      }
    });
  }

  function renderError(node, err) {
    clearInterval(node._timer);
    const badge = $(".verdict-badge", node);
    badge.className = "verdict-badge error";
    badge.textContent = "ERROR";
    $(".status", node).replaceChildren(el("span", { class: "error-text", text: err.message || String(err) }));
    for (const sel of ["table.elements", ".reasoning", ".facts", ".raw", ".report"]) $(sel, node)?.remove();
  }

  // Scheduling: the first request goes alone so it warms the function and writes the prompt cache;
  // after LEAD_MS (or as soon as it finishes) the rest run in parallel, up to MAX_PARALLEL at a time
  // (the function's reserved concurrency). The gate closes again after IDLE_MS without traffic,
  // since by then the cache entry and the warm containers are gone.
  const MAX_PARALLEL = 20, LEAD_MS = 10000, IDLE_MS = 5 * 60 * 1000;
  const queue = [];
  let active = 0, gateOpen = false, lastDone = 0;
  function openGate() { if (!gateOpen) { gateOpen = true; pump(); } }
  function pump() {
    if (gateOpen && active === 0 && lastDone && Date.now() - lastDone > IDLE_MS) gateOpen = false;
    while (queue.length && active < MAX_PARALLEL && (gateOpen || active === 0)) {
      const job = queue.shift();
      active++;
      const lead = !gateOpen;
      if (lead) setTimeout(openGate, LEAD_MS);
      job().finally(() => { active--; lastDone = Date.now(); if (lead) openGate(); pump(); });
    }
  }
  function validate(heading, effort) {
    heading = heading.trim();
    if (!heading) return;
    const node = newResultCard(heading);
    queue.push(async () => {
      const onRetry = (n, why) => { const e = $(".elapsed", node); if (e) e.textContent = `retrying (${why}, attempt ${n})…`; };
      try { renderResult(node, await callApi(heading, effort, onRetry)); }
      catch (e) { renderError(node, e); }
    });
    pump();
  }

  // ---------------------------------------------------------------- LCCN -> record -> subjects
  const SCHEMES = [
    ["authorities/subjects", "LCSH"], ["authorities/childrensSubjects", "LCSH (children's)"], ["authorities/names", "LCNAF"],
    ["fast", "FAST"], ["authorities/genreForms", "LCGFT"], ["mesh", "MeSH"],
  ];
  function schemeOf(node) {
    const abouts = [];
    for (const tag of [["bf", "Source"], ["mads", "MADSScheme"]]) {
      for (const s of node.getElementsByTagNameNS(NS[tag[0]], tag[1])) {
        const a = s.getAttributeNS(NS.rdf, "about") || "";
        if (a) abouts.push(a);
      }
    }
    for (const a of abouts) for (const [k, label] of SCHEMES) if (a.includes(k)) return label;
    const about = node.getAttributeNS(NS.rdf, "about") || "";
    for (const [k, label] of SCHEMES) if (about.includes(k)) return label;
    return abouts.length ? abouts[0].replace(/^https?:\/\/[^/]+\//, "") : "";
  }
  function directChildText(node, ns, local) {
    for (const c of node.children) if (c.namespaceURI === ns && c.localName === local) return c.textContent.trim();
    return "";
  }
  function marcTag(node) {
    const keys = node.getElementsByTagNameNS(NS.bflc, "marcKey");
    if (!keys.length) return "";
    const m = /^(\d{3})/.exec(keys[0].textContent.trim());
    return m ? "6" + m[1].slice(1) : "";
  }
  function parseSubjects(xml) {
    const out = [];
    const seen = new Set();
    for (const subj of xml.getElementsByTagNameNS(NS.bf, "subject")) {
      const node = subj.firstElementChild;
      if (!node) continue;
      const label = directChildText(node, NS.mads, "authoritativeLabel") || directChildText(node, NS.rdfs, "label");
      if (!label || seen.has(label)) continue;
      seen.add(label);
      out.push({ label, scheme: schemeOf(node), tag: marcTag(node), kind: node.localName, uri: node.getAttributeNS(NS.rdf, "about") || "" });
    }
    return out;
  }
  async function loadRecord(lccn) {
    lccn = lccn.replace(/[\s-]/g, "");
    const box = $("#record");
    box.replaceChildren(el("p", { class: "hint" }, el("span", { class: "spinner" }), `resolving LCCN ${lccn} at id.loc.gov…`));
    const idUrl = `https://id.loc.gov/resources/instances/identifier/${encodeURIComponent(lccn)}`;
    // the Location header points at the instance URI; without an RDF Accept header the chain ends at
    // the .html page, which is served without CORS headers, so ask for RDF and read the final URL
    const head = await fetch(idUrl, { method: "HEAD", redirect: "follow", headers: { accept: "application/rdf+xml" } });
    if (!head.ok) throw new Error(`id.loc.gov returned ${head.status} for LCCN ${lccn}`);
    const instanceUrl = head.url.replace(/\.(rdf|html)$/, "");
    // instance ids are numeric (22881244) or prefixed (in00024910740)
    if (!/\/resources\/instances\/[A-Za-z0-9]+$/.test(instanceUrl)) throw new Error(`LCCN ${lccn} did not resolve to an instance (got ${instanceUrl})`);
    const rdf = await fetch(instanceUrl + ".cbd.rdf");
    if (!rdf.ok) throw new Error(`could not fetch ${instanceUrl}.cbd.rdf (${rdf.status})`);
    const xml = new DOMParser().parseFromString(await rdf.text(), "application/xml");
    if (xml.getElementsByTagName("parsererror").length) throw new Error("could not parse the BIBFRAME RDF");
    const title = xml.getElementsByTagNameNS(NS.bf, "mainTitle")[0]?.textContent.trim() || "(no title)";
    const subtitle = xml.getElementsByTagNameNS(NS.bf, "subtitle")[0]?.textContent.trim() || "";
    const subjects = parseSubjects(xml);
    renderRecord(box, { lccn, title: subtitle ? `${title} : ${subtitle}` : title, instanceUrl, subjects });
  }
  function renderRecord(box, rec) {
    box.replaceChildren();
    box.append(el("div", { class: "record-title", text: rec.title }),
      el("div", { class: "record-meta" }, `LCCN ${rec.lccn} · `, el("a", { href: rec.instanceUrl, target: "_blank", rel: "noopener", text: rec.instanceUrl.replace("https://", "") }),
        ` · ${rec.subjects.length} subject${rec.subjects.length === 1 ? "" : "s"}, all queued for validation`));
    if (!rec.subjects.length) { box.append(el("p", { class: "hint", text: "No subjects on this record." })); return; }
    const list = el("ul", { class: "subjects" });
    for (const s of rec.subjects) {
      list.append(el("li", {}, el("span", { class: "tag", text: [s.tag, s.scheme].filter(Boolean).join(" · ") }),
        el("span", { class: "label", text: s.label })));
    }
    box.append(list);
    // validate every subject on the record straight away (lead request first, then parallel)
    const effort = $("#effort").value;
    for (const s of rec.subjects) validate(s.label, effort);
  }

  // ---------------------------------------------------------------- wiring
  for (const ex of EXAMPLES) {
    $("#examples").append(el("button", { type: "button", text: ex, onclick: () => { $("#heading-input").value = ex; validate(ex, $("#effort").value); } }));
  }
  function validateLines(text, effort) {
    for (const line of text.split(/\r?\n/)) validate(line, effort);
  }
  $("#heading-form").addEventListener("submit", (ev) => { ev.preventDefault(); validateLines($("#heading-input").value, $("#effort").value); });
  $("#heading-input").addEventListener("keydown", (ev) => {
    if (ev.key === "Enter" && (ev.metaKey || ev.ctrlKey)) { ev.preventDefault(); $("#heading-form").requestSubmit(); }
  });
  $("#lccn-form").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const btn = $("#lccn-btn");
    btn.disabled = true;
    try { await loadRecord($("#lccn-input").value); }
    catch (e) { $("#record").replaceChildren(el("p", { class: "error-text", text: e.message })); }
    finally { btn.disabled = false; }
  });
  // warm the function (cold start + lazy image loading) while the user is still typing
  if (apiUrl()) fetch(apiUrl(), { method: "GET" }).catch(() => {});
  const params = new URLSearchParams(location.search);
  if (params.get("heading")) { $("#heading-input").value = params.get("heading"); validateLines(params.get("heading"), params.get("effort") || "medium"); }
  if (params.get("lccn")) { $("#lccn-input").value = params.get("lccn"); $("#lccn-form").requestSubmit(); }
})();
