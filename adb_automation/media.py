import os
import subprocess
import tempfile

from .errors import AutomationError


def convert_audio_to_ogg(input_path):
    output_file = tempfile.NamedTemporaryFile(delete=False, suffix=".ogg")
    output_path = output_file.name
    output_file.close()

    command = [
        "ffmpeg",
        "-y",
        "-i",
        input_path,
        "-c:a",
        "libopus",
        "-b:a",
        "32k",
        output_path,
    ]

    try:
        subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=True,
        )
        return output_path
    except FileNotFoundError as exc:
        remove_file_if_exists(output_path)
        raise AutomationError("ffmpeg was not found. Install ffmpeg to send voice.") from exc
    except subprocess.CalledProcessError as exc:
        remove_file_if_exists(output_path)
        details = exc.stderr.strip() or exc.stdout.strip() or "ffmpeg conversion failed."
        raise AutomationError(details) from exc


def remove_file_if_exists(path):
    if path and os.path.exists(path):
        os.remove(path)
