const STREAM_CACHE_FALLBACK_TTL_MS = 5 * 60 * 1000;
const STREAM_CACHE_MAX_TTL_MS = 60 * 60 * 1000;
const STREAM_EXPIRY_SAFETY_MS = 2 * 60 * 1000;

function text(value) {
  if (!value) return '';
  if (typeof value === 'string') return value;
  if (typeof value.text === 'string') return value.text;
  if (typeof value.toString === 'function') return value.toString();
  return '';
}

export function normalizeSearchKey(mode, query) {
  const normalized = String(query || '').trim().replace(/\s+/g, ' ').toLocaleLowerCase();
  return `${mode}:${normalized}`;
}

export function musicItemPayload(item) {
  const id = item?.id || item?.video_id || item?.videoId || '';
  if (!/^[A-Za-z0-9_-]{11}$/.test(id)) return null;
  const artists = Array.isArray(item.artists)
    ? item.artists
      .map((artist) => ({ name: text(artist?.name) }))
      .filter((artist) => artist.name)
    : [];
  const uploader = artists.map((artist) => artist.name).join(', ') || text(item.author);

  return {
    id,
    videoId: id,
    title: text(item.title),
    uploader,
    artists,
    duration: Number(item?.duration?.seconds || item?.duration_seconds || 0),
    webpage_url: `https://www.youtube.com/watch?v=${id}`
  };
}

export function streamCacheTtlMs(streamUrl, nowMs = Date.now()) {
  try {
    const url = new URL(streamUrl);
    // Normal stream links carry ?expire=<seconds>; HLS (live) links carry /expire/<seconds>/ in the path.
    const pathExpire = url.pathname.match(/\/expire\/(\d{9,})(?:\/|$)/);
    const expiresAtSeconds = Number(url.searchParams.get('expire') || (pathExpire ? pathExpire[1] : NaN));
    if (!Number.isFinite(expiresAtSeconds) || expiresAtSeconds <= 0) {
      return STREAM_CACHE_FALLBACK_TTL_MS;
    }
    const safeTtl = expiresAtSeconds * 1000 - nowMs - STREAM_EXPIRY_SAFETY_MS;
    return Math.max(0, Math.min(safeTtl, STREAM_CACHE_MAX_TTL_MS));
  } catch {
    return STREAM_CACHE_FALLBACK_TTL_MS;
  }
}

// ------------------------------------------------------------------ live streams
// A live broadcast (a TV channel, a 24/7 radio, an event) has no audio file to download:
// YouTube serves it as an HLS playlist, which FFmpeg plays directly.

const VIDEO_ID = /^[A-Za-z0-9_-]{11}$/;

// /@handle/live, /channel/UC.../live, /c/name/live, /user/name/live: "the live stream of this
// channel right now". (/live/<video id> is a normal link to one broadcast.)
const CHANNEL_LIVE_URL = /^https?:\/\/(?:www\.|m\.)?youtube\.com\/(?:@[^/?#]+|channel\/UC[\w-]{22}|c\/[^/?#]+|user\/[^/?#]+)\/live\/?(?:[?#].*)?$/i;

export function isChannelLiveUrl(input) {
  return typeof input === 'string' && CHANNEL_LIVE_URL.test(input.trim());
}

export function isVideoId(value) {
  return typeof value === 'string' && VIDEO_ID.test(value);
}

// What the player response says about a broadcast: { live, hlsUrl }. A finished broadcast
// (is_live_content but no manifest) is an ordinary recording and is not "live".
export function liveStreamInfo(info) {
  const basic = info?.basic_info || {};
  const streaming = info?.streaming_data || {};
  const hlsUrl = typeof streaming.hls_manifest_url === 'string' ? streaming.hls_manifest_url : '';
  const hasFiles = (streaming.adaptive_formats?.length || 0) + (streaming.formats?.length || 0) > 0;
  const live = Boolean(basic.is_live) || Boolean(basic.is_live_content && hlsUrl && !hasFiles);
  return { live, hlsUrl };
}

// The variants of an HLS master playlist: [{ url, bandwidth, hasAudio, audioOnly }].
export function parseHlsMaster(text, baseUrl) {
  const variants = [];
  const lines = String(text || '').split(/\r?\n/);
  for (let index = 0; index < lines.length; index += 1) {
    const line = lines[index].trim();
    if (!line.startsWith('#EXT-X-STREAM-INF:')) continue;
    let target = '';
    for (let next = index + 1; next < lines.length; next += 1) {
      const candidate = lines[next].trim();
      if (!candidate) continue;
      if (!candidate.startsWith('#')) target = candidate;
      break;
    }
    if (!target) continue;
    let url;
    try {
      url = new URL(target, baseUrl).toString();
    } catch {
      continue;
    }
    const bandwidth = Number(line.match(/(?:^|[:,])BANDWIDTH=(\d+)/)?.[1] || 0);
    const codecs = line.match(/CODECS="([^"]*)"/)?.[1] || '';
    const hasVideo = /RESOLUTION=/.test(line) || /(?:avc1|hvc1|hev1|vp0?9|av01)/i.test(codecs);
    const hasAudio = !codecs || /(?:mp4a|ac-3|ec-3|opus)/i.test(codecs);
    variants.push({ url, bandwidth, hasAudio, audioOnly: hasAudio && !hasVideo });
  }
  return variants;
}

// The variant that costs the least to listen to: an audio-only one when there is one, else the
// lowest bit rate that still carries sound (FFmpeg would otherwise pick a big video variant).
export function pickHlsVariant(variants) {
  const withSound = (variants || []).filter((variant) => variant.hasAudio);
  if (withSound.length === 0) return null;
  const rate = (variant) => (variant.bandwidth > 0 ? variant.bandwidth : Number.MAX_SAFE_INTEGER);
  const audioOnly = withSound.filter((variant) => variant.audioOnly);
  const pool = audioOnly.length > 0 ? audioOnly : withSound;
  return [...pool].sort((a, b) => rate(a) - rate(b))[0];
}

// Does the search text ask for a broadcast ("kompas tv live", "siaran langsung ...", "24/7")?
export function wantsLive(query) {
  return /(?:^|[^\p{L}\p{N}])(?:live|livestream|live\s+stream|siaran\s+langsung|langsung|24\s*\/\s*7)(?:$|[^\p{L}\p{N}])/iu.test(String(query || ''));
}

// A search result that is on air right now (the badge or the time overlay says LIVE).
export function isLiveRenderer(renderer) {
  const badges = renderer?.badges || [];
  if (badges.some((badge) => badge?.metadataBadgeRenderer?.style === 'BADGE_STYLE_TYPE_LIVE_NOW')) return true;
  const overlays = renderer?.thumbnailOverlays || [];
  return overlays.some((overlay) => overlay?.thumbnailOverlayTimeStatusRenderer?.style === 'LIVE');
}

// When the person asks for a live stream, broadcasts that are on air come first (the order
// inside each group is kept).
export function preferLiveEntries(entries, query) {
  if (!Array.isArray(entries) || !wantsLive(query) || !entries.some((entry) => entry.is_live)) return entries;
  return [...entries.filter((entry) => entry.is_live), ...entries.filter((entry) => !entry.is_live)];
}
