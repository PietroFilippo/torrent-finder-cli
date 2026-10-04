"""Mobile searches Knaben first, ranks the app itself first, and can add F-Droid's
official open-source apps with their exact package identity (P06).

F-Droid fixtures copy its live October 2026 API answers for Organic Maps.
"""

import os
import tempfile
import threading
import unittest
from contextlib import ExitStack
from unittest.mock import Mock, patch

import isolation  # noqa: F401  (keeps the user's settings out of reach)
from torrent_finder import acquisition, fdroid
from torrent_finder.providers.mobile_provider import MobileProvider
from torrent_finder.providers.software_provider import SoftwareProvider
from torrent_finder.result_view import product_title_score
from torrent_finder.search_result import SearchResult
from torrent_finder.search_session import search_many

ORGANIC_MAPS = {"name": "Organic Maps・Offline Map & GPS",
                "summary": "Get reliable offline maps with GPS navigation.",
                "url": "https://f-droid.org/en/packages/app.organicmaps"}


def response(payload=None, *, url="", chunks=(), status=200):
    resp = Mock(status_code=status, url=url, headers={"Content-Length": str(sum(map(len, chunks)))})
    resp.json.return_value = payload
    resp.iter_content.return_value = list(chunks)
    resp.__enter__ = Mock(return_value=resp)
    resp.__exit__ = Mock(return_value=False)
    return resp


class FDroidClientTests(unittest.TestCase):
    def test_search_rows_carry_the_exact_package(self):
        apps = [ORGANIC_MAPS,
                {"name": "Broken", "url": "https://f-droid.org/en/packages/not a package"},
                {"name": "VLC", "url": "https://f-droid.org/en/packages/org.videolan.vlc"}]
        with patch.object(fdroid.requests, "get", return_value=response({"apps": apps})) as get:
            rows = fdroid.search("Organic Maps")
        self.assertEqual(get.call_args.kwargs["params"], {"q": "Organic Maps", "lang": "en"})
        self.assertEqual([r.name for r in rows], ["Organic Maps・Offline Map & GPS [app.organicmaps]",
                                                  "VLC [org.videolan.vlc]"])
        first = rows[0]
        self.assertEqual((first.info_hash, first["fd_package"], first["fd_app"], first.source),
                         ("fdroid:app.organicmaps", "app.organicmaps", "Organic Maps", "F-Droid"))
        self.assertEqual(first.page_url, "https://f-droid.org/en/packages/app.organicmaps/")

    def test_a_malformed_answer_is_no_rows(self):
        with patch.object(fdroid.requests, "get", return_value=response({"error": "x"})):
            self.assertEqual(fdroid.search("Anything"), [])

    def test_suggested_version_comes_from_the_package_api(self):
        api = {"packageName": "app.organicmaps", "suggestedVersionCode": 26092932,
               "packages": [{"versionName": "2026.09.29-32-FDroid", "versionCode": 26092932},
                            {"versionName": "2026.08.27-18-FDroid", "versionCode": 26082718}]}
        with patch.object(fdroid.requests, "get", return_value=response(api)) as get:
            self.assertEqual(fdroid.suggested_apk("app.organicmaps"),
                             ("https://f-droid.org/repo/app.organicmaps_26092932.apk", "2026.09.29-32-FDroid", 1))
        self.assertEqual(get.call_args.args[0], "https://f-droid.org/api/v1/packages/app.organicmaps")
        for bad in ({"suggestedVersionCode": "26092932"}, {"suggestedVersionCode": True}, {}):
            with patch.object(fdroid.requests, "get", return_value=response(bad)):
                self.assertIsNone(fdroid.suggested_apk("app.organicmaps"))
        with patch.object(fdroid.requests, "get") as get:
            self.assertIsNone(fdroid.suggested_apk("../../etc"))
        get.assert_not_called()

    def test_builds_per_cpu_type_are_counted(self):
        api = {"suggestedVersionCode": 13070108, "packages": [
            {"versionName": "3.7.1", "versionCode": code} for code in (13070105, 13070106, 13070107, 13070108)]}
        with patch.object(fdroid.requests, "get", return_value=response(api)):
            self.assertEqual(fdroid.suggested_apk("org.videolan.vlc")[2], 4)

    def test_apks_come_only_from_the_official_repository(self):
        url = "https://f-droid.org/repo/org.example.app_7.apk"
        with tempfile.TemporaryDirectory() as folder:
            with patch.object(fdroid.requests, "get") as get:
                self.assertIsNone(fdroid.download_apk("https://example.com/repo/org.example.app_7.apk", folder))
            get.assert_not_called()
            moved = response(url="https://mirror.example/org.example.app_7.apk", chunks=[b"PK"])
            with patch.object(fdroid.requests, "get", return_value=moved):
                self.assertIsNone(fdroid.download_apk(url, folder))
            self.assertEqual(os.listdir(folder), [])
            good = response(url=url, chunks=[b"PK\x03\x04", b"rest"])
            with patch.object(fdroid.requests, "get", return_value=good):
                path = fdroid.download_apk(url, folder)
            self.assertEqual(os.path.basename(path), "org.example.app_7.apk")
            with open(path, "rb") as fh:
                self.assertEqual(fh.read(), b"PK\x03\x04rest")


