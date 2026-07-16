import os
import tempfile
import unittest
from unittest.mock import patch

from torrent_finder import launcher_alias


class LauncherRenderingTests(unittest.TestCase):
    def test_command_choices_are_fixed_presets(self):
        self.assertEqual(
            launcher_alias.COMMAND_CHOICES,
            ("torrent-finder", "tf", "torrent", "find-torrent", "tfind"),
        )

    def test_windows_launcher_forwards_all_arguments_from_source_checkout(self):
        target = launcher_alias.LaunchTarget(
            argv=(r"C:\Python\python.exe", "-m", "torrent_finder"),
            cwd=r"C:\src\torrent-finder",
        )

        rendered = launcher_alias._render_launcher(target, platform="win32")

        self.assertIn(launcher_alias.MANAGED_MARKER, rendered)
        self.assertIn('pushd "C:\\src\\torrent-finder"', rendered)
        self.assertIn('"C:\\Python\\python.exe" -m torrent_finder %*', rendered)
        self.assertIn("exit /b %_TF_EXIT%", rendered)

    def test_posix_launcher_forwards_all_arguments(self):
        target = launcher_alias.LaunchTarget(
            argv=("/usr/bin/python3", "-m", "torrent_finder"),
            cwd="/home/user/torrent finder",
        )

        rendered = launcher_alias._render_launcher(target, platform="linux")

        self.assertIn(launcher_alias.MANAGED_MARKER, rendered)
        self.assertIn("cd '/home/user/torrent finder'", rendered)
        self.assertIn("exec /usr/bin/python3 -m torrent_finder \"$@\"", rendered)


class LauncherLocationTests(unittest.TestCase):
    def test_read_only_package_directory_falls_back_to_user_bin(self):
        user_bin = "C:/Users/test/.local/bin"
        with patch.object(
            launcher_alias, "_find_command", return_value="C:/Program Files/bin/torrent-finder.exe"
        ), patch.object(
            launcher_alias, "_directory_writable", return_value=False
        ), patch.object(
            launcher_alias, "_directory_on_path", side_effect=lambda path: path == user_bin
        ), patch.object(
            launcher_alias.os.path, "expanduser", return_value=user_bin
        ):
            directory = launcher_alias.launcher_dir()

        self.assertEqual(directory, user_bin)


class LauncherLifecycleTests(unittest.TestCase):
    def test_packaged_torrent_entry_point_is_selected_without_a_shim(self):
        canonical = "C:/bin/torrent-finder.exe"
        short = "C:/bin/torrent.exe"

        def find(name):
            return short if name == "torrent" else canonical

        with patch.object(launcher_alias, "_find_command", side_effect=find), \
             patch.object(launcher_alias, "load_setting", return_value=None), \
             patch.object(launcher_alias, "save_setting") as save, \
             patch.object(launcher_alias.store, "flush"):
            status = launcher_alias.set_terminal_command("torrent")

        self.assertFalse(status.managed)
        self.assertEqual(status.path, os.path.abspath(short))
        save.assert_called_once_with(
            launcher_alias.SETTING_KEY,
            {"name": "torrent", "path": os.path.abspath(short), "managed": False},
        )

    def test_unmanaged_command_collision_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            external = os.path.join(tmp, "tf.cmd")
            self._write(external, "@echo off\necho another tool\n")

            with patch.object(launcher_alias, "_find_command", return_value=external):
                with self.assertRaises(launcher_alias.LauncherConflict):
                    launcher_alias.set_terminal_command(
                        "tf",
                        directory=tmp,
                        target=self._target(),
                        platform="win32",
                    )

    def test_switching_alias_removes_the_previous_managed_launcher(self):
        with tempfile.TemporaryDirectory() as tmp:
            old_path = os.path.join(tmp, "find-torrent.cmd")
            self._write(old_path, f"@echo off\nrem {launcher_alias.MANAGED_MARKER}\n")
            saved = {
                "name": "find-torrent",
                "path": old_path,
                "managed": True,
            }

            with patch.object(launcher_alias, "load_setting", return_value=saved), \
                 patch.object(launcher_alias, "save_setting") as save, \
                 patch.object(launcher_alias.store, "flush"), \
                 patch.object(launcher_alias, "_find_command", return_value=None):
                status = launcher_alias.set_terminal_command(
                    "tf",
                    directory=tmp,
                    target=self._target(),
                    platform="win32",
                )

            self.assertFalse(os.path.exists(old_path))
            self.assertTrue(os.path.isfile(status.path))
            self.assertIn(launcher_alias.MANAGED_MARKER, self._read(status.path))
            save.assert_called_once_with(
                launcher_alias.SETTING_KEY,
                {"name": "tf", "path": status.path, "managed": True},
            )

    def test_reset_never_deletes_an_unowned_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            external = os.path.join(tmp, "tf.cmd")
            self._write(external, "@echo off\necho user file\n")
            saved = {"name": "tf", "path": external, "managed": True}

            with patch.object(launcher_alias, "load_setting", return_value=saved), \
                 patch.object(launcher_alias, "save_setting") as save, \
                 patch.object(launcher_alias.store, "flush"):
                status = launcher_alias.reset_terminal_command()

            self.assertTrue(os.path.isfile(external))
            self.assertEqual(status.name, launcher_alias.DEFAULT_COMMAND)
            save.assert_called_once_with(launcher_alias.SETTING_KEY, None)

    @staticmethod
    def _target():
        return launcher_alias.LaunchTarget(
            argv=(r"C:\Python\python.exe", "-m", "torrent_finder"),
            cwd=r"C:\src\torrent-finder",
        )

    @staticmethod
    def _write(path, text):
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text)

    @staticmethod
    def _read(path):
        with open(path, "r", encoding="utf-8") as handle:
            return handle.read()


if __name__ == "__main__":
    unittest.main()
