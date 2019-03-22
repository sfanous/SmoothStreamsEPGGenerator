import json
import logging
import os
import platform
import subprocess

import requests
from requests_oauthlib import OAuth1

from .configuration import Configuration
from .constants import DEFAULT_MC2XML_DIRECTORY_PATH
from .constants import DEFAULT_MC2XML_EXECUTABLE_MAP
from .constants import DEFAULT_MC2XML_OUTPUT_DIRECTORY_PATH
from .constants import DEFAULT_ROVI_TEMPLATE_FILE_PATH
from .constants import DEFAULT_ROVI_TEMPLATE_URL
from .error import Error
from .utilities import Utility

logger = logging.getLogger(__name__)


class Rovi(object):
    __slots__ = []

    @classmethod
    def _request_template_json(cls):
        url = '{0}'.format(DEFAULT_ROVI_TEMPLATE_URL.format(Configuration.get_configuration_parameter('ROVI_API_KEY')))

        logger.debug('Downloading templates.json\n'
                     'URL => {0}'.format(url))

        session = requests.Session()
        auth = OAuth1(Configuration.get_configuration_parameter('ROVI_API_KEY'),
                      Configuration.get_configuration_parameter('ROVI_SHARED_SECRET'))
        response = Utility.make_http_request(session.get, url, headers=session.headers, auth=auth)

        if response.status_code == requests.codes.OK:
            with open(DEFAULT_ROVI_TEMPLATE_FILE_PATH, 'w') as template_json_file:
                json.dump(response.json(), template_json_file, sort_keys=True, indent=4)

            logger.debug(Utility.assemble_response_from_log_message(response))
        else:
            logger.debug(Utility.assemble_response_from_log_message(response))

            response.raise_for_status()

    @classmethod
    def generate_xmltv_files(cls):
        cls._request_template_json()

        rovi_listings = Configuration.get_configuration_parameter('ROVI_LISTINGS')
        for rovi_listing in rovi_listings:
            (country, postal_code) = rovi_listing.split(':')

            logger.debug('Executing mc2xml\n'
                         '  Country     => {0}\n'
                         '  Postal code => {1}'.format(country[0:2], postal_code))

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
                    '-r', '{0}:{1}'.format(Configuration.get_configuration_parameter('ROVI_API_KEY'),
                                           Configuration.get_configuration_parameter('ROVI_SHARED_SECRET')),
                    '-D', '{0}'.format(os.path.join(DEFAULT_MC2XML_DIRECTORY_PATH, country, 'mc2xml.dat')),
                    '-C', '{0}'.format(os.path.join(DEFAULT_MC2XML_DIRECTORY_PATH, country, 'mc2xml.chl')),
                    '-o', '{0}'.format(os.path.join(DEFAULT_MC2XML_OUTPUT_DIRECTORY_PATH, '{0}.xml'.format(country))),
                    '--rovi-airing_synopses',
                    '--rovi-template={0}'.format(DEFAULT_ROVI_TEMPLATE_FILE_PATH),
                    '--max-threads=1'],
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
