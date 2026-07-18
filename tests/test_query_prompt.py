import io
import unittest
import warnings
from contextlib import redirect_stdout
from unittest.mock import patch

warnings.filterwarnings("ignore", module=".*requests.*")
warnings.filterwarnings("ignore", message=".*urllib3.*")

import readchar

from torrent_finder.ui import prompts

_ESC = readchar.key.ESC
_ENTER = readchar.key.ENTER
_CTRL_N = readchar.key.CTRL_N


def _run(keys, **kwargs):
    """Drive get_query_with_shortcut with a scripted key sequence."""
    seq = iter(keys)
    with patch.object(prompts.readchar, "readkey", side_effect=lambda: next(seq)):
        with redirect_stdout(io.StringIO()):
            return prompts.get_query_with_shortcut("prompt: ", **kwargs)


class MultiEscBackoutTests(unittest.TestCase):
    def test_esc_leaves_immediately_in_single_mode(self):
        self.assertEqual(_run(["a", "b", _ESC]), "GO_BACK")

    def test_esc_clears_the_line_being_typed(self):
        # Esc wipes "c", second title becomes "d".
        result = _run(
            ["a", "b", _CTRL_N, "c", _ESC, "d", _ENTER], multi=True
        )
        self.assertEqual(result, ["ab", "d"])

    def test_esc_restores_last_committed_title_for_editing(self):
        # Commit "ab", clear the empty line's Esc pops "ab" back; typing
        # appends to it.
        result = _run(["a", "b", _CTRL_N, _ESC, "c", _ENTER], multi=True)
        self.assertEqual(result, ["abc"])

    def test_esc_backs_all_the_way_out_only_when_empty(self):
        # ab committed, c typed: Esc (clear c), Esc (pop ab), Esc (clear ab),
        # Esc (now empty -> leave).
        result = _run(
            ["a", "b", _CTRL_N, "c", _ESC, _ESC, _ESC, _ESC], multi=True
        )
        self.assertEqual(result, "GO_BACK")

    def test_empty_multi_prompt_esc_leaves_immediately(self):
        self.assertEqual(_run([_ESC], multi=True), "GO_BACK")

    def test_enter_still_returns_committed_titles(self):
        result = _run(["a", _CTRL_N, "b", _ENTER], multi=True)
        self.assertEqual(result, ["a", "b"])


if __name__ == "__main__":
    unittest.main()
