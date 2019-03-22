import logging
import sqlite3
from sqlite3 import Row

from .constants import DEFAULT_DB_CREATE_SCHEMA_FILE_PATH
from .utilities import Utility

logger = logging.getLogger(__name__)


class Database(object):
    __slots__ = []

    _connection = None
    _cursor = None
    _database_file_path = None

    @classmethod
    def _create_schema(cls):
        cls._cursor.executescript(Utility.read_file(DEFAULT_DB_CREATE_SCHEMA_FILE_PATH))

    @classmethod
    def close_connection(cls):
        logger.debug('Close connection to SQLite database\n'
                     'SQLite database file => {0}'.format(cls._database_file_path))

        cls._cursor.close()
        cls._connection.close()

    @classmethod
    def commit(cls):
        cls._connection.commit()

    @classmethod
    def execute(cls, sql_statement, parameters):
        cls._cursor.execute(sql_statement, parameters)

        return cls._cursor.fetchall()

    @classmethod
    def get_row_count(cls):
        return cls._cursor.rowcount

    @classmethod
    def open_connection(cls, database_file_path):
        cls._database_file_path = database_file_path

        cls._connection = sqlite3.connect(cls._database_file_path)
        cls._connection.row_factory = Row
        cls._cursor = cls._connection.cursor()

        logger.debug('Opened connection to SQLite database\n'
                     'SQLite database file => {0}'.format(database_file_path))

        cls._create_schema()
