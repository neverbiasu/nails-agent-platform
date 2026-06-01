#!/usr/bin/env node
/**
 * xhs_rest_bridge.mjs
 *
 * Thin Node.js HTTP server that wraps xhs-mcp's internal modules and
 * exposes a REST API compatible with what xhs_mcp_fetcher.py expects.
 *
 * Endpoints:
 *   GET  /health
 *   GET  /api/v1/login/status
 *   GET  /api/v1/feeds/search?keyword=<kw>[&count=<n>]
 *   GET  /api/v1/feeds/list[?count=<n>]
 *   POST /api/v1/feeds/detail  { feed_id, xsec_token, load_all_comments? }
 *
 * Must run under Node.js v22+ (not Bun) — better-sqlite3 is compiled for
 * Node.js ABI 131 (Node v22–v23).  Bun uses ABI 137 and cannot load the
 * same binary.  dev.sh auto-selects Node v23.1.0 when available via NVM.
 *
 * Usage (dev.sh starts this automatically):
 *   node scripts/xhs_rest_bridge.mjs [--port 18060]
 */

import http from 'http';
import { URL } from 'url';
import { createRequire } from 'module';

// Resolve xhs-mcp package root so this script works regardless of cwd.
const req = createRequire(import.meta.url);
const XHS_MCP_PKG = new URL(
  req.resolve('@sillyl12324/xhs-mcp/package.json'),
  import.meta.url
).pathname.replace(/\/package\.json$/, '');

const PORT = (() => {
  const idx = process.argv.indexOf('--port');
  return idx !== -1 ? parseInt(process.argv[idx + 1], 10) : 18060;
})();

// ── Dynamic ES-module imports from the xhs-mcp package ──────────────────────
const { initDatabase } = await import(`${XHS_MCP_PKG}/dist/db/index.js`);
const { getAccountPool } = await import(`${XHS_MCP_PKG}/dist/core/account-pool.js`);
const { handleContentTools } = await import(`${XHS_MCP_PKG}/dist/tools/content.js`);

// ── Fix xsec_source for search-derived tokens ───────────────────────────────
// xhs-mcp's ContentService.getNote() hardcodes `xsec_source=pc_feed` when
// navigating a note detail page. But every token we forward comes from SEARCH
// results, and XHS binds a token to the channel that issued it: a search token
// is only accepted with `xsec_source=pc_search`. The mismatch makes the detail
// page render "Note not found", so enrichment (full imageList, desc, tags) fails
// for nearly every candidate. We cannot pass a source through getNote()'s
// signature, so we patch the one choke point all detail navigations share —
// BrowserContextManager.newPage — to rewrite the query param on page.goto().
try {
  const { BrowserContextManager } = await import(
    `${XHS_MCP_PKG}/dist/xhs/clients/context.js`
  );
  const _origNewPage = BrowserContextManager.prototype.newPage;
  BrowserContextManager.prototype.newPage = async function patchedNewPage(...args) {
    const page = await _origNewPage.apply(this, args);
    const _origGoto = page.goto.bind(page);
    page.goto = (url, opts) => {
      if (typeof url === 'string' && url.includes('xsec_source=pc_feed')) {
        url = url.replace('xsec_source=pc_feed', 'xsec_source=pc_search');
      }
      return _origGoto(url, opts);
    };
    return page;
  };
  console.error('[xhs-bridge] patched newPage → xsec_source=pc_search for detail');
} catch (err) {
  console.error('[xhs-bridge] WARN: could not patch xsec_source:', err.message);
}

// ── Init database and account pool (shared across all requests) ───────────────
let db, pool;
try {
  db = await initDatabase();
  pool = getAccountPool(db);
  console.error('[xhs-bridge] database + account pool initialised');
} catch (err) {
  console.error('[xhs-bridge] FATAL: failed to init database:', err.message);
  process.exit(1);
}

// ── Helpers ──────────────────────────────────────────────────────────────────
function json(res, code, body) {
  const payload = JSON.stringify(body);
  res.writeHead(code, {
    'Content-Type': 'application/json',
    'Content-Length': Buffer.byteLength(payload),
  });
  res.end(payload);
}

