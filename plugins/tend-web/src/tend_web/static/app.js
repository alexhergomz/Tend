// Tend web UI. Plain JavaScript: no build step, no libraries.
// Every piece of user text goes into the page as text, never as HTML.
"use strict";

// ── the key, from the address `t web` opened ────────────────────────────
const KEY = (() => {
  const m = location.hash.match(/key=([\w-]+)(?:&go=([\w/-]+))?/);  // &go= opens a page directly
  if (m) { sessionStorage.setItem("tend-key", m[1]); history.replaceState(null, "", `#/${m[2] || "now"}`); }
  return sessionStorage.getItem("tend-key") || "";
})();

let S = null;          // /api/state
let UI = { extensions: [], problems: [] };  // plugin extensions
let route = "now";
let focusRun = null;   // the running focus timer
const $ = (sel, el = document) => el.querySelector(sel);

// ── small helpers ───────────────────────────────────────────────────────
function h(tag, attrs = {}, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k === "class") el.className = v;
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else if (k === "style") el.setAttribute("style", v);
    else el.setAttribute(k, v === true ? "" : v);
  }
  for (const kid of kids.flat(Infinity)) {
    if (kid === null || kid === undefined || kid === false) continue;
    el.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
  }
  return el;
}

async function api(path, body) {
  const opts = { headers: { "X-Tend-Key": KEY } };
  if (body !== undefined) { opts.method = "POST"; opts.body = JSON.stringify(body); opts.headers["Content-Type"] = "application/json"; }
  let res;
  try { res = await fetch(path, opts); } catch (e) { toast("Tend isn't running. Start it again with: t web", { error: true }); throw e; }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    toast(data.error || `Something went wrong (${res.status})`, { error: true });
    throw new Error(data.error || res.status);
  }
  return data;
}

function toast(text, { error = false, undo = false, ms = 4200 } = {}) {
  if (!text) return;
  const box = $("#toasts");
  const el = h("div", { class: "toast" + (error ? " error" : "") }, h("span", {}, text));
  if (undo) el.append(h("button", { onclick: async () => { el.remove(); await doUndo(); } }, "Undo"));
  box.append(el);
  setTimeout(() => el.remove(), undo ? ms + 2500 : ms);
}

function said(data, { undo = true } = {}) {
  const msgs = (data && data.messages) || [];
  if (msgs.length) toast(msgs.join(" · "), { undo });
}

async function doUndo() { said(await api("/api/undo", {}), { undo: false }); await refresh(); }

function minutes(m) {
  m = Math.round(m || 0);
  if (m < 60) return `${m}m`;
  const hh = Math.floor(m / 60), r = m % 60;
  return r ? `${hh}h${String(r).padStart(2, "0")}m` : `${hh}h`;
}
const clock = s => { s = Math.max(0, Math.round(s)); const m = Math.floor(s / 60); return `${String(m).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`; };
const hm = iso => iso.slice(11, 16);
const chip = c => h("span", { class: "chip " + (c.tone === "muted" ? "" : c.tone) }, c.text);
const chips = list => h("div", { class: "chips" }, (list || []).map(chip));
const on = name => S && S.features[name];

// ── theme ───────────────────────────────────────────────────────────────
function applyTheme() {
  let pick = "auto";
  try { pick = localStorage.getItem("tend-theme") || "auto"; } catch (e) { /* private window */ }
  const dark = pick === "dark" || (pick === "auto" && matchMedia("(prefers-color-scheme: dark)").matches);
  document.documentElement.dataset.theme = dark ? "dark" : "light";
  return pick;
}
function setTheme(pick) { try { localStorage.setItem("tend-theme", pick); } catch (e) { /* ignore */ } applyTheme(); render(); }
matchMedia("(prefers-color-scheme: dark)").addEventListener("change", applyTheme);

// ── navigation ──────────────────────────────────────────────────────────
const NAV = [
  { label: "Today" },
  { id: "now", title: "Now", key: "n" },
  { id: "queue", title: "Queue", key: "l", count: () => S.queue.length },
  { id: "inbox", title: "Inbox", key: "t", count: () => S.inbox.length },
  { id: "slipped", title: "Slipped", key: "r", count: () => S.slipped.length, warn: true },
  { label: "Plan" },
  { id: "plan", title: "Day plan", key: "p", feature: "planning" },
  { id: "week", title: "Week", key: "c", feature: "planning" },
  { id: "goals", title: "Goals", key: "g" },
  { label: "Look back" },
  { id: "wins", title: "Wins", key: "w" },
  { id: "patterns", title: "Patterns", key: "i", feature: "learning" },
  { id: "review", title: "Weekly review", key: "v", feature: "review", count: () => (S.status.review ? 1 : 0), warn: true },
  { label: "Tend" },
  { id: "settings", title: "Settings", key: "," },
];

function navItems() {
  const items = NAV.filter(n => !n.feature || on(n.feature));
  const panels = UI.extensions.flatMap(e => e.panels.map(p => ({ id: `plugin/${e.name}/${p.id}`, title: p.title })));
  if (panels.length || UI.extensions.length) items.push({ label: "Plugins" }, ...panels, { id: "plugins", title: "All plugins" });
  return items;
}

function renderNav() {
  const nav = $("#nav");
  nav.replaceChildren(...navItems().map(n => {
    if (n.label) return h("div", { class: "nav-label" }, n.label);
    const count = n.count ? n.count() : 0;
    return h("a", { href: `#/${n.id}`, class: route === n.id ? "on" : "" }, n.title,
      count ? h("span", { class: "count" + (n.warn ? " warn" : "") }, count) : null,
      n.key ? h("span", { class: "key" }, n.key) : null);
  }));
  $("#version").textContent = `Tend ${S.version}`;
}

