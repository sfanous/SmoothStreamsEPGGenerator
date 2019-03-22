import logging
import sys

from configobj import ConfigObj

from .constants import DEFAULT_LOGGING_LEVEL
from .constants import VALID_LOGGING_LEVEL_VALUES
from .utilities import Utility

logger = logging.getLogger(__name__)


class Configuration(object):
    __slots__ = []

    _configuration = {}

    @classmethod
    def get_configuration_parameter(cls, parameter_name):
        return cls._configuration[parameter_name]

    @classmethod
    def read_configuration_file(cls, configuration_file_path):
        try:
            configuration_object = ConfigObj(configuration_file_path,
                                             file_error=True,
                                             indent_type='',
                                             interpolation=False,
                                             raise_errors=True,
                                             write_empty_values=True)

            non_defaultable_error = False
            error_messages = []

            rovi_api_key = None
            rovi_shared_secret = None
            rovi_listings = None
            schedules_direct_username = None
            schedules_direct_password = None
            schedules_direct_listings = None
            gmail_username = None
            gmail_password = None
            logging_level = DEFAULT_LOGGING_LEVEL

            # <editor-fold desc="Read Rovi section">
            try:
                rovi_section = configuration_object['Rovi']

                try:
                    rovi_api_key = rovi_section['api_key']
                except KeyError:
                    non_defaultable_error = True

                    error_messages.append('Could not find a api_key option within the [Rovi] section\n')

                try:
                    rovi_shared_secret = rovi_section['shared_secret']
                except KeyError:
                    non_defaultable_error = True

                    error_messages.append('Could not find a shared_secret option within the [Rovi] section\n')

                try:
                    rovi_listings = rovi_section['listings']
                except KeyError:
                    non_defaultable_error = True

                    error_messages.append('Could not find a listings option within the [Rovi] section\n')
            except KeyError:
                non_defaultable_error = True

                error_messages.append('Could not find a [Rovi] section\n')
            # </editor-fold>

            # <editor-fold desc="Read SchedulesDirect section">
            try:
                schedules_direct_section = configuration_object['SchedulesDirect']

                try:
                    schedules_direct_username = schedules_direct_section['username']
                except KeyError:
                    non_defaultable_error = True

                    error_messages.append('Could not find a username option within the [SchedulesDirect] section\n')

                try:
                    schedules_direct_password = schedules_direct_section['password']
                except KeyError:
                    non_defaultable_error = True

                    error_messages.append('Could not find a password option within the [SchedulesDirect] section\n')

                try:
                    schedules_direct_listings = schedules_direct_section['listings']
                except KeyError:
                    non_defaultable_error = True

                    error_messages.append('Could not find a listings option within the [SchedulesDirect] section\n')
            except KeyError:
                non_defaultable_error = True

                error_messages.append('Could not find a [SchedulesDirect] section\n')
            # </editor-fold>

            # <editor-fold desc="Read GMail section">
            try:
                gmail_section = configuration_object['GMail']

                try:
                    gmail_username = gmail_section['username']
                except KeyError:
                    non_defaultable_error = True

                    error_messages.append('Could not find a username option within the [GMail] section\n')

                try:
                    gmail_password = gmail_section['password']
                except KeyError:
                    non_defaultable_error = True

                    error_messages.append('Could not find a password option within the [GMail] section\n')
            except KeyError:
                non_defaultable_error = True

                error_messages.append('Could not find a [GMail] section\n')
            # </editor-fold>

            # <editor-fold desc="Read Logging section">
            try:
                logging_section = configuration_object['Logging']

                try:
                    logging_level = logging_section['level'].upper()
                    if not Utility.is_valid_logging_level(logging_level):
                        logging_level = DEFAULT_LOGGING_LEVEL

                        error_messages.append('The level option within the [Logging] section must be one of\n'
                                              '{0}\n'
                                              'Defaulting to {1}\n'.format('\n'.join(['\u2022 {0}'.format(service)
                                                                                      for service in
                                                                                      VALID_LOGGING_LEVEL_VALUES]),
                                                                           logging_level))
                except KeyError:
                    error_messages.append('Could not find a level option within the [Logging] section\n'
                                          'The level option within the [Logging] section must be one of\n'
                                          '{0}\n'
                                          'Defaulting to {1}\n'.format('\n'.join(['\u2022 {0}'.format(service)
                                                                                  for service in
                                                                                  VALID_LOGGING_LEVEL_VALUES]),
                                                                       logging_level))
            except KeyError:
                error_messages.append('Could not find an [Logging] section\n'
                                      'Defaulting the level option to {0}\n'.format(logging_level))
            # </editor-fold>

            if error_messages:
                error_messages.insert(0,
                                      '{0} configuration file values\n'
                                      'Configuration file path => {1}\n'.format(
                                          'Invalid' if non_defaultable_error else 'Warnings regarding',
                                          configuration_file_path))

                if non_defaultable_error:
                    error_messages.append('Exiting...')
                else:
                    error_messages.append('Processing with default values...')

                logger.error('\n'.join(error_messages))

                if non_defaultable_error:
                    sys.exit()

            if not non_defaultable_error:
                cls._configuration = {
                    'ROVI_API_KEY': rovi_api_key,
                    'ROVI_SHARED_SECRET': rovi_shared_secret,
                    'ROVI_LISTINGS': rovi_listings,
                    'SCHEDULES_DIRECT_USERNAME': schedules_direct_username,
                    'SCHEDULES_DIRECT_PASSWORD': schedules_direct_password,
                    'SCHEDULES_DIRECT_LISTINGS': schedules_direct_listings,
                    'GMAIL_USERNAME': gmail_username,
                    'GMAIL_PASSWORD': gmail_password,
                    'LOGGING_LEVEL': logging_level
                }

                logger.info('Read configuration file\n'
                            'Configuration file path  => {0}\n\n'
                            'Rovi API key             => {1}\n'
                            'Rovi shared secret       => {2}\n'
                            'Rovi listings            => {3}\n'
                            'SchedulesDirect username => {4}\n'
                            'SchedulesDirect password => {5}\n'
                            'SchedulesDirect listings => {6}\n'
                            'GMail username           => {7}\n'
                            'GMail password           => {8}\n'
                            'Logging level            => {9}'.format(configuration_file_path,
                                                                     rovi_api_key,
                                                                     rovi_shared_secret,
                                                                     rovi_listings,
                                                                     schedules_direct_username,
                                                                     schedules_direct_password,
                                                                     schedules_direct_listings,
                                                                     gmail_username,
                                                                     gmail_password,
                                                                     logging_level))
        except OSError:
            logger.error('Could not open the specified configuration file for reading\n'
                         'Configuration file path => {0}\n\n'
                         'Exiting...'.format(configuration_file_path))

            sys.exit()
        except SyntaxError as e:
            logger.error('Invalid configuration file syntax\n'
                         'Configuration file path => {0}\n'
                         '{1}'
                         '\n\nExiting...'.format(configuration_file_path,
                                                 '{0}'.format(e)))

            sys.exit()
