import assert from 'node:assert/strict';
import test from 'node:test';

import {
  isChannelLiveUrl,
  isLiveRenderer,
  isVideoId,
  liveStreamInfo,
  musicItemPayload,
  normalizeSearchKey,
  parseHlsMaster,
  pickHlsVariant,
  preferLiveEntries,
  streamCacheTtlMs,
  wantsLive
} from '../media.mjs';

test('normalizes equivalent search queries per mode', () => {
  assert.equal(normalizeSearchKey('music', '  Ela   VEM  '), 'music:ela vem');
  assert.equal(normalizeSearchKey('video', 'Ela Vem'), 'video:ela vem');
});

test('maps YouTube Music search items to the bridge contract', () => {
  const payload = musicItemPayload({
    id: 'J0pZqX0ITxg',
    title: 'Ela Vem',
    artists: [{ name: 'Mc G15' }, { name: 'Mc Livinho' }],
    duration: { seconds: 197 }
  });

  assert.deepEqual(payload, {
    id: 'J0pZqX0ITxg',
    videoId: 'J0pZqX0ITxg',
    title: 'Ela Vem',
    uploader: 'Mc G15, Mc Livinho',
    artists: [{ name: 'Mc G15' }, { name: 'Mc Livinho' }],
    duration: 197,
    webpage_url: 'https://www.youtube.com/watch?v=J0pZqX0ITxg'
  });
});

test('maps Up Next items using their video_id and author', () => {
  const payload = musicItemPayload({
    video_id: '48Lrud3Bxpc',
    title: { toString: () => 'Ela Vem (SET DJ NENE)' },
    author: 'Mc Kevin',
    duration: { seconds: 288 }
  });

  assert.equal(payload.videoId, '48Lrud3Bxpc');
  assert.equal(payload.title, 'Ela Vem (SET DJ NENE)');
  assert.equal(payload.uploader, 'Mc Kevin');
});

test('derives stream cache TTL from URL expiry with safety margin and cap', () => {
  const nowMs = 1_800_000_000_000;
  const expiresAt = Math.floor(nowMs / 1000) + 1_800;
  const url = `https://example.test/audio?expire=${expiresAt}`;

  assert.equal(streamCacheTtlMs(url, nowMs), 1_680_000);
});

test('caps long stream validity and rejects already unsafe URLs', () => {
  const nowMs = 1_800_000_000_000;
  const farExpiry = Math.floor(nowMs / 1000) + 10_000;
  const nearExpiry = Math.floor(nowMs / 1000) + 60;

  assert.equal(streamCacheTtlMs(`https://x.test/?expire=${farExpiry}`, nowMs), 3_600_000);
  assert.equal(streamCacheTtlMs(`https://x.test/?expire=${nearExpiry}`, nowMs), 0);
  assert.equal(streamCacheTtlMs('https://x.test/no-expiry', nowMs), 300_000);
});

// ------------------------------------------------------------------ live streams

const MASTER = [
  '#EXTM3U',
  '#EXT-X-INDEPENDENT-SEGMENTS',
  '#EXT-X-STREAM-INF:BANDWIDTH=2400000,CODECS="avc1.4d401f,mp4a.40.2",RESOLUTION=1280x720,FRAME-RATE=30',
  'https://manifest.googlevideo.com/api/manifest/hls_playlist/expire/1900000000/itag/95/index.m3u8',
  '#EXT-X-STREAM-INF:BANDWIDTH=290000,CODECS="avc1.4d400c,mp4a.40.5",RESOLUTION=256x144,FRAME-RATE=30',
  'https://manifest.googlevideo.com/api/manifest/hls_playlist/expire/1900000000/itag/91/index.m3u8',
  '#EXT-X-STREAM-INF:BANDWIDTH=680000,CODECS="avc1.4d4015,mp4a.40.5",RESOLUTION=426x240,FRAME-RATE=30',
  'https://manifest.googlevideo.com/api/manifest/hls_playlist/expire/1900000000/itag/92/index.m3u8',
  ''
].join('\n');

test('parses the variants of an HLS master playlist', () => {
  const variants = parseHlsMaster(MASTER, 'https://manifest.googlevideo.com/master.m3u8');
  assert.equal(variants.length, 3);
  assert.equal(variants[0].bandwidth, 2400000);
  assert.ok(variants.every((variant) => variant.hasAudio && !variant.audioOnly));
  assert.match(variants[1].url, /itag\/91\/index\.m3u8$/);
});

