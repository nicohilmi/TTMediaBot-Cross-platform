import { lastSegmentUrl, parseHlsMaster, rankHlsVariants, withPoToken } from './media.mjs';

// Resolving the HLS link of a live broadcast. Kept apart from server.mjs (which needs YouTube.js)
// so that it can be tested against a local HTTP server.

async function fetchPlaylistText(url, { userAgent, timeoutMs, fetchImpl }) {
  const response = await fetchImpl(url, {
    headers: { 'User-Agent': userAgent },
    signal: AbortSignal.timeout(timeoutMs)
  });
  if (!response.ok) throw new Error(`HLS playlist HTTP ${response.status}`);
  return response.text();
}

// HTTP status of the first bytes of one media segment (the body is dropped at once).
async function probeSegment(url, { userAgent, timeoutMs, fetchImpl }) {
  const response = await fetchImpl(url, {
    headers: { 'User-Agent': userAgent, Range: 'bytes=0-1023' },
    signal: AbortSignal.timeout(timeoutMs)
  });
  try {
    await response.body?.cancel();
  } catch {}
  return response.status;
}

// Does this variant really deliver audio? Its playlist is read and the newest segment is asked
// for. A playlist is often served while its segments are refused (no PO token in the link), and
// FFmpeg then plays silence without ever failing.
async function checkVariant(variantUrl, options) {
  const text = await fetchPlaylistText(variantUrl, options);
  const segment = lastSegmentUrl(text, variantUrl);
  if (!segment) return { ok: true, detail: 'no segment listed yet' };
  const status = await probeSegment(segment, options);
  return { ok: status >= 200 && status < 300, detail: `segment HTTP ${status}` };
}

// A live broadcast is an HLS playlist. Its master lists every quality (usually with the picture
// too); only sound is needed, so the cheapest variant that has sound is handed to FFmpeg
// (otherwise it may pick the biggest one and download a 720p video just to play audio).
//
// The PO token goes into the manifest link first (as yt-dlp does): the plain link is only the
// second try, because it is served without a token but its segments then are refused. A link is
// "verified" only after one of its segments has been fetched. When nothing could be verified the
// first variant is still returned (url set, verified false) so the caller can decide to try it.
export async function resolveLivePlaylist(manifestUrl, poToken, {
  userAgent,
  timeoutMs = 8000,
  fetchImpl = fetch
} = {}) {
  const options = { userAgent, timeoutMs, fetchImpl };
  const candidates = [];
  if (poToken) candidates.push({ label: 'with-pot', url: withPoToken(manifestUrl, poToken) });
  candidates.push({ label: 'plain', url: manifestUrl });

  const attempts = [];
  let unverified = null;
  for (const candidate of candidates) {
    try {
      const text = await fetchPlaylistText(candidate.url, options);
      let variants = rankHlsVariants(parseHlsMaster(text, candidate.url));
      if (variants.length === 0 && /^#EXTINF:/m.test(text)) {
        variants = [{ url: candidate.url }]; // already a media playlist
      }
      if (variants.length === 0) {
        attempts.push(`${candidate.label}: no variant with sound`);
        continue;
      }
      for (const variant of variants.slice(0, 3)) {
        try {
          const check = await checkVariant(variant.url, options);
          if (check.ok) {
            return { url: variant.url, verified: true, via: candidate.label, detail: check.detail, attempts };
          }
          attempts.push(`${candidate.label}: ${check.detail}`);
        } catch (error) {
          attempts.push(`${candidate.label}: ${error?.message || error}`);
        }
        if (!unverified) unverified = { url: variant.url, via: candidate.label };
      }
    } catch (error) {
      attempts.push(`${candidate.label}: ${error?.message || error}`);
    }
  }
  return { url: unverified?.url || '', verified: false, via: unverified?.via || '', detail: '', attempts };
}