window.addEventListener("hashchange", () => { route = (location.hash.replace(/^#\/?/, "") || "now"); render(); scrollTo(0, 0); });

// ── rendering ───────────────────────────────────────────────────────────
async function refresh() {
  S = await api("/api/state");
  render();
}

async function render() {
  if (!S) return;
  renderNav();
  const page = $("#page");
  const [view, ...rest] = route.split("/");
  const fn = VIEWS[view] || VIEWS.now;
  try {
    const content = await fn(...rest);
    page.replaceChildren(content);
  } catch (e) { console.error(e); }
}

function pageOf(title, sub, ...body) {
  return h("div", { class: "page" }, h("h1", {}, title), sub ? h("p", { class: "sub" }, sub) : null, ...body);
}

function statusRow() {
  const st = S.status, out = [];
  if (st.at_risk) out.push(h("a", { href: "#/queue" }, h("span", { class: "chip warn" }, `⚑ ${st.at_risk} deadline${st.at_risk > 1 ? "s" : ""} at risk`)));
  if (st.slipped) out.push(h("a", { href: "#/slipped" }, h("span", { class: "chip warn" }, `${st.slipped} slipped · decide`)));
  if (st.too_many_started) out.push(h("span", { class: "chip warn" }, `${st.started} started at once`));
  if (st.inbox) out.push(h("a", { href: "#/inbox" }, h("span", { class: "chip" }, `${st.inbox} in the inbox`)));
  if (st.review) out.push(h("a", { href: "#/review" }, h("span", { class: "chip accent" }, "weekly review due")));
  return out.length ? h("div", { class: "status" }, out) : null;
}

// ── task actions ────────────────────────────────────────────────────────
async function act(id, action, extra = {}) {
  said(await api("/api/act", { id, action, ...extra }));
  closeLayer();
  await refresh();
}

function taskButtons(t, { big = false } = {}) {
  // Focus and Done stand out; the rest stay quiet, so the choice is easy on a hard day.
  const main = big ? "btn big" : "btn", quiet = big ? "btn ghost" : "btn";
  const first = [
    h("button", { class: main + " primary", onclick: () => startFocus(t) }, "Focus", h("kbd", {}, "f")),
    h("button", { class: main, onclick: () => act(t.id, "done") }, "✓ Done", h("kbd", {}, "d")),
  ];
  const rest = [
    h("button", { class: quiet, onclick: () => act(t.id, "skip") }, "Skip today", h("kbd", {}, "s")),
    h("button", { class: quiet, onclick: () => splitDialog(t) }, "Split", h("kbd", {}, "x")),
  ];
  if (on("states")) {
    if (t.stage === "started") rest.push(h("button", { class: quiet, onclick: () => act(t.id, "todo") }, "Back to todo"));
    else if (!big) rest.push(h("button", { class: quiet, onclick: () => act(t.id, "start") }, "Start"));
    rest.push(h("button", { class: quiet, onclick: () => waitDialog(t) }, "Waiting for someone", h("kbd", {}, "h")));
  }
  rest.push(h("button", { class: quiet + (big ? "" : " ghost") + " danger", onclick: () => dropTask(t) }, "Drop", h("kbd", {}, "k")));
  return big ? { first, rest } : [...first, ...rest];
}

async function dropTask(t) {
  if (t.repeat && on("repeat")) {
    const once = await choose(`"${t.title}" repeats.`, [["once", "Skip just this one"], ["stop", "Stop repeating"]]);
    if (!once) return;
    return act(t.id, "drop", { once: once === "once" });
  }
  return act(t.id, "drop");
}

// ── views ───────────────────────────────────────────────────────────────
const VIEWS = {};

VIEWS.now = () => {
  const top = S.queue[0];
  const today = h("p", { class: "faint", style: "margin-top:26px" },
    S.done_today || S.focused_today ? `Today so far: ${S.done_today} done · ${minutes(S.focused_today)} focused` : "");
  if (!top) {
    if (S.first_run) {
      return pageOf("Welcome to Tend", null, h("div", { class: "card empty" },
        h("div", { class: "big" }, "Three steps to start"),
        h("div", { class: "steps" },
          h("div", {}, h("b", {}, "1"), h("span", {}, "Type anything in the box above and press Enter. No details needed.")),
          h("div", {}, h("b", {}, "2"), h("span", {}, "Tend picks the one thing to do now, and says why.")),
          h("div", {}, h("b", {}, "3"), h("span", {}, "Press Focus to start a timer, or Done when it's done.")))));
    }
    return pageOf("Now", null, statusRow(), h("div", { class: "card empty" },
      h("div", { class: "big" }, "Nothing to do right now"),
      h("p", { class: "muted" }, "Add a task above, or enjoy the space."), today));
  }
  const label = top.rule === 1 ? "Deadline at risk" : top.rule === 2 ? "Today's big rock" : "Do this now";
  const more = S.queue.length - 1;
  return h("div", { class: "page" },
    h("div", { style: "height:6px" }), statusRow(),
    h("div", { class: "card now" + (top.rule === 1 ? " risk" : "") },
      h("div", { class: "label" }, label),
      h("div", { class: "title" }, top.title),
      chips(top.chips),
      h("div", { class: "reason" }, top.reason),
      (() => {
        const b = taskButtons(top, { big: true });
        return [h("div", { class: "actions" }, b.first),
          h("div", { class: "more" }, b.rest, h("span", { class: "spacer" }),
            h("button", { class: "btn ghost", onclick: () => openTask(top.id) }, "Details"))];
      })()),
    more > 0 ? h("div", { class: "then" }, `${more} more in the `, h("a", { href: "#/queue" }, "queue"),
      ". Tend shows one at a time on purpose.") : null,
    today);
};

function queueItem(r) {
  return h("div", { class: "item" + (r.rule === 1 ? " risk" : ""), onclick: () => openTask(r.id) },
    h("div", { class: "place" }, r.rule === 1 ? "⚑" : r.place),
    h("div", { class: "name" }, r.title),
    chips(r.chips),
    h("div", { class: "why" }, r.reason));
}

VIEWS.queue = () => {
  const body = [h("div", { class: "card flush" }, S.queue.length
    ? h("div", { class: "list" }, S.queue.map(queueItem))
    : h("div", { class: "empty muted" }, "The queue is empty."))];
  if (S.waiting.length) {
    body.push(h("h2", {}, "Waiting"), h("p", { class: "sub" }, "Not in the queue until they come back, or until a deadline is at risk."),
      h("div", { class: "card flush" }, h("div", { class: "list" }, S.waiting.map(t =>
        h("div", { class: "item", onclick: () => openTask(t.id) }, h("div", { class: "place" }, "⏸"),
          h("div", { class: "name" }, t.title), chips(t.chips))))));
  }
  return pageOf("Queue", "In order, with the reason for each place. Click a task for details.", ...body);
};

VIEWS.inbox = () => {
  const t = S.inbox[0];
  if (!t) return pageOf("Inbox", null, h("div", { class: "card empty" }, h("div", { class: "big" }, "The inbox is empty"),
    h("p", { class: "muted" }, "New tasks without details land here.")));
  const pick = { value: null, size: null };
  const save = h("button", { class: "btn primary", disabled: true, onclick: submit }, "Save");
  const dateIn = h("input", { class: "field", placeholder: "fri, oct20, +3d (optional)", style: "width:220px" });
  const soft = h("input", { type: "checkbox", id: "soft" });
  const goal = S.goals.length && !t.goal ? h("select", { class: "field" }, h("option", { value: "" }, "no goal"),
    S.goals.map(g => h("option", { value: g.name }, g.name))) : null;
  const group = (field, options) => {
    const seg = h("div", { class: "seg" });
    for (const [val, text] of options) {
      seg.append(h("button", {
        onclick: e => {
          pick[field] = val; [...seg.children].forEach(b => b.classList.remove("on")); e.currentTarget.classList.add("on");
          save.disabled = !(pick.value && pick.size);
        },
      }, text));
    }
    return seg;
  };
  async function submit() {
    said(await api("/api/triage", { id: t.id, value: pick.value, size: pick.size, date: dateIn.value, soft: soft.checked,
      goal: goal ? goal.value : null }), { undo: true });
    await refresh();
  }
  return pageOf("Inbox", `${S.inbox.length} to sort. Three quick questions each.`,
    h("div", { class: "card stack" },
      h("div", { style: "font-size:24px;font-weight:650;letter-spacing:-.015em;overflow-wrap:anywhere" }, t.title),
      h("div", {}, h("div", { class: "muted" }, "How much does it matter?"),
        group("value", [[1, "Nice to have"], [2, "Matters"], [3, "Really matters"]])),
      h("div", {}, h("div", { class: "muted" }, "How big is it?"),
        group("size", [["S", "Small · under 1h"], ["M", "Medium · 1–3h"], ["L", "Large · over 3h"]])),
      h("div", {}, h("div", { class: "muted" }, "Does it have a date?"),
        h("div", { class: "row" }, dateIn, h("label", { class: "row muted", for: "soft" }, soft, "soft target (a date for yourself)"))),
      goal ? h("div", {}, h("div", { class: "muted" }, "Goal"), goal) : null,
      h("div", { class: "row" }, save,
        h("button", { class: "btn", onclick: () => { S.inbox.push(S.inbox.shift()); render(); } }, "Later"),
        h("span", { class: "spacer" }),
        h("button", { class: "btn ghost danger", onclick: () => act(t.id, "drop") }, "Drop"))));
};

VIEWS.slipped = () => {
  if (!S.slipped.length) return pageOf("Slipped", null, h("div", { class: "card empty" }, h("div", { class: "big" }, "Nothing has slipped"),
    h("p", { class: "muted" }, "When a date passes, the task comes here for one decision.")));
  return pageOf("Slipped", "Each one needs one decision. Dropping is a valid choice, not a failure.",
    h("div", { class: "stack" }, S.slipped.map(t => {
      const when = h("input", { class: "field", placeholder: "new date, like fri or +1w", style: "width:200px" });
      const resolve = async (choice, date) => { said(await api("/api/resolve", { id: t.id, choice, date })); await refresh(); };
      return h("div", { class: "card stack" },
        h("div", { class: "row" }, h("b", {}, t.title), h("span", { class: "chip warn" }, t.why)),
        chips(t.chips),
        h("div", { class: "row" },
          h("button", { class: "btn primary", onclick: () => resolve("today") }, "Do it today"),
          when, h("button", { class: "btn", onclick: () => when.value ? resolve("reschedule", when.value) : when.focus() }, "Reschedule"),
          h("button", { class: "btn", onclick: () => splitDialog(t) }, "Split"),
          h("button", { class: "btn ghost", onclick: () => resolve("drop") }, t.repeat && on("repeat") ? "Skip this one" : "Drop")));
    })));
};

VIEWS.plan = async () => {
  const P = await api("/api/plan?days=7");
  const day = (P.days.find(d => P.blocks.some(b => b.start.slice(0, 10) === d.date)) || P.days[0]).date;
  const items = [
    ...P.blocks.filter(b => b.start.slice(0, 10) === day).map(b => ({ ...b, kind: "block" })),
    ...P.events.filter(e => e.start.slice(0, 10) === day).map(e => ({ ...e, kind: "event" })),
  ].sort((a, b) => a.start.localeCompare(b.start));
  const label = P.days.find(d => d.date === day).label;
  const planned = P.days.reduce((s, d) => s + d.planned, 0), room = P.days.reduce((s, d) => s + d.capacity, 0);
  return pageOf(label === "today" ? "Today's plan" : `Plan for ${label}`,
    "Built with the same rules as Now, around your calendar. It's never saved: open it again any time.",
    h("div", { class: "card" }, items.length ? h("div", { class: "timeline" }, items.map(it => h("div", { class: "slot" },
      h("div", { class: "time" }, `${hm(it.start)}–${hm(it.end)}`),
      it.kind === "event" ? h("div", { class: "block event" }, it.title)
        : h("div", { class: "block" + (it.rule === 1 ? " risk" : ""), onclick: () => openTask(it.task_id) },
          h("b", {}, it.title), it.goal ? h("span", { class: "chip goal" }, it.goal) : null,
          it.rule === 1 ? h("span", { class: "chip warn" }, "deadline") : it.rule === 2 ? h("span", { class: "chip accent" }, "big rock") : null))))
      : h("div", { class: "empty muted" }, "Nothing planned. Add tasks, or check the working hours in Settings.")),
    P.late.length ? h("div", { class: "stack", style: "margin-top:18px" }, P.late.map(l => h("div", { class: "late" },
      `⚑ ${l.title}: ${l.past ? `past due (${l.due_label})` : l.finish ? `won't be done by ${l.due_label}, ${minutes(l.minutes_left)} lands after it` : `doesn't fit before ${l.due_label}, ${minutes(l.minutes_left)} has no slot`}`))) : null,
    h("p", { class: "muted", style: "margin-top:18px" }, `Next 7 days: ${minutes(planned)} of work planned, room for ${minutes(room)}.`),
    P.unplanned_min ? h("p", { class: "muted" }, `${minutes(P.unplanned_min)} of open work doesn't fit in the next weeks.`) : null);
};

let weekDays = 7;
VIEWS.week = async () => {
  const P = await api(`/api/plan?days=${weekDays}`);
  const capacity = Math.max(...P.days.map(d => d.capacity), 60);
  const rows = [];
  const seen = new Map();
  for (const b of P.blocks) { if (!seen.has(b.task_id)) seen.set(b.task_id, { id: b.task_id, title: b.title, late: P.late.some(l => l.task_id === b.task_id) }); }
  const head = h("tr", {}, h("th", {}, ""), P.days.map((d, i) => h("th", { class: i === 0 ? "today" : "" }, `${d.weekday} ${d.date.slice(8)}`)));
  if (P.events.length) {
    rows.push(h("tr", {}, h("td", { class: "name muted" }, "calendar"), P.days.map(d => {
      const busy = P.events.filter(e => e.start.slice(0, 10) === d.date).reduce((s, e) => s + (new Date(e.end) - new Date(e.start)) / 60000, 0);
      return h("td", {}, busy ? h("div", { class: "busy", style: `width:${Math.min(100, busy / 600 * 100)}%` }) : "");
    })));
  }
  for (const t of seen.values()) {
    rows.push(h("tr", {}, h("td", { class: "name", onclick: () => openTask(t.id), title: t.title }, t.title), P.days.map(d => {
      const m = P.blocks.filter(b => b.task_id === t.id && b.start.slice(0, 10) === d.date).reduce((s, b) => s + b.minutes, 0);
      const deadline = P.deadlines[String(t.id)] === d.date;
      return h("td", {}, h("div", { class: "row", style: "gap:0;flex-wrap:nowrap" },
        m ? h("div", { class: "bar" + (t.late ? " late" : ""), style: `width:${Math.max(8, Math.min(100, m / capacity * 100))}%`, title: minutes(m) }) : null,
        deadline ? h("span", { class: "diamond", title: "deadline" }, "◆") : null));
    })));
  }
  rows.push(h("tr", {}, h("td", { class: "muted" }, "focus"), P.days.map(d => h("td", { class: "total" }, d.planned ? minutes(d.planned) : "–"))));
  const seg = h("div", { class: "seg" }, [7, 14].map(n => h("button", { class: weekDays === n ? "on" : "", onclick: () => { weekDays = n; render(); } }, `${n} days`)));
  return h("div", { class: "page wide" }, h("div", { class: "row" }, h("h1", {}, "The next days"), h("span", { class: "spacer" }), seg),
    h("p", { class: "sub" }, "Each bar is the focus time for that day. ◆ marks a deadline."),
    h("div", { class: "card gantt" }, seen.size ? h("table", {}, h("thead", {}, head), h("tbody", {}, rows))
      : h("div", { class: "empty muted" }, "Nothing planned.")));
};

VIEWS.goals = () => {
  const name = h("input", { class: "field", placeholder: "name, like thesis", style: "width:180px" });
  const weekly = h("input", { class: "field", placeholder: "a week, like 3h", style: "width:130px" });
  const why = h("input", { class: "field", placeholder: "why it matters (optional)", style: "flex:1;min-width:180px" });
  const add = async () => { said(await api("/api/goals", { name: name.value, weekly: weekly.value || "0", why: why.value }), { undo: false }); await refresh(); };
  return pageOf("Goals", "A goal with a weekly target gets one 'big rock' task a day, until it's on track.",
    S.goals.length ? h("div", { class: "grid2" }, S.goals.map(g => {
      const pct = g.weekly_min ? Math.min(100, g.week_min / g.weekly_min * 100) : 0;
      const done = g.weekly_min && g.week_min >= g.weekly_min;
      const edit = h("input", { class: "field", value: g.weekly_min ? minutes(g.weekly_min) : "", placeholder: "3h", style: "width:90px" });
      return h("div", { class: "card stack" },
        h("div", { class: "row" }, h("b", { style: "font-size:17px" }, g.name),
          done ? h("span", { class: "chip good" }, "✓ on track") : null, h("span", { class: "spacer" }),
          h("button", { class: "btn small ghost danger", onclick: async () => { if (await confirmDialog(`Remove the goal "${g.name}"? Its tasks stay.`)) { said(await api("/api/goals/remove", { name: g.name }), { undo: false }); await refresh(); } } }, "Remove")),
        g.why ? h("div", { class: "muted" }, g.why) : null,
        g.weekly_min ? h("div", {}, h("div", { class: "meter" + (done ? " done" : "") }, h("div", { style: `width:${pct}%` })),
          h("div", { class: "muted num", style: "font-size:13px;margin-top:6px" }, `${minutes(g.week_min)} of ${minutes(g.weekly_min)} this week`))
          : h("div", { class: "muted" }, `${minutes(g.week_min)} this week · no weekly target`),
        h("div", { class: "row" }, edit,
          h("button", { class: "btn small", onclick: async () => { said(await api("/api/goals", { name: g.name, weekly: edit.value || "0" }), { undo: false }); await refresh(); } }, "Set weekly target")));
    })) : h("div", { class: "card empty muted" }, "No goals yet."),
    h("h2", {}, "Add a goal"), h("div", { class: "card row" }, name, weekly, why, h("button", { class: "btn primary", onclick: add }, "Add")));
};

let winsWeek = false;
VIEWS.wins = async () => {
  const W = await api(`/api/wins?week=${winsWeek ? 1 : 0}`);
  const seg = h("div", { class: "seg" }, [[false, "Today"], [true, "This week"]].map(([v, t]) =>
    h("button", { class: winsWeek === v ? "on" : "", onclick: () => { winsWeek = v; render(); } }, t)));
  return pageOf("Wins", null, h("div", { class: "row", style: "margin-bottom:16px" }, seg, h("span", { class: "spacer" }),
    h("span", { class: "muted" }, `${W.done.length} done · ${minutes(W.focused_min)} focused`)),
    h("div", { class: "card flush" }, W.done.length ? h("div", { class: "list" }, W.done.map(t => h("div", { class: "item" },
      h("div", { class: "place", style: "color:var(--good)" }, "✓"), h("div", { class: "name" }, t.title),
      h("div", { class: "muted num", style: "font-size:13px" }, winsWeek ? new Date(t.when).toLocaleDateString(undefined, { weekday: "short" }) : hm(t.when)))))
      : h("div", { class: "empty muted" }, "Nothing yet, and that's fine. One small step counts.")));
};

VIEWS.patterns = async () => {
  const C = await api("/api/stats");
  const days = n => `${Math.round(n * 10) / 10} day${Math.abs(n) === 1 ? "" : "s"}`;
  const row = (title, main, sub) => h("div", { class: "check-row" }, h("div", { style: "width:130px;font-weight:600" }, title),
    h("div", {}, h("div", {}, main), h("div", { class: "muted", style: "font-size:13px" }, sub)));
  const shift = (s, kind) => !s.active || s.median_late === null ? ["not enough data", `needs 5 finished tasks with ${kind}`]
    : [s.median_late > 0 ? `done ${days(s.median_late)} after the first date (median)` : s.median_late < 0 ? `done ${days(-s.median_late)} early` : "done on the first date",
      s.shift_days ? `${kind} count as ${days(s.shift_days)} earlier` : "no change needed"];
  return pageOf("Patterns", "What Tend learned from your last 20 finished tasks. Corrections start after 5 of a kind.",
    h("div", { class: "card" },
      row("Time", C.time.active ? `tasks take ×${C.time.factor} your estimate` : "not enough data",
        C.time.active ? `${C.time.samples} tasks · estimates are scaled` : "needs 5 finished tasks with focus time"),
      row("Soft dates", ...shift(C.soft, "soft targets")),
      row("Deadlines", ...shift(C.hard, "deadlines")),
      C.start_to_done.samples ? row("Start to done", `median ${days(C.start_to_done.median_days)}`, "data only, for plugins") : null,
      row("Push-backs", C.pushes.dated ? `${C.pushes.pushed} of ${C.pushes.dated} dated tasks pushed back` : "no dated tasks yet",
        C.pushes.top.length ? `most pushed now: ${C.pushes.top.map(t => `${t.title} (${t.pushes}×)`).join(", ")}` : "data only, for plugins")));
};

VIEWS.review = async () => {
  const R = await api("/api/review");
  const step = (n, title, ...body) => h("div", { class: "card stack" }, h("div", { class: "row" },
    h("span", { class: "chip accent" }, n), h("b", {}, title)), ...body);
  const taskRow = (t, buttons) => h("div", { class: "row" }, h("span", { style: "flex:1;min-width:200px" }, t.title), ...buttons);
  const goalInput = name => {
    const inp = h("input", { class: "field", placeholder: `next small step for ${name}`, style: "flex:1" });
    return h("div", { class: "row" }, h("b", { style: "width:120px" }, name), inp,
      h("button", { class: "btn small", onclick: async () => { if (inp.value) { said(await api("/api/tasks", { text: `${inp.value} +${name} v:3 s:S` })); render(); } } }, "Add"));
  };
  return pageOf("Weekly review", R.last ? `Last one on ${R.last}. About five minutes.` : "Your first one. About five minutes.",
    h("div", { class: "stack" },
      step(1, "Last 7 days", h("div", {}, `${R.done} done · ${minutes(R.focused_min)} focused`),
        R.goals.map(g => h("div", { class: "row" }, h("span", { style: "width:140px" }, g.name),
          h("div", { class: "meter" + (g.spent >= g.weekly_min ? " done" : ""), style: "flex:1" }, h("div", { style: `width:${Math.min(100, g.spent / g.weekly_min * 100)}%` })),
          h("span", { class: "muted num" }, `${minutes(g.spent)} / ${minutes(g.weekly_min)}`)))),
      on("learning") ? step(2, "How your plans usually go", h("a", { href: "#/patterns" }, "See your patterns →")) : null,
      step(3, "Inbox", R.inbox ? h("a", { href: "#/inbox" }, `Sort ${R.inbox} task${R.inbox > 1 ? "s" : ""} →`) : h("span", { class: "muted" }, "Nothing to sort.")),
      step(4, "Slipped tasks", R.slipped ? h("a", { href: "#/slipped" }, `Decide on ${R.slipped} →`) : h("span", { class: "muted" }, "Nothing has slipped.")),
      on("states") ? step(5, "Waiting without a date", R.waiting.length ? R.waiting.map(t => taskRow(t, [
        h("button", { class: "btn small", onclick: () => act(t.id, "todo") }, "Back to the queue"),
        h("button", { class: "btn small", onclick: () => act(t.id, "done") }, "Done"),
        h("button", { class: "btn small ghost", onclick: () => act(t.id, "drop") }, "Drop")])) : h("span", { class: "muted" }, "Nothing is waiting without a date.")) : null,
      step(6, "Old tasks", R.old.length ? R.old.map(t => {
        const when = h("input", { class: "field", placeholder: "date", style: "width:110px" });
        return taskRow(t, [when, h("button", { class: "btn small", onclick: async () => { if (when.value) { said(await api("/api/edit", { id: t.id, text: `aim:${when.value}` })); render(); } } }, "Set date"),
          h("button", { class: "btn small ghost", onclick: () => act(t.id, "drop") }, "Drop")]);
      }) : h("span", { class: "muted" }, "Nothing older than 30 days without a date.")),
      step(7, "Goals", R.empty_goals.length ? [h("div", { class: "muted" }, "These goals have no open tasks, so they can't move forward:"), R.empty_goals.map(goalInput)]
        : h("span", { class: "muted" }, "Every goal with a target has an open task.")),
      h("div", {}, h("button", { class: "btn primary big", onclick: async () => { said(await api("/api/review/done", {}), { undo: false }); await refresh(); location.hash = "#/now"; } }, "Finish the review"))));
};

VIEWS.settings = async () => {
  const C = await api("/api/settings");
  const pick = applyTheme();
  const section = (title, sub, ...body) => [h("h2", {}, title), sub ? h("p", { class: "sub", style: "margin-top:-4px" }, sub) : null, h("div", { class: "card" }, ...body)];
  const file = h("input", { type: "file", accept: ".jsonl,.json,application/json", class: "hidden" });
  file.addEventListener("change", async () => {
    const f = file.files[0]; if (!f) return;
    const replace = await choose(`Import ${f.name}?`, [["add", "Add the tasks to mine"], ["replace", "Replace all my data"]]);
    if (!replace) return;
    if (replace === "replace" && !(await confirmDialog("Replace ALL your data with this file? A copy of your current data is saved first."))) return;
    said(await api("/api/import", { content: await f.text(), replace: replace === "replace" }), { undo: false }); await refresh();
  });
  return pageOf("Settings", null,
    ...section("Look", null, h("div", { class: "row" }, h("span", { style: "width:120px" }, "Theme"),
      h("div", { class: "seg" }, [["auto", "Auto"], ["light", "Light"], ["dark", "Dark"]].map(([v, t]) => h("button", { class: pick === v ? "on" : "", onclick: () => setTheme(v) }, t))))),
    ...section("Features", "Everything beyond the core can be turned off. Your data is kept.",
      C.features.map(f => h("div", { class: "check-row" },
        h("label", { class: "switch" }, h("input", { type: "checkbox", checked: f.on, disabled: f.name === "plugins",
          onchange: async e => { said(await api("/api/features", { name: f.name, on: e.target.checked }), { undo: false }); await refresh(); } }), h("span", {})),
        h("div", {}, h("b", {}, f.name), h("div", { class: "muted", style: "font-size:13px" }, `${f.what} · since ${f.since}`))))),
    ...section("Backups", "A copy is made every day you use Tend. Restoring saves your current data first.",
      h("div", { class: "row", style: "margin-bottom:8px" }, h("button", { class: "btn", onclick: async () => { said(await api("/api/backup", {}), { undo: false }); render(); } }, "Save a copy now")),
      C.backups.length ? C.backups.slice(0, 12).map(b => h("div", { class: "check-row" },
        h("div", { style: "flex:1" }, h("b", { class: "num" }, new Date(b.made).toLocaleString()),
          h("div", { class: "muted", style: "font-size:13px" }, `${b.kind} · ${b.open_tasks ?? "?"} open tasks · ${b.size_kb} KB`)),
        h("button", { class: "btn small", onclick: async () => { if (await confirmDialog(`Go back to the copy from ${new Date(b.made).toLocaleString()}?`)) { said(await api("/api/restore", { n: b.n }), { undo: false }); await refresh(); } } }, "Restore")))
        : h("div", { class: "muted" }, "No copies yet.")),
    ...section("Export and import", "Everything as JSON lines: tasks, goals, focus sessions and history.",
      h("div", { class: "row" },
        h("button", { class: "btn", onclick: async () => { const E = await api("/api/export"); const a = h("a", { href: URL.createObjectURL(new Blob([E.content], { type: "application/json" })), download: E.filename }); a.click(); } }, "Download an export"),
        h("button", { class: "btn", onclick: () => file.click() }, "Import a file…"), file)),
    on("reminders") ? section("Reminders", C.reminders.timer ? `A timer checks for you: ${C.reminders.timer}` : "No timer yet: reminders only come when Tend runs t notify.",
      C.reminders.pending.length ? C.reminders.pending.map(r => h("div", { class: "check-row" }, h("div", {}, h("b", {}, r.title), h("div", { class: "muted" }, r.body))))
        : h("div", { class: "muted", style: "margin-bottom:10px" }, "Nothing new to remind you of."),
      h("div", { class: "row", style: "margin-top:10px" },
        h("button", { class: "btn", onclick: async () => said(await api("/api/reminders", { action: "test" }), { undo: false }) }, "Send a test"),
        C.reminders.timer ? h("button", { class: "btn ghost", onclick: async () => { said(await api("/api/reminders", { action: "uninstall" }), { undo: false }); render(); } }, "Remove the timer")
          : h("button", { class: "btn", onclick: async () => { if (await confirmDialog("Install a timer that checks for reminders every few minutes?")) { said(await api("/api/reminders", { action: "install" }), { undo: false }); render(); } } }, "Install the timer"))) : [],
    ...section("Check-up", "The same checks as t doctor.", C.doctor.map(c => h("div", { class: "check-row" },
      h("div", { class: "mark " + c.level }, { ok: "✓", info: "·", warn: "!", error: "✗" }[c.level]),
      h("div", {}, h("b", {}, c.area), " ", h("span", {}, c.text), c.fix && c.level !== "ok" ? h("div", { class: "muted", style: "font-size:13px" }, `fix: ${c.fix}`) : null)))),
    ...section("Keyboard", "The same keys as interactive mode in the terminal.", keysTable()),
    h("p", { class: "faint", style: "margin-top:20px" }, `Settings file ${C.paths.config} · data ${C.paths.data}`));
};

// ── plugins ─────────────────────────────────────────────────────────────
function renderOutput(r) {
  if (!r.ok) return h("div", { class: "stack" }, h("div", { class: "late" }, r.error || "The plugin failed."), r.output ? h("div", { class: "output" }, r.output) : null);
  if (r.format === "table") {
    const cols = [...new Set(r.rows.flatMap(Object.keys))];
    return r.rows.length ? h("table", { class: "data" }, h("thead", {}, h("tr", {}, cols.map(c => h("th", {}, c)))),
      h("tbody", {}, r.rows.map(row => h("tr", {}, cols.map(c => h("td", {}, row[c] ?? "")))))) : h("div", { class: "muted" }, "Nothing to show.");
  }
  if (r.format === "markdown") return markdown(r.output);
  if (r.format === "html") return h("iframe", { class: "plugin", src: r.frame, sandbox: "allow-scripts", title: "plugin" });
  return h("div", { class: "output" }, r.output || "(no output)");
}

async function runExtension(plugin, item, task) {
  return api("/api/ui/run", { plugin, item, task });
}

VIEWS.plugin = async (name, id) => {
  const ext = UI.extensions.find(e => e.name === name);
  const panel = ext && ext.panels.find(p => p.id === id);
  if (!panel) return pageOf("Plugin", null, h("div", { class: "card muted" }, "This plugin panel isn't installed any more."));
  const r = await runExtension(name, id);
  return pageOf(panel.title, `From the plugin t ${name}`, h("div", { class: "card" }, renderOutput(r)),
    h("p", {}, h("button", { class: "btn small ghost", onclick: render }, "Refresh")));
};

VIEWS.plugins = async () => {
  UI = await api("/api/ui");
  return pageOf("Plugins", "Plugins add panels and buttons with a t-<name>.ui.json file next to the plugin. See EXTENDING.md in the tend-web plugin.",
    UI.problems.length ? h("div", { class: "card stack", style: "margin-bottom:16px" }, UI.problems.map(p => h("div", { class: "late" }, p))) : null,
    UI.extensions.length ? h("div", { class: "stack" }, UI.extensions.map(e => h("div", { class: "card stack" },
      h("div", { class: "row" }, h("b", {}, e.title), h("span", { class: "chip" }, `t ${e.name}`)),
      e.panels.length ? h("div", { class: "row" }, e.panels.map(p => h("a", { class: "btn small", href: `#/plugin/${e.name}/${p.id}` }, p.title))) : null,
      e.actions.filter(a => a.where === "global").length ? h("div", { class: "row" }, e.actions.filter(a => a.where === "global").map(a =>
        h("button", { class: "btn small", onclick: () => pluginAction(e, a) }, a.title))) : null,
      e.actions.some(a => a.where === "task") ? h("div", { class: "muted", style: "font-size:13px" }, "Also adds buttons to each task's details.") : null)))
      : h("div", { class: "card muted" }, "No plugin adds anything to the web UI yet."));
};

async function pluginAction(ext, action, task) {
  if (action.confirm && !(await confirmDialog(action.confirm))) return;
  const r = await runExtension(ext.name, action.id, task ? task.id : undefined);
  dialog(h("h2", { style: "margin-top:0" }, action.title), renderOutput(r));
  if (r.ok) refresh();
}

function markdown(text) {
  const esc = s => s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  const inline = s => esc(s)
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\*\*([^*]+)\*\*/g, "<b>$1</b>")
    .replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>');
  const out = []; let list = false;
  for (const line of text.split("\n")) {
    const m = line.match(/^\s*(?:[-*]|\d+\.)\s+(.*)$/);
    if (m) {
      if (!list) { out.push("<ul>"); list = true; }
      const box = m[1].match(/^\[( |x)\]\s+(.*)$/i);
      out.push(box ? `<li class="check">${box[1].trim() ? "☑" : "☐"} ${inline(box[2])}</li>` : `<li>${inline(m[1])}</li>`);
      continue;
    }
    if (list) { out.push("</ul>"); list = false; }
    const head = line.match(/^(#{1,3})\s+(.*)$/);
    if (head) out.push(`<h${head[1].length + 1}>${inline(head[2])}</h${head[1].length + 1}>`);
    else if (line.trim()) out.push(`<p>${inline(line)}</p>`);
  }
  if (list) out.push("</ul>");
  const div = h("div", { class: "md" });
  div.innerHTML = out.join("");  // safe: every piece was escaped first
  return div;
}

// ── layers: task details, dialogs ───────────────────────────────────────
function closeLayer() { $("#layer").replaceChildren(); }

function layer(el, kind = "drawer") {
  const veil = h("div", { class: "veil" + (kind === "dialog" ? " dialog-veil" : ""), onclick: closeLayer });
  $("#layer").replaceChildren(veil, el);
  const first = el.querySelector("input, textarea, button.primary");
  if (first) setTimeout(() => first.focus(), 30);
}

function dialog(...kids) { layer(h("div", { class: "dialog" }, ...kids, h("div", { class: "row", style: "margin-top:18px" }, h("span", { class: "spacer" }), h("button", { class: "btn", onclick: closeLayer }, "Close"))), "dialog"); }

function confirmDialog(text) {
  return new Promise(resolve => {
    const done = v => { closeLayer(); resolve(v); };
    layer(h("div", { class: "dialog" }, h("p", { style: "margin-top:0;font-size:16px" }, text),
      h("div", { class: "row" }, h("span", { class: "spacer" }), h("button", { class: "btn", onclick: () => done(false) }, "Cancel"),
        h("button", { class: "btn primary", onclick: () => done(true) }, "Yes"))), "dialog");
  });
}

function choose(text, options) {
  return new Promise(resolve => {
    const done = v => { closeLayer(); resolve(v); };
    layer(h("div", { class: "dialog" }, h("p", { style: "margin-top:0;font-size:16px" }, text),
      h("div", { class: "row" }, h("span", { class: "spacer" }), h("button", { class: "btn ghost", onclick: () => done(null) }, "Cancel"),
        options.map(([v, t], i) => h("button", { class: "btn" + (i === 0 ? " primary" : ""), onclick: () => done(v) }, t)))), "dialog");
  });
}

function splitDialog(t) {
  const box = h("textarea", { class: "field", placeholder: "One step per line. Make the first one tiny.\nDetails work too: outline e:20m" });
  layer(h("div", { class: "dialog" }, h("h2", { style: "margin-top:0" }, `Split “${t.title}”`), box,
    h("div", { class: "row", style: "margin-top:14px" }, h("span", { class: "spacer" }), h("button", { class: "btn", onclick: closeLayer }, "Cancel"),
      h("button", { class: "btn primary", onclick: async () => { said(await api("/api/split", { id: t.id, steps: box.value.split("\n") })); closeLayer(); await refresh(); } }, "Split"))), "dialog");
}

function waitDialog(t) {
  const when = h("input", { class: "field", placeholder: "a date, like mon or +1w (optional)", style: "flex:1" });
  const go = v => act(t.id, "wait", { until: v });
  layer(h("div", { class: "dialog" }, h("h2", { style: "margin-top:0" }, `Waiting for someone?`),
    h("p", { class: "muted" }, "The task leaves the queue. With a date, it comes back that day by itself."),
    h("div", { class: "row" }, ["tom", "mon", "+1w"].map(v => h("button", { class: "btn small", onclick: () => go(v) }, v === "tom" ? "tomorrow" : v === "mon" ? "Monday" : "in a week")),
      h("button", { class: "btn small", onclick: () => go("") }, "no date")),
    h("div", { class: "row", style: "margin-top:12px" }, when, h("button", { class: "btn primary", onclick: () => go(when.value) }, "Wait"))), "dialog");
}

async function openTask(id) {
  const t = await api(`/api/task?id=${id}`);
  const inQueue = S.queue.find(r => r.id === id);
  const edit = h("input", { class: "field", style: "flex:1", placeholder: "due:fri v:3 +goal e:1h, or a new title" });
  const save = async () => { if (!edit.value) return; said(await api("/api/edit", { id, text: edit.value })); closeLayer(); await refresh(); };
  edit.addEventListener("keydown", e => { if (e.key === "Enter") save(); });
  const taskActions = UI.extensions.flatMap(e => e.actions.filter(a => a.where === "task").map(a => [e, a]));
  layer(h("div", { class: "drawer" },
    h("button", { class: "btn ghost small close", onclick: closeLayer }, "✕"),
    h("div", { class: "faint num" }, `#${t.id} · ${t.state}`),
    h("h1", { style: "margin:6px 0 10px;overflow-wrap:anywhere" }, t.title),
    chips(t.chips),
    inQueue ? h("p", { class: inQueue.rule === 1 ? "late" : "muted" }, inQueue.reason) : null,
    t.status === "open" ? h("div", { class: "row", style: "margin:18px 0" }, taskButtons(t)) : null,
    t.status === "open" ? [h("h2", {}, "Change"), h("div", { class: "row" }, edit, h("button", { class: "btn", onclick: save }, "Save")),
      h("p", { class: "faint", style: "font-size:13px" }, "Details: +goal  due:fri  aim:fri  after:mon  v:1–3  s:S|M|L  e:45m  @high  @low  every:mon  — none clears, as in due:none")] : null,
    t.steps.length ? [h("h2", {}, "Steps"), h("div", { class: "card flush" }, h("div", { class: "list" }, t.steps.map(s => h("div", { class: "item", onclick: () => openTask(s.id) },
      h("div", { class: "place" }, "└"), h("div", { class: "name" }, s.title), chips(s.chips)))))] : null,
    taskActions.length && t.status === "open" ? [h("h2", {}, "From plugins"), h("div", { class: "row" }, taskActions.map(([e, a]) => h("button", { class: "btn small", onclick: () => pluginAction(e, a, t) }, a.title)))] : null,
    h("p", { class: "faint", style: "margin-top:26px;font-size:13px" }, `Added ${t.created.slice(0, 10)}${t.focused_min ? ` · ${minutes(t.focused_min)} focused` : ""}${t.pushes ? ` · pushed back ${t.pushes}×` : ""}`)));
}

// ── focus timer ─────────────────────────────────────────────────────────
async function startFocus(t) {
  const r = await api("/api/focus/start", { id: t.id });
  const cfg = r.settings;
  if ("Notification" in window && Notification.permission === "default") Notification.requestPermission();
  focusRun = { t, cfg, mode: cfg.default_mode, phase: "work", elapsed: 0, worked: 0, paused: false, rounds: 1, last: performance.now(), msg: "" };
  focusRun.target = targetFor(focusRun);
  focusRun.timer = setInterval(tick, 250);
  drawFocus();
}

function targetFor(f) {
  if (f.phase === "work") return f.mode === "pomo" ? f.cfg.pomo_work * 60 : f.mode === "box" ? f.cfg.box_minutes * 60 : null;
  return null;
}

function ping(text) {
  try {
    const ctx = new AudioContext(), o = ctx.createOscillator(), g = ctx.createGain();
    o.frequency.value = 660; g.gain.setValueAtTime(0.08, ctx.currentTime); g.gain.exponentialRampToValueAtTime(0.0001, ctx.currentTime + 0.8);
    o.connect(g).connect(ctx.destination); o.start(); o.stop(ctx.currentTime + 0.8);
  } catch (e) { /* no sound */ }
  if ("Notification" in window && Notification.permission === "granted") new Notification("Tend", { body: text, silent: true });
}

function tick() {
  const f = focusRun; if (!f) return;
  const now = performance.now(), dt = (now - f.last) / 1000; f.last = now;
  if (!f.paused && f.phase !== "between") { f.elapsed += dt; if (f.phase === "work") f.worked += dt; }
  if (f.target && f.elapsed >= f.target) {
    if (f.phase === "work" && f.mode === "pomo") { ping(`Pomodoro done. Take ${f.cfg.pomo_break} minutes.`); f.phase = "break"; f.elapsed = 0; f.target = f.cfg.pomo_break * 60; }
    else if (f.phase === "work") { ping("Time's up."); f.phase = "between"; f.target = null; f.msg = "Time's up. Continue, finish, or stop here."; }
    else { ping("Break over."); f.phase = "between"; f.target = null; f.msg = "Break over. Ready for another round?"; }
  }
  drawFocus();
}

function focusKey(k) {
  const f = focusRun; if (!f) return false;
  if (k === "p" && f.phase !== "between") f.paused = !f.paused;
  else if (k === "d") endFocus(true);
  else if (k === "q" || k === "Escape") endFocus(false);
  else if (k === "b" && f.phase === "work" && f.mode === "flow") { f.phase = "break"; f.target = Math.max(180, f.elapsed * f.cfg.flow_break_ratio); f.elapsed = 0; }
  else if (k === "s" && f.phase === "break") f.elapsed = f.target;
  else if (k === "c" && f.phase === "between") { f.phase = "work"; f.elapsed = 0; f.paused = false; f.rounds += 1; f.target = targetFor(f); }
  else return false;
  drawFocus();
  return true;
}

async function endFocus(done) {
  const f = focusRun; if (!f) return;
  clearInterval(f.timer); focusRun = null; document.title = "Tend";
  $("#layer").replaceChildren();
  said(await api("/api/focus/end", { id: f.t.id, minutes: f.worked / 60, mode: f.mode, done }), { undo: done });
  await refresh();
}

function drawFocus() {
  const f = focusRun; if (!f) return;
  const R = 130, C = 2 * Math.PI * R;
  const frac = f.target ? Math.min(1, f.elapsed / f.target) : (f.elapsed % 3600) / 3600;
  const left = f.target ? f.target - f.elapsed : f.elapsed;
  document.title = `${clock(left)} · ${f.t.title}`;
  const label = f.paused ? "Paused" : f.phase === "break" ? "Break" : f.phase === "between" ? "Paused" : "Focus";
  const modeSeg = h("div", { class: "seg" }, [["pomo", "Pomodoro"], ["flow", "Flow"], ["box", "Timebox"]].map(([m, t]) => h("button", {
    class: f.mode === m ? "on" : "", disabled: f.worked > 5 && f.mode !== m,
    onclick: () => { if (f.worked <= 5) { f.mode = m; f.phase = "work"; f.elapsed = 0; f.target = targetFor(f); drawFocus(); } },
  }, t)));
  const btn = (k, text, primary) => h("button", { class: "btn big" + (primary ? " primary" : ""), onclick: () => focusKey(k) }, text, h("kbd", {}, k === "Escape" ? "esc" : k));
  const controls = f.phase === "between" ? [btn("c", "Continue", true), btn("d", "✓ Done"), btn("q", "Stop")]
    : f.phase === "break" ? [btn("p", f.paused ? "Resume" : "Pause"), btn("s", "Skip break"), btn("d", "✓ Done"), btn("q", "Stop")]
      : [btn("p", f.paused ? "Resume" : "Pause", true), ...(f.mode === "flow" ? [btn("b", "Take a break")] : []), btn("d", "✓ Done"), btn("q", "Stop")];
  const view = h("div", { class: "focus" },
    modeSeg,
    h("div", { class: "phase" + (f.phase === "break" ? " break" : "") }, label),
    h("div", { class: "what" }, f.t.title),
    h("div", { class: "ring" + (f.phase === "break" ? " break" : "") },
      svgRing(R, C, frac),
      h("div", { class: "clock" }, h("b", {}, clock(left)), h("span", { class: "muted" }, f.target ? "left" : "focused"))),
    f.phase === "between" ? h("div", { class: "muted" }, f.msg) : h("div", { class: "muted" },
      f.mode === "flow" && f.phase === "work" ? `Break earned: ${minutes(Math.max(180, f.elapsed * f.cfg.flow_break_ratio) / 60)}` : `Round ${f.rounds} · ${minutes(f.worked / 60)} focused`),
    h("div", { class: "row", style: "justify-content:center" }, controls));
  $("#layer").replaceChildren(view);
}

function svgRing(R, C, frac) {
  const ns = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(ns, "svg"); svg.setAttribute("viewBox", "0 0 280 280");
  for (const [cls, off] of [["track", 0], ["fill", C * (1 - frac)]]) {
    const c = document.createElementNS(ns, "circle");
    c.setAttribute("cx", 140); c.setAttribute("cy", 140); c.setAttribute("r", R); c.setAttribute("fill", "none");
    c.setAttribute("stroke-width", 14); c.setAttribute("stroke-linecap", "round"); c.setAttribute("class", cls);
    c.setAttribute("stroke-dasharray", C); c.setAttribute("stroke-dashoffset", off);
    svg.append(c);
  }
  return svg;
}

// ── keyboard ────────────────────────────────────────────────────────────
const KEYS = [["n", "Now"], ["l", "Queue"], ["t", "Inbox"], ["r", "Slipped"], ["p", "Day plan"], ["c", "Week"], ["g", "Goals"],
  ["w", "Wins"], ["i", "Patterns"], ["v", "Weekly review"], [",", "Settings"], ["a or /", "Add a task"],
  ["f", "Focus on the top task"], ["d", "Done"], ["s", "Skip today"], ["x", "Split"], ["h", "Wait"], ["k", "Drop"], ["u", "Undo"], ["?", "These keys"], ["esc", "Close"]];

function keysTable() { return h("div", { class: "keys" }, KEYS.map(([k, t]) => [h("span", {}, h("kbd", {}, k)), h("span", {}, t)])); }

document.addEventListener("keydown", e => {
  if (e.metaKey || e.ctrlKey || e.altKey) return;
  if (focusRun) { if (focusKey(e.key)) e.preventDefault(); return; }
  const typing = /^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement.tagName);
  if (e.key === "Escape") { if (typing) document.activeElement.blur(); closeLayer(); return; }
  if (typing || $("#layer").children.length) return;
  const go = { n: "now", l: "queue", t: "inbox", r: "slipped", p: "plan", c: "week", g: "goals", w: "wins", i: "patterns", v: "review", ",": "settings" }[e.key];
  const top = S && S.queue[0];
  if (go) location.hash = `#/${go}`;
  else if (e.key === "a" || e.key === "/") $("#capture-input").focus();
  else if (e.key === "?") dialog(h("h2", { style: "margin-top:0" }, "Keys"), keysTable());
  else if (e.key === "u") doUndo();
  else if (top && e.key === "f") startFocus(top);
  else if (top && e.key === "d") act(top.id, "done");
  else if (top && e.key === "s") act(top.id, "skip");
  else if (top && e.key === "x") splitDialog(top);
  else if (top && e.key === "h" && on("states")) waitDialog(top);
  else if (top && e.key === "k") dropTask(top);
  else return;
  e.preventDefault();
});

// ── capture ─────────────────────────────────────────────────────────────
let previewTimer = null;
$("#capture-input").addEventListener("input", () => {
  clearTimeout(previewTimer);
  const text = $("#capture-input").value;
  previewTimer = setTimeout(async () => {
    const box = $("#preview");
    if (!text.trim()) return box.replaceChildren();
    const p = await api(`/api/parse?text=${encodeURIComponent(text)}`);
    box.replaceChildren(...(p.error ? [h("span", { class: "err" }, p.error)]
      : [h("b", {}, p.title || "…"), ...p.chips.map(chip), h("span", { class: "faint" }, "Enter to add")]));
  }, 140);
});
$("#capture").addEventListener("submit", async e => {
  e.preventDefault();
  const inp = $("#capture-input");
  if (!inp.value.trim()) return;
  said(await api("/api/tasks", { text: inp.value }));
  inp.value = ""; $("#preview").replaceChildren();
  await refresh();
});

$("#theme").addEventListener("click", () => setTheme(document.documentElement.dataset.theme === "dark" ? "light" : "dark"));

// ── start ───────────────────────────────────────────────────────────────
(async function start() {
  applyTheme();
  route = location.hash.replace(/^#\/?/, "") || "now";
  if (!KEY) {
    $("#page").replaceChildren(pageOf("Open Tend from the terminal", "Run t web: it opens this page with its key."));
    return;
  }
  try { UI = await api("/api/ui"); } catch (e) { /* no plugins */ }
  await refresh();
  setInterval(() => { if (!focusRun && !$("#layer").children.length && document.visibilityState === "visible") refresh(); }, 30000);
})();
