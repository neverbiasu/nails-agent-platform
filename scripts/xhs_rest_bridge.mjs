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

/** Convert xhs-mcp search item → noteCard wrapper Python expects. */
function toFeed(item) {
  return {
    id: item.id || '',
    noteCard: {
      displayTitle: item.title || '',
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
      const text = (mcpResult.content?.[0]?.text) || '{}';
      let parsed;
      try { parsed = JSON.parse(text); } catch { parsed = {}; }
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
