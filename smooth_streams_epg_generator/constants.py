import logging
import os
import sys

DEFAULT_CHANNEL_MAP_DIRECTORY_PATH = os.path.join(sys.path[0], 'resources', 'channel_map')
DEFAULT_CHANNEL_MAP_FILE_PATH = os.path.join(DEFAULT_CHANNEL_MAP_DIRECTORY_PATH, 'smooth_streams.xml')
DEFAULT_CONFIGURATION_FILE_PATH = os.path.join(sys.path[0], 'smooth_streams_epg_generator.ini')
DEFAULT_DB_DIRECTORY_PATH = os.path.join(sys.path[0], 'db')
DEFAULT_DB_FILE_PATH = os.path.join(DEFAULT_DB_DIRECTORY_PATH, 'smooth_streams_epg_generator.db')
DEFAULT_DB_CREATE_SCHEMA_FILE_PATH = os.path.join(DEFAULT_DB_DIRECTORY_PATH, 'create_schema.sql')
DEFAULT_INPUT_XMLTV_DIRECTORY_PATH = os.path.join(sys.path[0], 'xmltv')
DEFAULT_LOGGING_LEVEL = logging.DEBUG
DEFAULT_LOG_DIRECTORY_PATH = os.path.join(sys.path[0], 'logs')
DEFAULT_LOG_FILE_PATH = os.path.join(DEFAULT_LOG_DIRECTORY_PATH, 'smooth_streams_epg_generator.log')
DEFAULT_MC2XML_DIRECTORY_PATH = os.path.join(sys.path[0], 'mc2xml')
DEFAULT_MC2XML_EXECUTABLE_MAP = {'Darwin': 'mc2xml_osx.bin',
                                 'Linux': 'mc2xml_linux.bin',
                                 'Windows': 'mc2xml_windows.exe'}
DEFAULT_MC2XML_OUTPUT_DIRECTORY_PATH = os.path.join(sys.path[0], 'xmltv')
DEFAULT_OUTPUT_XMLTV_DIRECTORY_PATH = os.path.join(sys.path[0], 'output')
DEFAULT_OUTPUT_XMLTV_FILE_NAME_FORMAT = 'xmltv_{0}{1}{2}.xml'
DEFAULT_OUTPUT_XMLTV_NUMBER_OF_DAYS = [1, 3, 7]
DEFAULT_ROVI_TEMPLATE_FILE_PATH = os.path.join(DEFAULT_MC2XML_DIRECTORY_PATH, 'rovi_template', 'templates.json')
DEFAULT_ROVI_TEMPLATE_URL = url = 'http://cloud.rovicorp.com/template/v1/{0}/3/templates.json'
GMAIL_SERVER_HOSTNAME = 'smtp.gmail.com'
LOGGING_MAP = {'DEBUG': logging.DEBUG, 'ERROR': logging.ERROR, 'INFO': logging.INFO}
MAXIMUM_TIME_DELTA_IN_SECONDS = 1800
RISKY_FUZZY_MATCH_PERCENTAGE = 50
SAFE_FUZZY_MATCH_PERCENTAGE = 70
SMOOTH_STREAMS_EPG_BASE_URL = 'https://fast-guide.smoothstreams.tv/'
SMOOTH_STREAMS_EPG_FILE_NAME = 'feed.xml'
VALID_LOGGING_LEVEL_VALUES = ['DEBUG', 'ERROR', 'INFO']
VERSION = '1.2.0'
