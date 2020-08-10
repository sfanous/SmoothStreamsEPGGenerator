import logging
import logging.handlers

from .constants import DEFAULT_LOGGING_LEVEL
from .formatters import MultiLineFormatter

logger = logging.getLogger(__name__)


class Log(object):
    __slots__ = []

    @classmethod
    def initialize_logging(cls, log_file_path):
        formatter = MultiLineFormatter(
            '%(asctime)s %(name)-40s %(funcName)-48s %(levelname)-8s %(message)s'
        )

        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)

        rotating_file_handler = logging.handlers.RotatingFileHandler(
            '{0}'.format(log_file_path),
            maxBytes=1024 * 1024 * 10,
            backupCount=10,
            encoding='utf-8',
        )
        rotating_file_handler.setFormatter(formatter)

        logging.getLogger('smooth_streams_epg_generator').addHandler(console_handler)
        logging.getLogger('smooth_streams_epg_generator').addHandler(
            rotating_file_handler
        )

        cls.set_logging_level(DEFAULT_LOGGING_LEVEL)

    @classmethod
    def set_logging_level(cls, log_level):
        logging.getLogger('smooth_streams_epg_generator').setLevel(log_level)

        for handler in logger.handlers:
            handler.setLevel(log_level)
