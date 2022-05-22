from parrot_rcc.types import LogLevel
import logging


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


def setup_logging(logger: logging.Logger, log_level: LogLevel):
    # create logger with 'spam_application'
    logger.setLevel(f"{log_level}")

    # create console handler with a higher log level
    ch = logging.StreamHandler()
    ch.setLevel(f"{log_level}")

    ch.setFormatter(
        DebugFormatter() if log_level == LogLevel.DEBUG else DefaultFormatter()
    )

    logger.addHandler(ch)
