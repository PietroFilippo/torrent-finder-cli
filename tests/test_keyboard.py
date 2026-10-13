"""The Windows key decoder: "à" is a letter, special keys keep readchar's strings."""

import sys
import unittest
from unittest.mock import patch

import readchar

import isolation  # noqa: F401  # redirected settings and the shared test baseline
from torrent_finder.ui import keyboard

CTRL, ALT, SHIFT = 0x0008, 0x0002, 0x0010


class SpecialCodeTests(unittest.TestCase):
    def test_navigation_keys_match_readchars_windows_names(self):
        for vk, name in ((0x26, "UP"), (0x28, "DOWN"), (0x25, "LEFT"), (0x27, "RIGHT"), (0x24, "HOME"),
                         (0x23, "END"), (0x21, "PAGE_UP"), (0x22, "PAGE_DOWN"), (0x2E, "DELETE"), (0x2D, "INSERT")):
            with self.subTest(name=name):
                self.assertEqual("\x00" + keyboard.special_code(vk, 0), _windows_key(name))

    def test_shift_leaves_navigation_alone_and_ctrl_or_alt_change_it_as_getwch_does(self):
        self.assertEqual(keyboard.special_code(0x26, SHIFT), "\x48")
        self.assertEqual(keyboard.special_code(0x25, CTRL), "\x73")
        self.assertEqual(keyboard.special_code(0x26, ALT), "\x98")

    def test_function_keys(self):
        self.assertEqual("\x00" + keyboard.special_code(0x70, 0), _windows_key("F1"))
        self.assertEqual("\x00" + keyboard.special_code(0x79, 0), _windows_key("F10"))
        self.assertEqual("\x00" + keyboard.special_code(0x7B, 0), _windows_key("F12"))
        self.assertEqual(keyboard.special_code(0x70, SHIFT), "\x54")

    def test_modifier_keys_alone_are_not_keys(self):
        for vk in (0x10, 0x11, 0x12, 0x14):  # Shift, Ctrl, Alt, Caps Lock
            self.assertIsNone(keyboard.special_code(vk, 0))


class ReadkeyTests(unittest.TestCase):
    def read(self, *events):
        with patch.object(keyboard, "_open_console", return_value=True), \
             patch.object(keyboard, "read_key_event", side_effect=list(events)):
            return keyboard.readkey()

    def test_a_typed_a_grave_is_the_letter(self):
        # getwch returns the same "\xe0" for "à" and for an arrow's prefix; readchar then ate the next key.
        self.assertEqual(self.read(("à", None)), "à")

    def test_special_keys_keep_readchars_strings(self):
        self.assertEqual(self.read(("", "\x48")), "\x00\x48")

    def test_ctrl_c_interrupts(self):
        with self.assertRaises(KeyboardInterrupt):
            self.read(("\x03", None))

    def test_a_character_beyond_the_basic_plane_arrives_whole(self):
        self.assertEqual(self.read(("\ud83d", None), ("\ude00", None)), "\U0001F600")

    def test_without_a_console_readchar_reads(self):
        with patch.object(keyboard, "_open_console", return_value=False), \
             patch.object(keyboard, "_original", return_value="x") as original:
            self.assertEqual(keyboard.readkey(), "x")
        original.assert_called_once()


class InstallTests(unittest.TestCase):
    def setUp(self):
        self.addCleanup(setattr, readchar, "readkey", readchar.readkey)

    def test_windows_reads_through_the_decoder(self):
        with patch.object(keyboard.sys, "platform", "win32"), patch.object(readchar, "readkey", keyboard._original):
            keyboard.install()
            self.assertIs(readchar.readkey, keyboard.readkey)

    def test_other_systems_keep_readchar(self):
        with patch.object(keyboard.sys, "platform", "linux"), patch.object(readchar, "readkey", keyboard._original):
            keyboard.install()
            self.assertIs(readchar.readkey, keyboard._original)

    def test_a_patched_readkey_is_left_alone(self):
        sentinel = lambda: "k"  # noqa: E731  # what a test's patch looks like
        with patch.object(keyboard.sys, "platform", "win32"), patch.object(readchar, "readkey", sentinel):
            keyboard.install()
            self.assertIs(readchar.readkey, sentinel)


# getwch's strings for special keys, under readchar's Windows names (readchar.key is
# that module only on Windows; its private module isn't imported on other systems).
_WINDOWS_KEYS = {
    "UP": "\x00\x48", "DOWN": "\x00\x50", "LEFT": "\x00\x4b", "RIGHT": "\x00\x4d",
    "HOME": "\x00\x47", "END": "\x00\x4f", "PAGE_UP": "\x00\x49", "PAGE_DOWN": "\x00\x51",
    "DELETE": "\x00\x53", "INSERT": "\x00\x52", "F1": "\x00\x3b", "F10": "\x00\x44", "F12": "\x00\x86",
}


def _windows_key(name):
    return _WINDOWS_KEYS[name]


class ReadcharAgreementTests(unittest.TestCase):
    @unittest.skipUnless(sys.platform == "win32", "readchar.key holds the Windows codes only on Windows")
    def test_the_codes_are_readchars_own(self):
        for name, code in _WINDOWS_KEYS.items():
            with self.subTest(name=name):
                self.assertEqual(getattr(readchar.key, name), code)


if __name__ == "__main__":
    unittest.main()
