from unittest import TestCase

from bot.services.result_filter import looks_like_collection, pick_single_track_index


class ResultFilterTests(TestCase):
    def test_detects_multi_song_uploads(self):
        for title in (
            "FATAMORGANA - LAILA AYU - SIMPATIK MUSIK FULL ALBUM TERBARU 2026",
            "Dangdut Koplo Non Stop 2026",
            "nonstop lagu galau",
            "Best songs playlist",
            "1 Hour of Relaxing Music",
            "2 jam lagu santai",
            "Megamix 2026",
        ):
            self.assertTrue(looks_like_collection(title), title)

    def test_single_songs_are_not_collections(self):
        for title in (
            "Sweet but Psycho - Ava Max",
            "Teman Biasa - Tiara Amora - SIMPATIK MUSIC",
            "Mahalini - Sial (Official Lyric Video)",
            "Hour of Need",  # "hour" without a number is a normal word
            "",
        ):
            self.assertFalse(looks_like_collection(title), title)

    def test_first_real_song_wins(self):
        titles = ["Fatamorgana FULL ALBUM", "Non Stop Hits", "Fatamorgana - Laila Ayu"]
        self.assertEqual(pick_single_track_index("vata morgana", titles), 2)

    def test_query_asking_for_an_album_keeps_the_top_result(self):
        self.assertEqual(pick_single_track_index("laila ayu full album", ["X Full Album", "Y"]), 0)

    def test_all_collections_fall_back_to_the_top_result(self):
        self.assertEqual(pick_single_track_index("x", ["A full album", "B non stop"]), 0)

    def test_empty_results(self):
        self.assertEqual(pick_single_track_index("x", []), 0)
