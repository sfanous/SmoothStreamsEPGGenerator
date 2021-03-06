import logging
import sys
import traceback

from .configuration import Configuration
from .constants import LOGGING_MAP
from .constants import VERSION
from .db import Database
from .epg import EPG
from .error import Error
from .log import Log
from .notification import Notifier
from .privilege import Privilege
from .rovi import Rovi
from .schedules_direct import SchedulesDirect
from .utilities import Utility

logger = logging.getLogger(__name__)


def main():
    try:
        Privilege.initialize()
        Privilege.become_unprivileged_user()

        (
            do_backup_output_xmltv_files,
            configuration_file_path,
            database_file_path,
            log_file_path,
            output_directory_path,
        ) = Utility.parse_command_line_arguments()

        Log.initialize_logging(log_file_path)

        logger.info(
            'Starting SmoothStreams EPG Generator %s\n'
            'Configuration file path => %s\n'
            'Database file path      => %s\n'
            'Log file path           => %s\n'
            'Output directory path   => %s',
            VERSION,
            configuration_file_path,
            database_file_path,
            log_file_path,
            output_directory_path,
        )

        Configuration.read_configuration_file(configuration_file_path)
        Log.set_logging_level(
            LOGGING_MAP[
                Configuration.get_configuration_parameter('LOGGING_LEVEL').upper()
            ]
        )
        Database.open_connection(database_file_path)

        Rovi.generate_xmltv_files()
        SchedulesDirect.generate_xmltv_files()

        EPG.generate_epg(output_directory_path, do_backup_output_xmltv_files)

        Database.commit()
        Database.close_connection()
    except Exception:
        (type_, value_, traceback_) = sys.exc_info()
        error = '\n'.join(traceback.format_exception(type_, value_, traceback_))

        logger.error(error)
        Error.add_error(error)
    finally:
        if (
            Configuration.get_configuration_parameter('GMAIL_ENABLED')
            and Error.has_errors()
        ):
            Notifier.send_email('\n{0}\n'.format('*' * 120).join(Error.get_errors()))

    logger.info('Shutdown SmoothStreams EPG Generator %s', VERSION)
