import assert from 'node:assert/strict';
import http from 'node:http';
import test from 'node:test';

import { resolveLivePlaylist } from '../live.mjs';

const TOKEN = 'TESTPOT_abc-123';

// A small stand-in for the YouTube manifest server. Like the real one it serves every playlist
// with HTTP 200 whether or not the PO token is in the link, but it refuses the media segments
// (HTTP 403) when the token is missing from the path. That is what made a broadcast "play" silence.
function startServer({ segmentsNeedToken = true, rejectTokenManifest = false, audioOnly = false } = {}) {
  const requests = [];
  const server = http.createServer((req, res) => {
    requests.push(`${req.method} ${req.url}`);
    const withToken = req.url.includes(`/pot/${TOKEN}`);
    const prefix = withToken ? `/pot/${TOKEN}` : '';
    if (req.url.startsWith('/api/manifest/')) {
      if (rejectTokenManifest && withToken) {
        res.statusCode = 404;
        return res.end();
      }
      res.setHeader('content-type', 'application/vnd.apple.mpegurl');
      const picture = '#EXT-X-STREAM-INF:BANDWIDTH=290000,CODECS="avc1.42C00B,mp4a.40.5",RESOLUTION=256x144\n'
        + `/hls${prefix}/v91.m3u8\n`;
      const sound = '#EXT-X-STREAM-INF:BANDWIDTH=49000,CODECS="mp4a.40.5"\n'
        + `/hls${prefix}/a139.m3u8\n`;
      return res.end(`#EXTM3U\n${picture}${audioOnly ? sound : ''}`);
    }
    if (req.url.startsWith('/hls/')) {
      res.setHeader('content-type', 'application/vnd.apple.mpegurl');
      return res.end(`#EXTM3U\n#EXT-X-TARGETDURATION:5\n#EXTINF:5.0,\n/seg${prefix}/1.ts\n#EXTINF:5.0,\n/seg${prefix}/2.ts\n`);
    }
    if (req.url.startsWith('/seg/')) {
      if (segmentsNeedToken && !withToken) {
        res.statusCode = 403;
        return res.end('forbidden');
      }
      res.statusCode = 206;
      return res.end('x'.repeat(1024));
    }
    res.statusCode = 404;
    return res.end();
  });
  return new Promise((resolve) => {
    server.listen(0, '127.0.0.1', () => {
      const base = `http://127.0.0.1:${server.address().port}`;
      resolve({
        base,
        manifest: `${base}/api/manifest/hls_variant/expire/9999999999/file/index.m3u8`,
        requests,
        close: () => server.close()
      });
    });
  });
}

const options = { userAgent: 'test-agent', timeoutMs: 3000 };

test('with a PO token the segments are reachable: the link carries the token and is verified', async () => {
  const server = await startServer();
  try {
    const result = await resolveLivePlaylist(server.manifest, TOKEN, options);
    assert.equal(result.verified, true);
    assert.equal(result.via, 'with-pot');
    assert.equal(result.url, `${server.base}/hls/pot/${TOKEN}/v91.m3u8`);
    // the plain link was not needed at all
    assert.equal(server.requests.some((line) => line.startsWith('GET /api/manifest/') && !line.includes('/pot/')), false);
  } finally {
    server.close();
  }
});

test('a playlist that is served while its segments are refused is not handed over as good', async () => {
  const server = await startServer();
  try {
    const result = await resolveLivePlaylist(server.manifest, undefined, options);
    assert.equal(result.verified, false);
    assert.match(result.attempts.join(' '), /segment HTTP 403/);
    assert.ok(result.url, 'the first variant is still returned so the caller can decide');
  } finally {
    server.close();
  }
});

test('when the manifest with the token is refused, the plain link is used', async () => {
  const server = await startServer({ segmentsNeedToken: false, rejectTokenManifest: true });
  try {
    const result = await resolveLivePlaylist(server.manifest, TOKEN, options);
    assert.equal(result.verified, true);
    assert.equal(result.via, 'plain');
    assert.match(result.attempts.join(' '), /HTTP 404/);
  } finally {
    server.close();
  }
});

test('an audio-only variant is preferred over one with a picture', async () => {
  const server = await startServer({ audioOnly: true });
  try {
    const result = await resolveLivePlaylist(server.manifest, TOKEN, options);
    assert.equal(result.verified, true);
    assert.match(result.url, /a139\.m3u8$/);
  } finally {
    server.close();
  }
});

test('a manifest that cannot be reached gives an unverified empty result with the reason', async () => {
  const result = await resolveLivePlaylist('http://127.0.0.1:9/api/manifest/hls_variant/file/index.m3u8', TOKEN, {
    userAgent: 'test-agent',
    timeoutMs: 1500
  });
  assert.equal(result.verified, false);
  assert.equal(result.url, '');
  assert.equal(result.attempts.length, 2); // with the token, then plain
});
