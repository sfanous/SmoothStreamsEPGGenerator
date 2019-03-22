import hashlib
import logging
import os
import platform
import subprocess
from datetime import datetime
from datetime import timedelta

import requests
import tzlocal

from .configuration import Configuration
from .constants import DEFAULT_MC2XML_DIRECTORY_PATH
from .constants import DEFAULT_MC2XML_EXECUTABLE_MAP
from .constants import DEFAULT_MC2XML_OUTPUT_DIRECTORY_PATH
from .error import Error
from .utilities import Utility

logger = logging.getLogger(__name__)


class SchedulesDirect(object):
    __slots__ = []

    _lineups = []

    @classmethod
    def _do_generate_xmltv_file(cls, country):
        current_date_time_in_local = datetime.now(tzlocal.get_localzone())

        for xmltv_file_name in os.listdir(DEFAULT_MC2XML_OUTPUT_DIRECTORY_PATH):
            if xmltv_file_name == '{0}.xml'.format(country):
                xmltv_file_attributes = os.stat(os.path.join(DEFAULT_MC2XML_OUTPUT_DIRECTORY_PATH, xmltv_file_name))
                xmltv_file_modification_date_time_in_local = datetime.fromtimestamp(
                    xmltv_file_attributes.st_mtime).astimezone(tzlocal.get_localzone())

                if current_date_time_in_local > xmltv_file_modification_date_time_in_local + timedelta(hours=18):
                    return True
                else:
                    return False

        return True

    @classmethod
    def _generate_xmltv_file(cls, country, postal_code, lineup_name):
        logger.debug('Executing mc2xml\n'
                     '  Country     => {0}\n'
                     '  Postal code => {1}\n'
                     '  Lineup name => {2}'.format(country[0:2], postal_code, lineup_name))

        completed_process = subprocess.run(
            ['{0}'.format(
                os.path.join(DEFAULT_MC2XML_DIRECTORY_PATH, DEFAULT_MC2XML_EXECUTABLE_MAP[platform.system()])),
                '-F',
                '-u',
                '-U',
                '-d', '240',
                '-s', '-24',
                '-c', '{0}'.format(country[0:2]),
                '-g', '{0}'.format(postal_code),
                '-J', '{0}:{1}'.format(Configuration.get_configuration_parameter('SCHEDULES_DIRECT_USERNAME'),
                                       Configuration.get_configuration_parameter('SCHEDULES_DIRECT_PASSWORD')),
                '-D', '{0}'.format(os.path.join(DEFAULT_MC2XML_DIRECTORY_PATH, country, 'mc2xml.dat')),
                '-C', '{0}'.format(os.path.join(DEFAULT_MC2XML_DIRECTORY_PATH, country, 'mc2xml.chl')),
                '-o', '{0}'.format(os.path.join(DEFAULT_MC2XML_OUTPUT_DIRECTORY_PATH, '{0}.xml'.format(country)))],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE)

        if completed_process.returncode:
            error = 'Failure while executing mc2xml\n' \
                    'Executed command => {0}\n' \
                    'Standard output  => {1}\n' \
                    'Standard error   => {2}'.format(' '.join(completed_process.args),
                                                     completed_process.stdout.decode().strip(),
                                                     completed_process.stderr.decode().strip())

            logger.error(error)
            Error.add_error(error)
        else:
            logger.debug('Successfully executed mc2xml')

    @classmethod
    def _populate_lineups(cls):
        logger.debug('Obtaining SchedulesDirect token\n'
                     'URL      => {0}\n'
                     'username => {1}\n'
                     'password => {2}'.format('https://json.schedulesdirect.org/20141201/token',
                                              Configuration.get_configuration_parameter('SCHEDULES_DIRECT_USERNAME'),
                                              hashlib.sha1(Configuration.get_configuration_parameter(
                                                  'SCHEDULES_DIRECT_PASSWORD').encode()).hexdigest()))

        session = requests.Session()
        response = Utility.make_http_request(session.post,
                                             'https://json.schedulesdirect.org/20141201/token',
                                             json_={"username": Configuration.get_configuration_parameter(
                                                 'SCHEDULES_DIRECT_USERNAME'),
                                                 "password": hashlib.sha1(
                                                     Configuration.get_configuration_parameter(
                                                         'SCHEDULES_DIRECT_PASSWORD').encode()).hexdigest()})
        logger.debug(Utility.assemble_response_from_log_message(response))
        token_response = response.json()

        if response.status_code == requests.codes.OK:
            if token_response['code'] == 0:
                token = token_response['token']

                logger.debug('Listing lineups currently added to the account\n'
                             'URL   => {0}\n'
                             'token => {1}'.format('https://json.schedulesdirect.org/20141201/lineups',
                                                   token))

                response = Utility.make_http_request(session.get,
                                                     'https://json.schedulesdirect.org/20141201/lineups',
                                                     headers={'token': token})
                logger.debug(Utility.assemble_response_from_log_message(response))
                list_lineups_response = response.json()

                if response.status_code == requests.codes.OK:
                    if list_lineups_response['code'] == 0:
                        for lineup in list_lineups_response['lineups']:
                            cls._lineups.append(lineup['lineup'])
                    else:
                        error = 'SchedulesDirect error\n' \
                                'Message => {0}'.format(list_lineups_response['message'])

                        logger.error(error)
                        Error.add_error(error)

                        raise SchedulesDirectError(list_lineups_response['message'])
                else:
                    error = 'SchedulesDirect error\n' \
                            'Message => {0}'.format(list_lineups_response['message'])

                    logger.error(error)
                    Error.add_error(error)

                    raise SchedulesDirectError(list_lineups_response['message'])
            else:
                error = 'SchedulesDirect error\n' \
                        'Message => {0}'.format(token_response['message'])

                logger.error(error)
                Error.add_error(error)

                raise SchedulesDirectError(token_response['message'])
        else:
            error = 'SchedulesDirect error\n' \
                    'Message => {0}'.format(token_response['message'])

            logger.error(error)
            Error.add_error(error)

            raise SchedulesDirectError(token_response['message'])

    @classmethod
    def generate_xmltv_files(cls):
        cls._populate_lineups()

        schedules_direct_listings = Configuration.get_configuration_parameter('SCHEDULES_DIRECT_LISTINGS')
        for schedules_direct_listing in schedules_direct_listings:
            (country, postal_code, lineup_name) = schedules_direct_listing.split(':')

            if cls._do_generate_xmltv_file(country) and lineup_name in cls._lineups:
                cls._generate_xmltv_file(country, postal_code, lineup_name)

        for schedules_direct_listing in schedules_direct_listings:
            (country, postal_code, lineup_name) = schedules_direct_listing.split(':')

            if cls._do_generate_xmltv_file(country) and lineup_name not in cls._lineups:
                cls._generate_xmltv_file(country, postal_code, lineup_name)


class SchedulesDirectError(Exception):
    pass
