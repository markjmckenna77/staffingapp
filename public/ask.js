// Ask bar for the staffing dashboard (Oct 16 2026). Injected by app/route.ts.
// Sends the question (and the last few exchanges, for follow-ups) to /api/ask and renders the
// answer and any result tables in a panel under the session bar. Nothing is stored in the browser.
(function () {
  var form = document.getElementById("sa-ask");
  var input = document.getElementById("sa-ask-q");
  var panel = document.getElementById("sa-ask-panel");
  var log = document.getElementById("sa-ask-log");
  if (!form || !input || !panel || !log) return;

  var history = [];
  var busy = false;
  var EXAMPLES = [
    "Who has the most unbooked time over the next 4 weeks?",
    "What was utilization by practice last month?",
    "Who is under target this month in Data Management?",
    "Who has worked for DoorDash in the last 6 months?",
    "Who is booked on Boston Scientific next week, and for how many hours?",
    "Who has Snowflake and dbt skills and is free in November?",
  ];

  function el(tag, cls, text) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text != null) e.textContent = text;
    return e;
  }
  function esc(s) {
    return String(s).replace(/[&<>"]/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]; });
  }
  // Small markdown subset: paragraphs, "- " bullets, **bold**.
  function md(text) {
    var out = [], list = null;
    String(text || "").split(/\n/).forEach(function (line) {
      var b = /^\s*[-*•]\s+(.*)$/.exec(line);
      var h = esc(b ? b[1] : line).replace(/\*\*(.+?)\*\*/g, "<b>$1</b>");
      if (b) { if (!list) { list = []; } list.push("<li>" + h + "</li>"); return; }
      if (list) { out.push("<ul>" + list.join("") + "</ul>"); list = null; }
      if (line.trim()) out.push("<p>" + h + "</p>");
    });
    if (list) out.push("<ul>" + list.join("") + "</ul>");
    return out.join("");
  }
  function fmt(col, v) {
    if (v == null) return "";
    if (typeof v === "number" || (typeof v === "string" && /^-?\d+(\.\d+)?(e[+-]?\d+)?$/i.test(v) && !/ID$|^WEEK$|MONTH|YEAR|DATE/i.test(col))) {
      var n = Number(v);
      if (/UTIL|PCT|PERCENT|SHARE|AVAILAB|BILLABILITY|TARGET/i.test(col) && Math.abs(n) <= 1.5) return Math.round(n * 100) + "%";
      return n.toLocaleString(undefined, { maximumFractionDigits: Number.isInteger(n) ? 0 : 1 });
    }
    return String(v);
  }
  function label(c) {
    return c.replace(/_/g, " ").toLowerCase().replace(/^\w/, function (x) { return x.toUpperCase(); });
  }
  function table(t) {
    var wrap = el("div", "sa-ask-table");
    var head = el("div", "sa-ask-thead");
    head.appendChild(el("b", null, t.title || "Result"));
    var meta = t.rows.length + " row" + (t.rows.length === 1 ? "" : "s") + (t.truncated ? " (first 500)" : "");
    head.appendChild(el("span", "sa-ask-muted", meta));
    var copy = el("button", "sa-ask-link", "Copy");
    copy.type = "button";
    copy.onclick = function () {
      var tsv = [t.columns.map(label).join("\t")].concat(t.rows.map(function (r) {
        return t.columns.map(function (c) { return fmt(c, r[c]); }).join("\t");
      })).join("\n");
      navigator.clipboard && navigator.clipboard.writeText(tsv).then(function () { copy.textContent = "Copied"; setTimeout(function () { copy.textContent = "Copy"; }, 1500); });
    };
    head.appendChild(copy);
    wrap.appendChild(head);
    var scroller = el("div", "sa-ask-scroll");
    var tb = el("table");
    var tr = el("tr");
    t.columns.forEach(function (c) { tr.appendChild(el("th", null, label(c))); });
    var thead = el("thead"); thead.appendChild(tr); tb.appendChild(thead);
    var body = el("tbody");
    t.rows.slice(0, 200).forEach(function (r) {
      var row = el("tr");
      t.columns.forEach(function (c) {
        var v = r[c];
        var td = el("td", typeof v === "number" ? "n" : null, fmt(c, v));
        row.appendChild(td);
      });
      body.appendChild(row);
    });
    tb.appendChild(body);
    scroller.appendChild(tb);
    wrap.appendChild(scroller);
    if (t.sql) {
      var d = el("details", "sa-ask-sql");
      d.appendChild(el("summary", null, "Query"));
      d.appendChild(el("pre", null, t.sql));
      wrap.appendChild(d);
    }
    return wrap;
  }

  function showExamples() {
    log.innerHTML = "";
    var box = el("div", "sa-ask-examples");
    box.appendChild(el("div", "sa-ask-muted", "Ask anything about consultants, bookings, utilization, clients or open roles. Live from Snowflake; read-only. Try:"));
    EXAMPLES.forEach(function (q) {
      var b = el("button", "sa-ask-chip", q);
      b.type = "button";
      b.onclick = function () { input.value = q; submit(); };
      box.appendChild(b);
    });
    log.appendChild(box);
  }
  function open() {
    panel.hidden = false;
    if (!log.childNodes.length) showExamples();
  }
  function close() { panel.hidden = true; }

  function submit() {
    var q = input.value.trim();
    if (!q || busy) return;
    open();
    if (!history.length) log.innerHTML = "";
    busy = true;
    form.classList.add("sa-busy");
    var item = el("div", "sa-ask-item");
    item.appendChild(el("div", "sa-ask-q", q));
    var ans = el("div", "sa-ask-a");
    ans.appendChild(el("span", "sa-ask-muted sa-ask-wait", "Working it out…"));
    item.appendChild(ans);
    log.appendChild(item);
    item.scrollIntoView({ block: "start", behavior: "smooth" });
    input.value = "";
    fetch("/api/ask", {
      method: "POST",
      credentials: "include",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ question: q, history: history }),
    }).then(function (r) {
      return r.json().catch(function () { return { error: "bad_response" }; }).then(function (j) { return { status: r.status, j: j }; });
    }).then(function (res) {
      ans.innerHTML = "";
      if (res.status !== 200) {
        var msg = res.j.detail || (res.status === 401 ? "Your session has expired - reload the page to sign in again." : "Something went wrong - try again.");
        ans.appendChild(el("p", "sa-ask-err", msg));
        return;
      }
      ans.innerHTML = md(res.j.answer);
      (res.j.tables || []).forEach(function (t) { ans.appendChild(table(t)); });
      history.push({ q: q, a: res.j.answer || "" });
      if (history.length > 3) history.shift();
    }).catch(function () {
      ans.innerHTML = "";
      ans.appendChild(el("p", "sa-ask-err", "Couldn't reach the app - check your connection and try again."));
    }).then(function () {
      busy = false;
      form.classList.remove("sa-busy");
      input.focus();
    });
  }

  form.addEventListener("submit", function (e) { e.preventDefault(); submit(); });
  input.addEventListener("focus", open);
  document.getElementById("sa-ask-close").onclick = close;
  document.getElementById("sa-ask-new").onclick = function () { history = []; showExamples(); input.focus(); };
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape" && !panel.hidden) { close(); input.blur(); }
    var t = e.target;
    var typing = t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.isContentEditable);
    if (!typing && (e.key === "/" || ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k"))) { e.preventDefault(); input.focus(); }
  });
  document.addEventListener("mousedown", function (e) {
    if (!panel.hidden && !panel.contains(e.target) && !form.contains(e.target)) close();
  });
})();