test('picks the cheapest variant that still has sound', () => {
  const picked = pickHlsVariant(parseHlsMaster(MASTER, 'https://x.example/m.m3u8'));
  assert.equal(picked.bandwidth, 290000);
  assert.match(picked.url, /itag\/91\//);
});

test('prefers an audio-only variant when the playlist has one', () => {
  const text = [
    '#EXTM3U',
    '#EXT-X-STREAM-INF:BANDWIDTH=140000,CODECS="mp4a.40.2"',
    'audio.m3u8',
    '#EXT-X-STREAM-INF:BANDWIDTH=90000,CODECS="avc1.4d400c",RESOLUTION=256x144',
    'video-only.m3u8',
    '#EXT-X-STREAM-INF:BANDWIDTH=290000,CODECS="avc1.4d400c,mp4a.40.5",RESOLUTION=256x144',
    'muxed.m3u8'
  ].join('\n');
  const variants = parseHlsMaster(text, 'https://x.example/dir/master.m3u8');
  const picked = pickHlsVariant(variants);
  assert.equal(picked.url, 'https://x.example/dir/audio.m3u8');
  assert.equal(variants[1].hasAudio, false, 'a video-only variant has no sound');
  assert.equal(variants[2].audioOnly, false);
  assert.equal(pickHlsVariant([]), null);
  assert.equal(pickHlsVariant(null), null);
});

test('ignores broken playlists', () => {
  assert.deepEqual(parseHlsMaster('', 'https://x.example/'), []);
  assert.deepEqual(parseHlsMaster('#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=1\n', 'https://x.example/'), []);
  assert.equal(pickHlsVariant([{ url: 'v', bandwidth: 1, hasAudio: false, audioOnly: false }]), null);
});

test('tells a running broadcast from a recording', () => {
  const hls = 'https://manifest.googlevideo.com/api/manifest/hls_variant/expire/1900000000/x/index.m3u8';
  assert.deepEqual(liveStreamInfo({ basic_info: { is_live: true }, streaming_data: { hls_manifest_url: hls } }), { live: true, hlsUrl: hls });
  assert.equal(liveStreamInfo({ basic_info: { is_live: true }, streaming_data: {} }).live, true);
  assert.equal(liveStreamInfo({ basic_info: { is_live: false, is_live_content: true }, streaming_data: { adaptive_formats: [{}] } }).live, false);
  assert.equal(liveStreamInfo({ basic_info: { is_live_content: true }, streaming_data: { hls_manifest_url: hls } }).live, true);
  assert.deepEqual(liveStreamInfo({}), { live: false, hlsUrl: '' });
});

test('recognizes the live page of a channel', () => {
  for (const url of [
    'https://www.youtube.com/@KompasTV/live',
    'https://youtube.com/@KompasTV/live/',
    'https://m.youtube.com/channel/UCabcdefghijklmnopqrstuv/live',
    'https://www.youtube.com/c/SomeName/live?feature=share',
    'https://www.youtube.com/user/somebody/live'
  ]) {
    assert.equal(isChannelLiveUrl(url), true, url);
  }
  for (const url of [
    'https://www.youtube.com/live/dQw4w9WgXcQ',
    'https://www.youtube.com/@KompasTV',
    'https://www.youtube.com/@KompasTV/videos',
    'https://www.youtube.com/watch?v=dQw4w9WgXcQ',
    'https://example.com/@x/live',
    '', null, undefined
  ]) {
    assert.equal(isChannelLiveUrl(url), false, String(url));
  }
  assert.equal(isVideoId('dQw4w9WgXcQ'), true);
  assert.equal(isVideoId('short'), false);
});

test('detects what asks for a broadcast in a search text', () => {
  for (const query of ['kompas tv live', 'LIVE kompas', 'siaran langsung metro tv', 'lofi 24/7', 'lofi 24 / 7', 'tv live streaming']) {
    assert.equal(wantsLive(query), true, query);
  }
  for (const query of ['alive', 'deliver me', 'olive tree', 'kompas tv', 'Ela Vem', '', null]) {
    assert.equal(wantsLive(query), false, String(query));
  }
});

test('finds live results in the raw search result', () => {
  assert.equal(isLiveRenderer({ badges: [{ metadataBadgeRenderer: { style: 'BADGE_STYLE_TYPE_LIVE_NOW', label: 'LIVE' } }] }), true);
  assert.equal(isLiveRenderer({ thumbnailOverlays: [{ thumbnailOverlayTimeStatusRenderer: { style: 'LIVE' } }] }), true);
  assert.equal(isLiveRenderer({ thumbnailOverlays: [{ thumbnailOverlayTimeStatusRenderer: { style: 'DEFAULT' } }] }), false);
  assert.equal(isLiveRenderer({}), false);
  assert.equal(isLiveRenderer(null), false);
});

test('puts broadcasts first only when a live stream was asked for', () => {
  const entries = [
    { id: 'a', is_live: false },
    { id: 'b', is_live: true },
    { id: 'c', is_live: false },
    { id: 'd', is_live: true }
  ];
  assert.deepEqual(preferLiveEntries(entries, 'kompas tv live').map((entry) => entry.id), ['b', 'd', 'a', 'c']);
  assert.deepEqual(preferLiveEntries(entries, 'kompas tv').map((entry) => entry.id), ['a', 'b', 'c', 'd']);
  assert.deepEqual(preferLiveEntries([{ id: 'a' }], 'x live').map((entry) => entry.id), ['a']);
});

test('cache lifetime follows the expiry in the path of an HLS link', () => {
  const now = 1_900_000_000_000 - 10 * 60 * 1000;
  const ttl = streamCacheTtlMs('https://manifest.googlevideo.com/api/manifest/hls_playlist/expire/1900000000/itag/91/index.m3u8', now);
  assert.equal(ttl, 8 * 60 * 1000);
  assert.equal(streamCacheTtlMs('https://manifest.googlevideo.com/api/manifest/hls_playlist/itag/91/index.m3u8', now), 5 * 60 * 1000);
});
