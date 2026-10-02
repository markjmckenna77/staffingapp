/* Cleartelligence Staffing - shared-store shim (Oct 2 2026).
 *
 * The weekly dashboard page was written against the claude.ai artifact database and reaches
 * it through a small Firestore-style API: window.claude.use("db") -> db.collection(name)
 * .add/.onSnapshot/.orderBy and db.doc(path).get/.set/.update/.delete/.onSnapshot, where a
 * snapshot is { docs: [{ id, exists, data() }] } or, for one document, { id, exists, data() }.
 *
 * This file provides the same API on top of /api/db (Postgres), so the page - which the Python
 * pipeline regenerates every week - needs no changes. Live updates are polled every few seconds
 * with a `since` cursor, and the page's own writes are applied locally at once.
 */
(function () {
  "use strict";
  if (window.claude && typeof window.claude.use === "function") return;

  var API = "/api/db";
  var POLL_MS = 4000;
  var cache = {};        // collection -> { docs: {id -> {body, deleted}}, loaded: bool, subs: [fn], errs: [fn] }
  var since = 0;         // server cursor shared by all polled collections
  var timer = null;
  var offline = false;

  function err(code, status) { var e = new Error(code); e.code = code; if (status) e.status = status; return e; }

  function request(method, url, body) {
    return fetch(url, {
      method: method,
      credentials: "same-origin",
      headers: body !== undefined ? { "content-type": "application/json" } : undefined,
      body: body !== undefined ? JSON.stringify(body) : undefined
    }).then(function (r) {
      if (r.status === 204) return null;
      return r.json().catch(function () { return {}; }).then(function (j) {
        if (!r.ok) throw err((j && j.error) || ("http_" + r.status), r.status);
        return j;
      });
    }, function () { throw err("offline"); });
  }

  function col(name) {
    if (!cache[name]) cache[name] = { docs: {}, loaded: false, subs: [], errs: [] };
    return cache[name];
  }

  function frozen(body) {
    var o = {};
    Object.keys(body || {}).forEach(function (k) { o[k] = body[k]; });
    return Object.freeze(o);
  }

  function docSnap(id, rec) {
    var exists = !!(rec && !rec.deleted);
    var body = exists ? frozen(rec.body) : null;
    return { id: id, exists: exists, data: function () { return body; } };
  }

  function colSnap(name, orderField) {
    var c = col(name);
    var docs = Object.keys(c.docs).filter(function (id) { return !c.docs[id].deleted; })
      .map(function (id) { return docSnap(id, c.docs[id]); });
    if (orderField) {
      docs.sort(function (a, b) {
        var x = a.data()[orderField], y = b.data()[orderField];
        return x < y ? -1 : x > y ? 1 : 0;
      });
    }
    return { docs: docs, size: docs.length, empty: !docs.length, forEach: function (fn) { docs.forEach(fn); } };
  }

  function emit(name) {
    var c = col(name);
    if (!c.loaded) return;
    c.subs.slice().forEach(function (s) {
      try { s.fn(s.doc ? docSnap(s.doc, c.docs[s.doc]) : colSnap(name, s.order)); }
      catch (e) { if (window.console) console.error("[sa-shim] snapshot handler failed", e); }
    });
  }

  function apply(name, list) {
    var c = col(name);
    (list || []).forEach(function (d) {
      var cur = c.docs[d.id];
      if (cur && cur.updated > d.updated) return;         // local write newer than the poll
      c.docs[d.id] = { body: d.body || {}, deleted: !!d.deleted, updated: d.updated || 0 };
    });
  }

  function fetchCollections(names, cursor) {
    if (!names.length) return Promise.resolve();
    return request("GET", API + "?c=" + encodeURIComponent(names.join(",")) + (cursor ? "&since=" + cursor : ""))
      .then(function (j) {
        names.forEach(function (n) { apply(n, j.collections && j.collections[n]); col(n).loaded = true; });
        if (!cursor || j.now > since) since = j.now;
        offline = false;
        names.forEach(emit);
      });
  }

  function subscribedNames() {
    return Object.keys(cache).filter(function (n) { return cache[n].subs.length; });
  }

  function poll() {
    var names = subscribedNames();
    var fresh = names.filter(function (n) { return !cache[n].loaded; });
    var p = fresh.length ? fetchCollections(fresh, 0) : Promise.resolve();
    return p.then(function () {
      var loaded = names.filter(function (n) { return cache[n].loaded; });
      return fetchCollections(loaded, since);
    }).catch(function (e) {
      if (!offline) {
        offline = true;
        names.forEach(function (n) { col(n).errs.slice().forEach(function (fn) { try { fn(e); } catch (x) {} }); });
      }
    });
  }

  function schedule() {
    if (timer) return;
    timer = setInterval(function () { if (!document.hidden) poll(); }, POLL_MS);
    document.addEventListener("visibilitychange", function () { if (!document.hidden) poll(); });
  }

  function subscribe(name, fn, onErr, opts) {
    var c = col(name);
    var sub = { fn: fn, order: opts && opts.order, doc: opts && opts.doc };
    c.subs.push(sub);
    if (typeof onErr === "function") c.errs.push(onErr);
    schedule();
    if (c.loaded) { setTimeout(function () { try { sub.fn(sub.doc ? docSnap(sub.doc, c.docs[sub.doc]) : colSnap(name, sub.order)); } catch (e) {} }, 0); }
    else { fetchCollections([name], 0).catch(function (e) { if (typeof onErr === "function") onErr(e); }); }
    return function () {
      c.subs = c.subs.filter(function (s) { return s !== sub; });
      if (onErr) c.errs = c.errs.filter(function (f) { return f !== onErr; });
    };
  }

  function localWrite(name, doc) {
    col(name).docs[doc.id] = { body: doc.body || {}, deleted: !!doc.deleted, updated: doc.updated || Date.now() };
    emit(name);
  }

  function splitPath(path) {
    var parts = String(path).split("/");
    if (parts.length !== 2 || !parts[0] || !parts[1]) throw err("bad_path");
    return parts;
  }

  function docRef(path) {
    var p = splitPath(path), name = p[0], id = p[1];
    var url = API + "/" + encodeURIComponent(name) + "/" + encodeURIComponent(id);
    return {
      id: id,
      path: path,
      get: function () {
        return request("GET", url).then(function (j) {
          if (j && j.exists) localWrite(name, j);
          return docSnap(id, j && j.exists ? { body: j.body, deleted: false } : null);
        });
      },
      set: function (body) {
        return request("PUT", url, body || {}).then(function (j) { localWrite(name, j); });
      },
      update: function (patch) {
        return request("PATCH", url, patch || {}).then(function (j) { localWrite(name, j); });
      },
      delete: function () {
        return request("DELETE", url).then(function () { localWrite(name, { id: id, body: {}, deleted: true }); });
      },
      onSnapshot: function (fn, onErr) { return subscribe(name, fn, onErr, { doc: id }); }
    };
  }

  function colRef(name, order) {
    return {
      id: name,
      add: function (body) {
        return request("POST", API + "/" + encodeURIComponent(name), body || {}).then(function (j) {
          localWrite(name, j);
          return docRef(name + "/" + j.id);
        });
      },
      doc: function (id) { return docRef(name + "/" + id); },
      orderBy: function (field) { return colRef(name, field); },
      onSnapshot: function (fn, onErr) { return subscribe(name, fn, onErr, { order: order }); },
      get: function () {
        return fetchCollections([name], 0).then(function () { return colSnap(name, order); });
      }
    };
  }

  var db = { collection: function (name) { return colRef(name); }, doc: docRef };

  window.claude = window.claude || {};
  window.claude.use = function (cap) {
    if (cap === "db") return Promise.resolve(db);
    return Promise.reject(err("unsupported_capability"));
  };

  /* Comments are attributed to whatever the page has in localStorage "ct.author"; default it
     to the signed-in user's name so nothing is posted as "Unattributed". */
  try {
    var u = window.__saUser || {};
    if (u.name && !window.localStorage.getItem("ct.author")) window.localStorage.setItem("ct.author", u.name);
  } catch (e) {}
})();
