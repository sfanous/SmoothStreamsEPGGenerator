import copy
import logging

logger = logging.getLogger(__name__)


class Error(object):
    __slots__ = []

    _errors = []

    @classmethod
    def add_error(cls, error):
        cls._errors.append(error)

    @classmethod
    def get_errors(cls):
        return copy.deepcopy(cls._errors)

    @classmethod
    def has_errors(cls):
        if cls._errors:
            return True

        return False
