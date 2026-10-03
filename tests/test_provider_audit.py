"""Offline checks for evidence grading and secret-safe serialization."""
import unittest
from scripts.provider_audit import candidate, safe_url, serial_row
from scripts.provider_audit_corpus import build
from scripts.provider_audit_report import score


class AuditEvidenceTests(unittest.TestCase):
    def test_manifest_covers_each_provider_and_negative_controls(self):
        cases=build()["cases"]
        self.assertEqual(len(cases),352)
        self.assertEqual(len({c["id"] for c in cases}),352)
        for slug in {c["provider"] for c in cases}:
            sample=[c for c in cases if c["provider"]==slug]
            self.assertEqual(len(sample),32)
            negative=next(c for c in sample if c["scenario"]=="negative_control")
            self.assertEqual(candidate({"name":negative["query"]},negative),(False,False))

    def test_known_saki_collisions_and_sequels_are_not_target_candidates(self):
        case=next(c for c in build()["cases"] if c["id"]=="anime-01")
        self.assertTrue(candidate({"name":"[Nozomi] Saki (720p Complete BD)"},case)[0])
        for title in ["Saki Achiga-hen 01", "Tenkou-saki no Seiso Karen", "Koko wa Ore ni Makasete Saki ni Ike"]:
            self.assertFalse(candidate({"name":title},case)[0])

    def test_listing_urls_discard_userinfo_credentials_and_fragments(self):
        self.assertEqual(safe_url("https://u:secret@example.com/view?t=42&token=secret#private"),
                         "https://example.com/view?t=42")
        self.assertEqual(safe_url("magnet:?xt=urn:btih:abc"),"")
        row=serial_row({"name":"x","cookie":"secret","password":"secret","handle":{"token":"secret"}})
        self.assertNotIn("secret",str(row))

    def test_unavailable_cells_remain_unknown_after_rescoring(self):
        case=build()["cases"][0]
        record={"measurement":"not_run","candidate_count":None,"status":"unknown_circuit_open"}
        self.assertEqual(score(record,case),record)

    def test_title_and_requested_variant_have_separate_counts(self):
        case={"aliases":["Saki"],"variant_tokens":"720p"}
        self.assertEqual(candidate({"name":"Saki 1080p"},case),(True,False))
        self.assertEqual(candidate({"name":"Saki 720p"},case),(True,True))

    def test_apostrophe_spelling_is_not_a_false_title_miss(self):
        self.assertTrue(candidate({"name":"Baldurs Gate 3"},{"aliases":["Baldur’s Gate 3"]})[0])


if __name__ == "__main__":
    unittest.main()