def row(name, seeders=1, source="Knaben", n=[0]):
    n[0] += 1
    return SearchResult(name=name, info_hash=f"{n[0]:040x}", seeders=seeders, source=source)


def search(query, knaben=None, apibay=None, fdroid_rows=None, fdroid_on=False):
    calls = []

    def engine(name, rows):
        def run(_self, q):
            calls.append((name, q))
            return list((rows or {}).get(q, []))
        return run

    provider = MobileProvider()
    if fdroid_on:
        next(e for e in provider.engines if e.name == "F-Droid").set_mode("on")
    with ExitStack() as stack:
        stack.enter_context(patch.object(MobileProvider, "_search_knaben", engine("Knaben", knaben)))
        stack.enter_context(patch.object(MobileProvider, "_search_apibay", engine("Apibay", apibay)))
        stack.enter_context(patch.object(fdroid, "search", lambda q: calls.append(("F-Droid", q))
                                         or list((fdroid_rows or {}).get(q, []))))
        return search_many(provider, [query]), calls


class MobileSearchTests(unittest.TestCase):
    def test_knaben_first_with_apibay_as_fallback_and_f_droid_off(self):
        modes = {e.name: e.mode for e in MobileProvider().engines}
        self.assertEqual(modes, {"Knaben": "on", "Apibay": "auto", "SolidTorrents": "off", "F-Droid": "off"})
        _, calls = search("Minecraft", knaben={"Minecraft": [row("[Android] Minecraft 1.21.72")]})
        self.assertEqual(calls, [("Knaben", "Minecraft")])

    def test_apibay_also_runs_when_knaben_rows_are_other_apps(self):
        knaben = {"Minecraft": [row("[Android] Pixel Gun 3D (Pocket Minecraft Edition) v8.3.1")]}
        _, calls = search("Minecraft", knaben=knaben)
        self.assertIn(("Apibay", "Minecraft"), calls)

    def test_the_app_itself_ranks_above_look_alikes_and_add_ons(self):
        knaben = {"Minecraft": [row("[Android] Pixel Gun 3D (Pocket Minecraft Edition) v8.3.1", 900),
                                row("Lucky Block Mod for Minecraft v1.0 Android .APK", 500),
                                row("[Android] Minecraft 1.21.72.01 [RUS]", 20)]}
        results, _ = search("Minecraft", knaben=knaben)
        self.assertEqual(results[0].name, "[Android] Minecraft 1.21.72.01 [RUS]")

    def test_f_droid_rows_are_matched_on_the_app_name(self):
        app = fdroid_row = SearchResult(name="Organic Maps・Offline Map & GPS [app.organicmaps]",
                                        info_hash="fdroid:app.organicmaps", source="F-Droid",
                                        handle={"fd_package": "app.organicmaps"}, extra={"fd_app": "Organic Maps"})
        other = SearchResult(name="GeoShare: Jump Between Maps [page.ooooo.geoshare]", info_hash="fdroid:page.ooooo.geoshare",
                             source="F-Droid", handle={"fd_package": "page.ooooo.geoshare"},
                             extra={"fd_app": "GeoShare"})
        results, calls = search("Organic Maps apk", fdroid_rows={"Organic Maps": [other, fdroid_row]}, fdroid_on=True)
        # One F-Droid request, for the name alone: release tags mean nothing there.
        self.assertEqual([call for call in calls if call[0] == "F-Droid"], [("F-Droid", "Organic Maps")])
        self.assertEqual(results[0]["fd_package"], app["fd_package"])
        # The app name without its tagline is the product: an exact match.
        tagged = SearchResult(name="Organic Maps・Hike, Bike, Drive [app.organicmaps]", info_hash="fdroid:x",
                              source="F-Droid", extra={"fd_app": "Organic Maps"})
        self.assertEqual(MobileProvider().title_relevance(tagged, "Organic Maps"), 3)
        self.assertIs(acquisition.for_result(results[0]).__class__, acquisition.FDroidAcquisition)

    def test_a_typed_tag_searches_the_name_and_lists_tagged_releases_first(self):
        knaben = {"Minecraft": [row("[Android] Minecraft 1.21.72", 900), row("Minecraft PE 1.21 + OBB", 5)]}
        results, calls = search("Minecraft obb", knaben=knaben)
        self.assertIn(("Knaben", "Minecraft"), calls)
        self.assertEqual(results[0].name, "Minecraft PE 1.21 + OBB")

    def test_platform_exclusions_match_whole_words(self):
        mobile, desktop = MobileProvider(), SoftwareProvider()
        kept, _ = mobile.filter_with_reasons([row("Kiosk Browser Lockdown v2 APK"), row("Minecraft iOS IPA")])
        self.assertEqual([r.name for r in kept], ["Kiosk Browser Lockdown v2 APK"])
        kept, _ = desktop.filter_with_reasons([row("ASUS BIOS Flash Utility 3.2"), row("Photoshop Express APK")])
        self.assertEqual([r.name for r in kept], ["ASUS BIOS Flash Utility 3.2"])

    def test_addons_and_bracketed_mentions_are_other_products(self):
        self.assertEqual(product_title_score("Actions for Photoshop pack", "Photoshop"), 1)
        self.assertEqual(product_title_score("(MAC) Adobe Photoshop CC 2019", "Photoshop"), 3)


