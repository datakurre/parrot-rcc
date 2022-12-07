from io import BytesIO
from parrot_rcc.types import LogLevel
from PIL import Image
from urllib.parse import unquote
import base64
import binascii
import logging
import os
import re


class DefaultFormatter(logging.Formatter):

    green = "\x1b[32;20m"
    grey = "\x1b[38;20m"
    yellow = "\x1b[33;20m"
    red = "\x1b[31;20m"
    bold_red = "\x1b[31;1m"
    reset = "\x1b[0m"
    timestamp = "%(asctime)s - %(name)s - "
    level = "%(levelname)s"
    message = " - %(message)s"

    FORMATS = {
        logging.DEBUG: timestamp + grey + level + reset + message,
        logging.INFO: timestamp + green + level + reset + message,
        logging.WARNING: timestamp + yellow + level + reset + message,
        logging.ERROR: timestamp + red + level + reset + message,
        logging.CRITICAL: timestamp + bold_red + level + reset + message,
    }

    def format(self, record):
        log_fmt = self.FORMATS.get(record.levelno)
        formatter = logging.Formatter(log_fmt)
        return formatter.format(record)


class DebugFormatter(DefaultFormatter):

    FORMATS = {
        key: value + " (%(filename)s:%(lineno)d)"
        for key, value in DefaultFormatter.FORMATS.items()
    }


def setup_logging(logger: logging.Logger, log_level: LogLevel, debug: bool = False):
    # create logger with 'spam_application'
    logger.setLevel(f"{log_level}")

    # create console handler with a higher log level
    ch = logging.StreamHandler()
    ch.setLevel(f"{log_level}")

    ch.setFormatter(DebugFormatter() if debug else DefaultFormatter())

    logger.addHandler(ch)


def inline_screenshots(file_path: str):
    data = None
    mimetype = None
    cwd = os.getcwd()
    with open(file_path, encoding="utf-8") as fp:
        data = fp.read()
    for src in re.findall('img src="([^"]+)', data):
        if os.path.exists(src):
            filename = src
        elif os.path.exists(os.path.join(file_path, src)):
            filename = os.path.join(file_path, src)
        elif os.path.exists(os.path.join(cwd, src)):
            filename = os.path.join(cwd, src)
        elif src.startswith("data:"):
            filename = None
            try:
                spec, uri = src.split(",", 1)
                spec, encoding = spec.split(";", 1)
                spec, mimetype = spec.split(":", 1)
                if not (encoding == "base64" and mimetype.startswith("image/")):
                    continue
                data = base64.b64decode(unquote(uri).encode("utf-8"))
                Image.open(BytesIO(data))
            except (binascii.Error, IndexError, ValueError):
                continue
        else:
            continue
        if filename:
            im = Image.open(filename)
            mimetype = Image.MIME[im.format]
            # Fix issue where Pillow on Windows returns APNG for PNG
            if mimetype == "image/apng":
                mimetype = "image/png"
            with open(filename, "rb") as fp:
                data = fp.read()
        if data and mimetype:
            uri = data_uri(mimetype, data)
            data = data.replace(f'a href="{src}"', "a")
            data = data.replace(
                f'img src="{src}" width="800px"',
                f'img src="{uri}" style="max-width:800px;"',
            )  # noqa: E501
            data = data.replace(f'img src="{src}"', f'img src="{uri}"')
    with open(file_path, "w", encoding="utf-8") as fp:
        fp.write(data)


def data_uri(mimetype: str, data: bytes) -> str:
    return "data:{};base64,{}".format(  # noqa: C0209
        mimetype, base64.b64encode(data).decode("utf-8")
    )
