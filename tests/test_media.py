import subprocess
import unittest
from unittest.mock import Mock, patch

from adb_automation import media
from adb_automation.errors import AutomationError


class MediaConversionTests(unittest.TestCase):
    def test_convert_audio_to_ogg_runs_ffmpeg_command(self):
        output_file = Mock()
        output_file.name = "/tmp/output.ogg"

        with patch(
            "adb_automation.media.tempfile.NamedTemporaryFile",
            return_value=output_file,
        ), patch("adb_automation.media.subprocess.run") as run:
            output_path = media.convert_audio_to_ogg("/tmp/input.mp3")

        self.assertEqual(output_path, "/tmp/output.ogg")
        output_file.close.assert_called_once()
        run.assert_called_once_with(
            [
                "ffmpeg",
                "-y",
                "-i",
                "/tmp/input.mp3",
                "-c:a",
                "libopus",
                "-b:a",
                "32k",
                "/tmp/output.ogg",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=True,
        )

    def test_convert_audio_to_ogg_removes_output_on_failure(self):
        output_file = Mock()
        output_file.name = "/tmp/output.ogg"

        with patch(
            "adb_automation.media.tempfile.NamedTemporaryFile",
            return_value=output_file,
        ), patch(
            "adb_automation.media.subprocess.run",
            side_effect=subprocess.CalledProcessError(
                1, ["ffmpeg"], stderr="bad audio"
            ),
        ), patch("adb_automation.media.remove_file_if_exists") as remove_file:
            with self.assertRaises(AutomationError):
                media.convert_audio_to_ogg("/tmp/input.mp3")

        remove_file.assert_called_once_with("/tmp/output.ogg")


if __name__ == "__main__":
    unittest.main()