class FDroidBatchTests(unittest.TestCase):
    def test_batch_download_saves_the_suggested_apk(self):
        result = SearchResult(name="VLC [org.videolan.vlc]", info_hash="fdroid:org.videolan.vlc", source="F-Droid",
                              page_url="https://f-droid.org/en/packages/org.videolan.vlc/",
                              handle={"fd_package": "org.videolan.vlc"})
        url = "https://f-droid.org/repo/org.videolan.vlc_13060407.apk"
        with patch.object(fdroid, "suggested_apk", return_value=(url, "3.6.4", 4)), \
             patch.object(fdroid, "download_apk", return_value="C:/x/org.videolan.vlc_13060407.apk") as download:
            outcome = acquisition.for_result(result).batch_item(
                result, download_dir="C:/x", cancel_event=threading.Event(), set_status=lambda _: None)
        self.assertTrue(outcome.ok)
        self.assertEqual(download.call_args.args[:2], (url, "C:/x"))
        with patch.object(fdroid, "suggested_apk", return_value=None):
            outcome = acquisition.for_result(result).batch_item(
                result, download_dir="C:/x", cancel_event=threading.Event(), set_status=lambda _: None)
        self.assertEqual((outcome.ok, outcome.manual_url), (False, result.page_url))


if __name__ == "__main__":
    unittest.main()
