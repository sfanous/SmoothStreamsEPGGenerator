import json
import logging.handlers
import os
import shutil
import sys
import traceback
from argparse import ArgumentParser
from datetime import datetime

import requests

from .constants import DEFAULT_CONFIGURATION_FILE_PATH
from .constants import DEFAULT_DB_FILE_PATH
from .constants import DEFAULT_LOG_FILE_PATH
from .constants import DEFAULT_OUTPUT_XMLTV_DIRECTORY_PATH
from .constants import VALID_LOGGING_LEVEL_VALUES

logger = logging.getLogger(__name__)


class Utility(object):
    __slots__ = []

    @classmethod
    def assemble_response_from_log_message(cls,
                                           response,
                                           is_content_binary=False,
                                           is_content_json=False,
                                           is_content_text=False,
                                           do_print_content=False):
        response_status_code = response.status_code
        if response_status_code == requests.codes.OK:
            response_headers = response.headers

            if is_content_binary:
                response_content = response.content
            elif is_content_json:
                response_content = json.dumps(response.json(), sort_keys=True, indent=2)
            elif is_content_text:
                response_content = response.text
            else:
                response_content = ''
                do_print_content = False

            return 'Response\n' \
                   '[Method]\n' \
                   '========\n{0}\n\n' \
                   '[URL]\n' \
                   '=====\n{1}\n\n' \
                   '[Status Code]\n' \
                   '=============\n{2}\n\n' \
                   '[Header]\n' \
                   '========\n{3}\n\n' \
                   '[Content]\n' \
                   '=========\n{4:{5}}\n'.format(response.request.method,
                                                 response.url,
                                                 response_status_code,
                                                 '\n'.join(['{0:32} => {1!s}'.format(key, response_headers[key])
                                                            for key in sorted(response_headers)]),
                                                 response_content if do_print_content else len(response_content),
                                                 '' if do_print_content else ',')
        else:
            return 'Response\n' \
                   '[Method]\n' \
                   '========\n{0}\n\n' \
                   '[URL]\n' \
                   '=====\n{1}\n\n' \
                   '[Status Code]\n' \
                   '=============\n{2}\n'.format(response.request.method, response.url, response_status_code)

    @classmethod
    def backup_epgs(cls, output_directory_path):
        latest_file_modification_date_time_in_local = None

        for xmltv_file_name in os.listdir(output_directory_path):
            if xmltv_file_name.endswith('.xml'):
                xmltv_file_attributes = os.stat(os.path.join(output_directory_path, xmltv_file_name))
                xmltv_file_modification_date_time_in_local = datetime.fromtimestamp(xmltv_file_attributes.st_mtime)

                if latest_file_modification_date_time_in_local is None or \
                        xmltv_file_modification_date_time_in_local > latest_file_modification_date_time_in_local:
                    latest_file_modification_date_time_in_local = xmltv_file_modification_date_time_in_local

        if latest_file_modification_date_time_in_local:
            backup_directory_path = os.path.join(output_directory_path,
                                                 latest_file_modification_date_time_in_local.strftime('%Y%m%d%H%M%S'))
            cls.create_directory(backup_directory_path)
            for xmltv_file_name in os.listdir(output_directory_path):
                if xmltv_file_name.endswith('.xml'):
                    shutil.copy2(os.path.join(output_directory_path, xmltv_file_name), backup_directory_path)

    @classmethod
    def calculate_absolute_time_delta(cls, date_time_1, date_time_2):
        return abs((date_time_2 - date_time_1).total_seconds())

    @classmethod
    def create_directory(cls, path):
        os.makedirs(path)

    @classmethod
    def is_valid_logging_level(cls, logging_level):
        is_valid_logging_level = True

        if logging_level not in VALID_LOGGING_LEVEL_VALUES:
            is_valid_logging_level = False

        return is_valid_logging_level

    @classmethod
    def make_http_request(cls,
                          requests_http_method,
                          url,
                          params=None,
                          data=None,
                          json_=None,
                          headers=None,
                          cookies=None,
                          stream=False,
                          auth=None,
                          timeout=60):
        try:
            logger.debug('Request\n'
                         '[Method]\n'
                         '========\n{0}\n\n'
                         '[URL]\n'
                         '=====\n{1}\n'
                         '{2}{3}{4}{5}'.format(requests_http_method.__name__.upper(),
                                               url,
                                               '\n'
                                               '[Query Parameters]\n'
                                               '==================\n{0}\n'.format('\n'.join(
                                                   ['{0:32} => {1!s}'.format(key, params[key])
                                                    for key in sorted(params)])) if params else '',
                                               '\n'
                                               '[Headers]\n'
                                               '=========\n{0}\n'.format(
                                                   '\n'.join(
                                                       ['{0:32} => {1!s}'.format(header, headers[header])
                                                        for header in sorted(headers)])) if headers else '',
                                               '\n'
                                               '[Cookies]\n'
                                               '=========\n{0}\n'.format(
                                                   '\n'.join(
                                                       ['{0:32} => {1!s}'.format(cookie, cookies[cookie])
                                                        for cookie in sorted(cookies)])) if cookies else '',
                                               '\n'
                                               '[JSON]\n'
                                               '======\n{0}\n'.format(
                                                   json.dumps(json_,
                                                              sort_keys=True,
                                                              indent=2)) if json_ else '').strip())

            return requests_http_method(url,
                                        params=params,
                                        data=data,
                                        json=json_,
                                        headers=headers,
                                        cookies=cookies,
                                        stream=stream,
                                        auth=auth,
                                        timeout=timeout)
        except requests.exceptions.RequestException as e:
            (type_, value_, traceback_) = sys.exc_info()
            logger.error('\n'.join(traceback.format_exception(type_, value_, traceback_)))

            raise e

    @classmethod
    def parse_command_line_arguments(cls):
        parser = ArgumentParser()

        parser.add_argument('-b',
                            action='store_true',
                            dest='do_backup_output_xmltv_files',
                            help='backup XMLTV files generated from previous execution')
        parser.add_argument('-c',
                            action='store',
                            default=DEFAULT_CONFIGURATION_FILE_PATH,
                            dest='configuration_file_path',
                            help='path to the configuration file',
                            metavar='configuration file path')
        parser.add_argument('-d',
                            action='store',
                            default=DEFAULT_DB_FILE_PATH,
                            dest='database_file_path',
                            help='path to the database file',
                            metavar='database file path')
        parser.add_argument('-l',
                            action='store',
                            default=DEFAULT_LOG_FILE_PATH,
                            dest='log_file_path',
                            help='path to the log file',
                            metavar='log file path')
        parser.add_argument('-o',
                            action='store',
                            default=DEFAULT_OUTPUT_XMLTV_DIRECTORY_PATH,
                            dest='output_directory_path',
                            help='path to the output directory file',
                            metavar='output directory path')

        arguments = parser.parse_args()

        return (arguments.do_backup_output_xmltv_files,
                arguments.configuration_file_path,
                arguments.database_file_path,
                arguments.log_file_path,
                arguments.output_directory_path)

    @classmethod
    def read_file(cls, file_path):
        try:
            with open(file_path, mode='r', encoding='utf-8') as input_file:
                file_content = input_file.read()

                return file_content
        except OSError:
            logger.error('Failed to read file\n'
                         'File path => {0}'.format(file_path))

            raise

    @classmethod
    def write_file(cls, file_path, file_content):
        try:
            with open(file_path, mode='w', encoding='utf-8') as output_file:
                output_file.write(file_content)
        except OSError:
            logger.error('Failed to write file\n'
                         'File path => {0}'.format(file_path))

            raise