/** Read the full POST body as a UTF-8 string. */
function readBody(req) {
  return new Promise((resolve, reject) => {
    let data = '';
    req.setEncoding('utf8');
    req.on('data', chunk => { data += chunk; });
    req.on('end', () => resolve(data));
    req.on('error', reject);
  });
}

/** Convert xhs-mcp search item → noteCard wrapper Python expects. */
function toFeed(item) {
  return {
    id: item.id || '',
    // xsecToken is required by get_feed_detail; xhs-mcp search returns it at
    // the top level (item.xsecToken) — must be forwarded or detail calls fail.
    xsecToken: item.xsecToken || item.xsec_token || '',
    noteCard: {
      displayTitle: item.title || '',
      // 'description' is not in search results; populated by detail enrichment.
      desc: item.description || '',
      interactInfo: {
        likedCount: String(item.likes || '0'),
        collectedCount: String(item.collects || '0'),
        commentCount: String(item.comments || '0'),
        sharedCount: '0',
      },
      cover: { urlDefault: item.cover || '' },
      user: item.user || {},
    },
  };
}

// ── Request handler ───────────────────────────────────────────────────────────
async function handle(req, res) {
  const u = new URL(req.url, `http://localhost:${PORT}`);
  const path = u.pathname;

  // Health
  if (path === '/health') {
    return json(res, 200, { ok: true });
  }

  // Login status — check if any active account exists in the DB
  if (path === '/api/v1/login/status') {
    try {
      const accounts = db.accounts.findActive();
      const loggedIn = accounts.length > 0;
      return json(res, 200, {
        success: true,
        data: { is_logged_in: loggedIn, account_count: accounts.length },
      });
    } catch (err) {
      console.error('[xhs-bridge] login status error:', err.message);
      return json(res, 500, { success: false, message: err.message });
    }
  }

  // Search
  if (path === '/api/v1/feeds/search') {
    const keyword = u.searchParams.get('keyword') || '';
    const count = parseInt(u.searchParams.get('count') || '20', 10);
    if (!keyword) return json(res, 400, { success: false, message: 'keyword required' });

    try {
      console.error(`[xhs-bridge] search: "${keyword}" count=${count}`);
      const mcpResult = await handleContentTools(
        'xhs_search',
        { keyword, count, timeout: 90000 },
        pool,
        db
      );
      // mcpResult.content[0].text is JSON: { count: N, items: [...] }
      // If the tool returns an error string (e.g. "Search failed: ..."), treat as empty.
      const text = (mcpResult.content?.[0]?.text) || '{}';
      let parsed;
      try { parsed = JSON.parse(text); } catch {
        console.error(`[xhs-bridge] search non-JSON response: ${text.substring(0, 200)}`);
        parsed = {};
      }
      const items = parsed.items || [];
      const feeds = items.map(toFeed);
      return json(res, 200, {
        success: true,
        data: { feeds, total: feeds.length },
      });
    } catch (err) {
      console.error('[xhs-bridge] search error:', err.message);
      return json(res, 500, { success: false, message: err.message });
    }
  }

  // List feeds
  if (path === '/api/v1/feeds/list') {
    const count = parseInt(u.searchParams.get('count') || '20', 10);
    try {
      console.error(`[xhs-bridge] list_feeds count=${count}`);
      const mcpResult = await handleContentTools(
        'xhs_list_feeds',
        {},
        pool,
        db
      );
      const text = (mcpResult.content?.[0]?.text) || '{}';
      let parsed;
      try { parsed = JSON.parse(text); } catch { parsed = {}; }
      const items = (parsed.items || []).slice(0, count);
      const feeds = items.map(toFeed);
      return json(res, 200, {
        success: true,
        data: { feeds, total: feeds.length },
      });
    } catch (err) {
      console.error('[xhs-bridge] list error:', err.message);
      return json(res, 500, { success: false, message: err.message });
    }
  }

  // Detail — POST /api/v1/feeds/detail
  // Python XHSMCPFetcher.get_feed_detail() calls this with:
  //   { feed_id, xsec_token, load_all_comments }
  // We call xhs_get_note and reshape the result into the noteCard-style
  // envelope that _detail_note() / _merge_detail_to_signal() expect.
  if (path === '/api/v1/feeds/detail') {
    let rawBody = '';
    try { rawBody = await readBody(req); } catch { /* ignore */ }
    let params = {};
    try { params = JSON.parse(rawBody || '{}'); } catch { /* ignore */ }

    const feed_id = params.feed_id || '';
    const xsec_token = params.xsec_token || '';
    if (!feed_id || !xsec_token) {
      return json(res, 400, { success: false, message: 'feed_id and xsec_token required' });
    }

    try {
      console.error(`[xhs-bridge] get_note: "${feed_id}"`);
      const mcpResult = await handleContentTools(
        'xhs_get_note',
        { noteId: feed_id, xsecToken: xsec_token, describeImages: false },
        pool,
        db
      );
      const text = (mcpResult.content?.[0]?.text) || '';

      // Error responses from xhs_get_note are plain-text, not JSON.
      if (mcpResult.isError || !text) {
        console.error(`[xhs-bridge] get_note error for ${feed_id}: ${text.substring(0, 200)}`);
        return json(res, 200, { success: false, message: text || 'Note not found' });
      }

      let note;
      try { note = JSON.parse(text); } catch {
        console.error(`[xhs-bridge] get_note non-JSON for ${feed_id}: ${text.substring(0, 200)}`);
        return json(res, 200, { success: false, message: 'Note response parse error' });
      }
      if (!note || typeof note !== 'object') {
        return json(res, 200, { success: false, message: 'Note not found' });
      }

      // xhs_get_note returns { id, title, desc, imageList, stats, tags, time, … }
      // _merge_detail_to_signal() reads note.interactInfo.likedCount — map stats→interactInfo.
      const stats = note.stats || {};
      note.interactInfo = note.interactInfo || {
        likedCount:     String(stats.likedCount     || '0'),
        collectedCount: String(stats.collectedCount || '0'),
        commentCount:   String(stats.commentCount   || '0'),
        sharedCount:    String(stats.shareCount     || '0'),
      };

      // Ensure each imageList entry has urlDefault (Python _image_urls_from_note reads it).
      if (Array.isArray(note.imageList)) {
        note.imageList = note.imageList.map(img => ({
          ...img,
          urlDefault: img.urlDefault || img.url || '',
        }));
      }

      // Return as { success: true, note: {...} }
      // _detail_note() scans body.note → found immediately.
      return json(res, 200, { success: true, note });
    } catch (err) {
      console.error(`[xhs-bridge] detail error for ${feed_id}:`, err.message);
      return json(res, 500, { success: false, message: err.message });
    }
  }

  // Reload account — clears cached XhsClient so next request picks up fresh DB cookies.
  // Call this after running xhs_login.py to apply new cookies without restarting.
  if (path === '/api/v1/accounts/reload' && req.method === 'POST') {
    try {
      const clearedNames = [];
      for (const [id] of pool.clients) {
        clearedNames.push(id);
      }
      pool.clients.clear();
      console.error(`[xhs-bridge] account pool cleared (${clearedNames.length} clients evicted)`);
      return json(res, 200, { success: true, data: { evicted: clearedNames.length } });
    } catch (err) {
      console.error('[xhs-bridge] reload error:', err.message);
      return json(res, 500, { success: false, message: err.message });
    }
  }

  return json(res, 404, { success: false, message: 'not found' });
}

// ── Start server ─────────────────────────────────────────────────────────────
const server = http.createServer((req, res) => {
  handle(req, res).catch((err) => {
    console.error('[xhs-bridge] unhandled error:', err);
    json(res, 500, { success: false, message: String(err) });
  });
});

server.listen(PORT, () => {
  console.error(`[xhs-bridge] listening on http://localhost:${PORT}`);
});

process.on('SIGINT', () => { server.close(); process.exit(0); });
process.on('SIGTERM', () => { server.close(); process.exit(0); });
