/* Meeting Notes panel (Mark, Oct 20 2026).
 *
 * Shows the notes and action items from the last two "Staffing Weekly" meetings at the top of the
 * dashboard, with every earlier meeting behind an "Earlier meetings" disclosure. The records come
 * from the `meetings` collection, which the scheduled Granola import writes through
 * POST /api/meeting-log/import (one document per meeting week: summary, decisions, discussion,
 * actionItems, source {title, url, date}). Nothing here is editable; the ✎ drawers and the Meeting
 * Agenda stay where they are. Injected by app/route.ts after the dashboard's title block.
 */
(function () {
  "use strict";
  var SHOW_LATEST = 2;

  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"]/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c];
    });
  }
  function fmtDate(iso) {
    var m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso || "");
    if (!m) return iso || "";
    var d = new Date(Date.UTC(+m[1], +m[2] - 1, +m[3]));
    return d.toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric", year: "numeric", timeZone: "UTC" });
  }
  function list(title, items, cls) {
    if (!items || !items.length) return "";
    return '<div class="mn-block ' + (cls || "") + '"><div class="mn-label">' + esc(title) + "</div><ul>" +
      items.map(function (x) { return "<li>" + esc(x) + "</li>"; }).join("") + "</ul></div>";
  }
  function actions(items) {
    if (!items || !items.length) return "";
    return '<div class="mn-block mn-actions"><div class="mn-label">Action items</div><ul>' +
      items.map(function (a) {
        var meta = [];
        if (a.owner && a.owner !== "unassigned") meta.push(esc(a.owner));
        if (a.due) meta.push("due " + esc(a.due));
        return "<li><span class=\"mn-check\">&#9744;</span> " + esc(a.text) +
          (meta.length ? ' <span class="mn-meta">' + meta.join(" &middot; ") + "</span>" : "") + "</li>";
      }).join("") + "</ul></div>";
  }
  function meetingHtml(m, open) {
    var src = m.source || {};
    var when = src.date || m.week;
    var title = src.title || "Staffing Weekly";
    var head = '<span class="mn-title">' + esc(title) + '</span> <span class="mn-date">' + esc(fmtDate(when)) + "</span>" +
      (src.url ? ' <a class="mn-link" href="' + esc(src.url) + '" target="_blank" rel="noopener">open in Granola</a>' : "");
    var body = (m.summary ? '<p class="mn-summary">' + esc(m.summary) + "</p>" : "") +
      list("Decisions", m.decisions, "mn-decisions") + actions(m.actionItems) + list("Discussion", m.discussion, "mn-discussion");
    if (!body) body = '<p class="mn-summary mn-muted">No notes were captured for this meeting.</p>';
    return '<details class="mn-meeting"' + (open ? " open" : "") + "><summary>" + head + "</summary><div class=\"mn-body\">" + body + "</div></details>";
  }

  function render(host, docs) {
    var ms = docs.map(function (d) { return d.body || {}; }).filter(function (m) { return m && m.week; });
    ms.sort(function (a, b) { return (b.source && b.source.date || b.week) < (a.source && a.source.date || a.week) ? -1 : 1; });
    var latest = ms.slice(0, SHOW_LATEST), earlier = ms.slice(SHOW_LATEST);
    var html = "";
    if (!ms.length) {
      html = '<p class="mn-summary mn-muted">No meeting notes yet. Once Granola records the Monday Staffing Weekly meeting, ' +
        "the notes and action items from the last two meetings appear here, with earlier meetings underneath.</p>";
    } else {
      html = latest.map(function (m) { return meetingHtml(m, true); }).join("");
      if (earlier.length) {
        html += '<details class="mn-earlier"><summary>Earlier meetings <span class="count-chip">' + earlier.length + "</span></summary>" +
          earlier.map(function (m) { return meetingHtml(m, false); }).join("") + "</details>";
      }
    }
    host.querySelector(".mn-content").innerHTML = html;
  }

  function mount() {
    if (document.getElementById("meeting-notes")) return;
    var anchor = document.querySelector(".agenda-panel") || document.querySelector(".summary-panel");
    if (!anchor || !anchor.parentNode) return;
    var sec = document.createElement("section");
    sec.className = "agenda-panel meeting-notes-panel";
    sec.id = "meeting-notes";
    sec.innerHTML = '<h2 class="sec-head"><span class="sec-caret"></span>Meeting Notes ' +
      '<span class="section4-range">last two Staffing Weekly meetings &middot; from Granola</span></h2>' +
      '<div class="mn-content"><p class="mn-summary mn-muted">Loading&hellip;</p></div>';
    anchor.parentNode.insertBefore(sec, anchor);
    var h = sec.querySelector("h2.sec-head");
    h.style.cursor = "pointer";
    h.addEventListener("click", function (ev) {
      if (ev.target.closest && ev.target.closest("button, a, input, textarea")) return;
      sec.classList.toggle("sec-collapsed");
    });
    load(sec);
  }

  function load(sec) {
    fetch("/api/db?c=meetings", { credentials: "same-origin" })
      .then(function (r) { return r.ok ? r.json() : Promise.reject(new Error("HTTP " + r.status)); })
      .then(function (j) { render(sec, (j.collections && j.collections.meetings) || []); })
      .catch(function (e) {
        sec.querySelector(".mn-content").innerHTML = '<p class="mn-summary mn-muted">Meeting notes are not available right now (' + esc(e.message) + ").</p>";
      });
  }

  var css = document.createElement("style");
  css.textContent =
    ".meeting-notes-panel .mn-content{font-size:13px}" +
    ".meeting-notes-panel .mn-meeting{border:1px solid var(--border,#ddd);border-radius:8px;padding:6px 12px;margin:0 0 8px;background:var(--surface-page,transparent)}" +
    ".meeting-notes-panel .mn-meeting>summary{cursor:pointer;font-weight:600;list-style:none;display:flex;gap:8px;align-items:baseline;flex-wrap:wrap}" +
    ".meeting-notes-panel summary::-webkit-details-marker{display:none}" +
    ".meeting-notes-panel .mn-meeting>summary::before{content:'\\25B8';display:inline-block;transition:transform .12s ease;color:var(--muted-ink,#888)}" +
    ".meeting-notes-panel .mn-meeting[open]>summary::before{transform:rotate(90deg)}" +
    ".meeting-notes-panel .mn-date{color:var(--text-secondary,#555);font-weight:500}" +
    ".meeting-notes-panel .mn-link{margin-left:auto;font-size:11.5px;font-weight:500;color:var(--accent,#2a78d6);text-decoration:none}" +
    ".meeting-notes-panel .mn-link:hover{text-decoration:underline}" +
    ".meeting-notes-panel .mn-body{padding:4px 0 6px 18px}" +
    ".meeting-notes-panel .mn-summary{margin:4px 0 8px;line-height:1.45}" +
    ".meeting-notes-panel .mn-muted{color:var(--muted-ink,#888);font-style:italic}" +
    ".meeting-notes-panel .mn-block{margin:0 0 8px}" +
    ".meeting-notes-panel .mn-label{font-size:10.5px;font-weight:700;letter-spacing:.04em;text-transform:uppercase;color:var(--text-secondary,#555);margin-bottom:2px}" +
    ".meeting-notes-panel ul{margin:0;padding-left:18px;line-height:1.45}" +
    ".meeting-notes-panel .mn-actions ul{list-style:none;padding-left:2px}" +
    ".meeting-notes-panel .mn-check{color:var(--muted-ink,#888);margin-right:2px}" +
    ".meeting-notes-panel .mn-meta{color:var(--muted-ink,#888);font-size:11.5px}" +
    ".meeting-notes-panel .mn-earlier{margin-top:4px}" +
    ".meeting-notes-panel .mn-earlier>summary{cursor:pointer;font-weight:600;color:var(--accent,#2a78d6);list-style:none;margin:0 0 6px}" +
    ".meeting-notes-panel .mn-earlier>summary::before{content:'\\25B8';display:inline-block;margin-right:6px;transition:transform .12s ease}" +
    ".meeting-notes-panel .mn-earlier[open]>summary::before{transform:rotate(90deg)}" +
    ".meeting-notes-panel .mn-earlier .mn-meeting{margin-left:8px}";
  document.head.appendChild(css);

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", mount);
  else mount();
})();
