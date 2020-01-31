import bisect
import copy
import logging
import os
import re
import sqlite3
from datetime import datetime
from datetime import timedelta
from xml.sax import saxutils

import jellyfish
import pytz
import requests
import tzlocal
from fuzzywuzzy import fuzz
from fuzzywuzzy import process
from lxml import etree

from smooth_streams_epg_generator.db import Database
from .constants import DEFAULT_CHANNEL_MAP_FILE_PATH
from .constants import DEFAULT_INPUT_XMLTV_DIRECTORY_PATH
from .constants import DEFAULT_MC2XML_DIRECTORY_PATH
from .constants import DEFAULT_OUTPUT_XMLTV_FILE_NAME_FORMAT
from .constants import DEFAULT_OUTPUT_XMLTV_NUMBER_OF_DAYS
from .constants import MAXIMUM_TIME_DELTA_IN_SECONDS
from .constants import RISKY_FUZZY_MATCH_PERCENTAGE
from .constants import SAFE_FUZZY_MATCH_PERCENTAGE
from .constants import SMOOTH_STREAMS_EPG_BASE_URL
from .constants import SMOOTH_STREAMS_EPG_FILE_NAME
from .error import Error
from .privilege import Privilege
from .utilities import Utility

logger = logging.getLogger(__name__)


class EPG(object):
    __slots__ = []

    _categories_map = {}
    _channel_id_map = {'I207.59976': '1', 'I206.32645': '2', 'I209.45507': '3', 'I208.60696': '4', 'I219.82547': '5',
                       'I618.59305': '6', 'I212.45399': '7', 'I216.45526': '8', 'I213.62081': '9', 'I215.58690': '10',
                       'I220.48639': '11', 'I218.61854': '12', 'I217.60316': '13', 'I221.59250': '14',
                       'I1423.48099': '15', 'I1446.91306': '16', 'I1420.68946': '17', 'I1410.49952': '18',
                       'I1405.62111': '19', 'I1409.68859': '20', 'I1401.34313': '21', 'I464.77033': '22',
                       'I466.71914': '23', 'I249.62420': '24', 'I241.59186': '25', 'I242.58452': '26',
                       'I265.51529': '27', 'I247.58515': '28', 'I245.42642': '29', 'I244.58623': '30',
                       'I296.60048': '31', 'I229.49788': '32', 'I202.58646': '33', 'I2.1.31507': '34',
                       'I7.1.24052': '35', 'I29.1.42945': '36', 'I280.57391': '37', 'I360.60179': '38',
                       'I269.57708': '41', 'I278.56905': '42', 'I276.49438': '43', 'I248.58574': '44',
                       'I259.66379': '45', 'I355.58780': '46', 'I254.59337': '47', 'I501.19548': '48',
                       'I506.59839': '49', 'I231.50747': '50', 'I509.59845': '51', 'I545.21868': '52',
                       'I519.59948': '53', 'I517.59373': '54', 'I531.67236': '55', 'I525.34941': '56',
                       'I535.36225': '57', 'I285.65342': '58', 'I515.34933': '59', 'I520.59961': '60',
                       'I4.1.24051': '63', 'I1400.90123': '65', 'I1204.34200': '66', 'I1203.44792': '67',
                       'I1201.44784': '68', 'I1202.72705': '69', 'I406.76382': '70', 'I346.89690': '71',
                       'I623.87000': '73', 'I610.58321': '76', 'I232.68065': '77', 'I264.64492': '78',
                       'I712.68605': '80', 'I53.87010': '100', 'I25.69046130': '101', 'I26.69046131': '102',
                       'I374.72791': '105', 'I378.87629': '106', 'I422.109501': '107', 'I867.82450': '108',
                       'I868.82451': '109', 'I869.95772': '110', 'I872.64572': '111', 'I409.90643': '112',
                       'I401.17744': '113', 'I404.19036': '114', 'I407.19038': '115', 'I405.24216': '116',
                       'I402.89362': '117', 'I406.74410': '118', 'I145.100264': '119', 'I403.104325': '120',
                       'I408.104322': '121', 'I1412.91308': '123', 'I1413.76955': '124', 'I356.64241': '127',
                       'I252.60150': '131', 'I312.66268': '132', 'I362.58812': '145', 'I1503.94289': '150'}
    _epg = {}
    _latest_date_time_epg_xml = None
    _mc2xml_channel_ids_map = {}
    _parsed_programs_map = {}
    _smooth_streams_epg = {}
    _startup_date_time_in_utc = None

    @classmethod
    def _are_programs_pre_validated_match(cls, smooth_streams_program, epg_program):
        program_match_records = cls._query_program_match_table(smooth_streams_program, epg_program)
        if program_match_records:
            if program_match_records[0]['is_valid'] == 1:
                cls._update_program_match_table(smooth_streams_program, epg_program)

                return True

        return False

    @classmethod
    def _cleanup_smooth_streams_epg(cls):
        for channel in cls._smooth_streams_epg.values():
            last_program_stop = None
            smooth_streams_programs_to_delete = []

            for smooth_streams_program in channel.programs:
                if last_program_stop is None:
                    last_program_stop = smooth_streams_program.stop
                elif smooth_streams_program.start >= last_program_stop:
                    last_program_stop = smooth_streams_program.stop
                elif smooth_streams_program.start < last_program_stop:
                    smooth_streams_programs_to_delete.append(smooth_streams_program)

                    logger.debug('Overlap in SmoothStreams EPG detected\n'
                                 'Sports program\n'
                                 '  Title     => {0}\n'
                                 '  Start     => {1}\n'
                                 '  Stop      => {2}'.format(smooth_streams_program.titles[0]['value'],
                                                             smooth_streams_program.start,
                                                             smooth_streams_program.stop))

            for smooth_streams_program_to_delete in smooth_streams_programs_to_delete:
                channel.remove_program(smooth_streams_program_to_delete)

                logger.debug('Overlap in SmoothStreams EPG processed\n'
                             'SmoothStreams program removed\n'
                             '  Title     => {0}\n'
                             '  Start     => {1}\n'
                             '  Stop      => {2}'.format(smooth_streams_program_to_delete.titles[0]['value'],
                                                         smooth_streams_program_to_delete.start,
                                                         smooth_streams_program_to_delete.stop))

    @classmethod
    def _create_match_tuples(cls, smooth_streams_program, epg_program):
        match_tuples = []

        if ': ' in smooth_streams_program.titles[0]['value']:
            smooth_streams_program_category = smooth_streams_program.titles[0]['value'][
                                              0:smooth_streams_program.titles[0]['value'].find(': ')]
            epg_program_title = re.sub(r'\A.*:\s+', '', epg_program.titles[0]['value'])

            category_map_records = cls._query_category_map_table(smooth_streams_program_category)
            for category_map_record in category_map_records:
                if category_map_record['is_valid'] == 1:
                    if category_map_record['epg_category'] == epg_program_title and epg_program.has_sub_titles():
                        match_tuples.append(
                            (smooth_streams_program.titles[0]['value'][len(smooth_streams_program_category) + 2:],
                             epg_program.sub_titles[0]['value']))

                        if ': ' in epg_program.sub_titles[0]['value']:
                            match_tuples.append(
                                (smooth_streams_program.titles[0]['value'][len(smooth_streams_program_category) + 2:],
                                 re.sub(r'\A.*:\s+', '', epg_program.sub_titles[0]['value'])))
                elif category_map_record['reviewed']:
                    return match_tuples

            if not match_tuples and epg_program.has_sub_titles():
                match_tuples.append(
                    (smooth_streams_program.titles[0]['value'][len(smooth_streams_program_category) + 2:],
                     epg_program.sub_titles[0]['value']))

                if ': ' in epg_program.sub_titles[0]['value']:
                    match_tuples.append(
                        (smooth_streams_program.titles[0]['value'][len(smooth_streams_program_category) + 2:],
                         re.sub(r'\A.*:\s+', '', epg_program.sub_titles[0]['value'])))
        else:
            match_tuples.append((smooth_streams_program.titles[0]['value'], epg_program.titles[0]['value']))

        match_tuples.append(('{0}{1}'.format(smooth_streams_program.titles[0]['value'],
                                             ': {0}'.format(smooth_streams_program.sub_titles[0]['value'])
                                             if smooth_streams_program.has_sub_titles() else ''),
                             '{0}{1}'.format(epg_program.titles[0]['value'],
                                             ': {0}'.format(epg_program.sub_titles[0]['value'])
                                             if epg_program.has_sub_titles() else '')))

        return match_tuples

    @classmethod
    def _create_potential_match_tuples(cls, smooth_streams_program_query_strings):
        potential_matches_to_score_map = {}
        for smooth_streams_program_query_string in smooth_streams_program_query_strings:
            for potential_match_tuple in process.extract(smooth_streams_program_query_string,
                                                         cls._parsed_programs_map.keys(),
                                                         scorer=fuzz.token_sort_ratio,
                                                         limit=5):
                if potential_match_tuple[0] not in potential_matches_to_score_map or \
                        potential_matches_to_score_map[potential_match_tuple[0]] < potential_match_tuple[1]:
                    potential_matches_to_score_map[potential_match_tuple[0]] = potential_match_tuple[1]

        potential_match_tuples = []
        for potential_match in potential_matches_to_score_map:
            potential_match_tuples.append((potential_match, potential_matches_to_score_map[potential_match]))
        potential_match_tuples.sort(key=lambda potential_match_tuple_: potential_match_tuple_[1], reverse=True)

        return potential_match_tuples

    @classmethod
    def _create_program_query_strings(cls, smooth_streams_program):
        smooth_streams_program_query_strings = []

        if ': ' in smooth_streams_program.titles[0]['value']:
            smooth_streams_program_category = smooth_streams_program.titles[0]['value'][
                                              0:smooth_streams_program.titles[0]['value'].find(': ')]

            category_map_records = cls._query_category_map_table(smooth_streams_program_category)
            for category_map_record in category_map_records:
                if category_map_record['is_valid']:
                    smooth_streams_program_query_strings.append(
                        re.sub(smooth_streams_program_category,
                               category_map_record['epg_category'],
                               smooth_streams_program.titles[0]['value']))

            smooth_streams_program_query_strings.append(
                smooth_streams_program.titles[0]['value'][len(smooth_streams_program_category) + 2:])
            smooth_streams_program_query_strings.append(smooth_streams_program.titles[0]['value'])

            if smooth_streams_program.has_sub_titles():
                smooth_streams_program_query_strings.append('{0}: {1}'.format(
                    smooth_streams_program.titles[0]['value'],
                    smooth_streams_program.sub_titles[0]['value']))
        else:
            smooth_streams_program_query_strings.append(smooth_streams_program.titles[0]['value'])

            if smooth_streams_program.has_sub_titles():
                smooth_streams_program_query_strings.append('{0}: {1}'.format(
                    smooth_streams_program.titles[0]['value'],
                    smooth_streams_program.sub_titles[0]['value']))

        return smooth_streams_program_query_strings

    @classmethod
    def _delete_from_failed_program_match_table(cls):
        sql_statement = 'DELETE ' \
                        'FROM failed_program_match ' \
                        'WHERE date_time_of_last_failure < :date_time_of_last_failure_cutoff'
        Database.execute(sql_statement, {'date_time_of_last_failure_cutoff': str(cls._startup_date_time_in_utc)})
        Database.commit()

    @classmethod
    def _delete_from_forced_program_match_table(cls):
        sql_statement = 'DELETE ' \
                        'FROM forced_program_match ' \
                        'WHERE smooth_streams_program_stop < :smooth_streams_program_stop_cutoff'
        Database.execute(sql_statement,
                         {'smooth_streams_program_stop_cutoff': str(cls._startup_date_time_in_utc - timedelta(days=1))})
        Database.commit()

    @classmethod
    def _delete_from_ignored_epg_program_match_table(cls):
        sql_statement = 'DELETE ' \
                        'FROM ignored_epg_program_match ' \
                        'WHERE epg_program_stop < :epg_program_stop_cutoff ' \
                        '  AND epg_program_stop <> \'\''
        Database.execute(sql_statement,
                         {'epg_program_stop_cutoff': str(cls._startup_date_time_in_utc - timedelta(days=1))})
        Database.commit()

    @classmethod
    def _delete_from_ignored_smooth_streams_program_match_table(cls):
        sql_statement = 'DELETE ' \
                        'FROM ignored_smooth_streams_program_match ' \
                        'WHERE smooth_streams_program_stop < :smooth_streams_program_stop_cutoff ' \
                        '  AND smooth_streams_program_stop <> \'\''
        Database.execute(sql_statement,
                         {'smooth_streams_program_stop_cutoff': str(cls._startup_date_time_in_utc - timedelta(days=1))})
        Database.commit()

    @classmethod
    def _delete_from_program_match_table(cls):
        sql_statement = 'DELETE ' \
                        'FROM program_match ' \
                        'WHERE date_time_of_last_match < :date_time_of_last_match_cutoff'
        Database.execute(sql_statement, {'date_time_of_last_match_cutoff': str(cls._startup_date_time_in_utc)})
        Database.commit()

    @classmethod
    def _determine_matching_program(cls,
                                    smooth_streams_program,
                                    potential_match_tuples,
                                    do_check_same_channel=True,
                                    do_check_start_stop_times_alignment=False,
                                    do_check_duration_equivalency=True):
        for potential_match_tuple in potential_match_tuples:
            for potential_matching_epg_program in cls._parsed_programs_map[potential_match_tuple[0]]:
                regular_expression_match = re.search(r'I[0-9]+.[0-9]+(.[0-9]+)?',
                                                     potential_matching_epg_program.channel)
                if regular_expression_match is not None:
                    potential_matching_epg_program_channel_id = regular_expression_match.group(0)
                else:
                    potential_matching_epg_program_channel_id = potential_matching_epg_program.channel

                if do_check_same_channel:
                    if potential_matching_epg_program_channel_id not in cls._channel_id_map or \
                            smooth_streams_program.channel != \
                            cls._channel_id_map[potential_matching_epg_program_channel_id]:
                        continue
                else:
                    if potential_matching_epg_program_channel_id in cls._channel_id_map and \
                            smooth_streams_program.channel == \
                            cls._channel_id_map[potential_matching_epg_program_channel_id]:
                        continue

                if cls._do_programs_match(smooth_streams_program,
                                          potential_matching_epg_program,
                                          do_check_start_stop_times_alignment=do_check_start_stop_times_alignment,
                                          do_check_duration_equivalency=do_check_duration_equivalency):
                    matching_epg_program = potential_matching_epg_program

                    if not do_check_start_stop_times_alignment and do_check_duration_equivalency:
                        matching_epg_program = copy.deepcopy(potential_matching_epg_program)
                        matching_epg_program.start = smooth_streams_program.start
                        matching_epg_program.stop = smooth_streams_program.stop

                    return matching_epg_program

        return None

    @classmethod
    def _do_process_overlap(cls,
                            smooth_streams_program,
                            epg_program,
                            do_find_best_matching_program=True,
                            do_check_start_stop_times_alignment=True):
        do_process_overlap = True

        if not cls._is_program_in_the_past(smooth_streams_program) and not \
                cls._is_program_past_date_time_criteria(smooth_streams_program) and not \
                cls._is_program_in_ignored_smooth_streams_program_match_table(smooth_streams_program) and not \
                cls._does_program_match_ignored_smooth_streams_program_pattern(smooth_streams_program):
            if cls._are_programs_pre_validated_match(smooth_streams_program, epg_program):
                do_process_overlap = False
            else:
                if do_find_best_matching_program:
                    if not cls._do_programs_match(
                            smooth_streams_program,
                            epg_program,
                            do_check_start_stop_times_alignment=do_check_start_stop_times_alignment):
                        smooth_streams_program = cls._find_best_matching_program(smooth_streams_program)
                    else:
                        do_process_overlap = False

        return (do_process_overlap, smooth_streams_program)

    @classmethod
    def _do_programs_match(cls,
                           smooth_streams_program,
                           epg_program,
                           do_check_start_stop_times_alignment=True,
                           do_check_duration_equivalency=False,
                           do_calculate_title_sub_title_ratio=True):
        if cls._is_program_in_ignored_epg_program_match_table(epg_program):
            return False

        if do_check_start_stop_times_alignment:
            if Utility.calculate_absolute_time_delta(smooth_streams_program.start,
                                                     epg_program.start) > MAXIMUM_TIME_DELTA_IN_SECONDS or \
                    Utility.calculate_absolute_time_delta(smooth_streams_program.stop,
                                                          epg_program.stop) > MAXIMUM_TIME_DELTA_IN_SECONDS or \
                    abs(Utility.calculate_absolute_time_delta(smooth_streams_program.start,
                                                              smooth_streams_program.stop) -
                        Utility.calculate_absolute_time_delta(epg_program.start,
                                                              epg_program.stop)) > 2 * MAXIMUM_TIME_DELTA_IN_SECONDS:
                return False
            elif not do_calculate_title_sub_title_ratio:
                return True

        if do_check_duration_equivalency:
            if Utility.calculate_absolute_time_delta(smooth_streams_program.start, smooth_streams_program.stop) != \
                    Utility.calculate_absolute_time_delta(epg_program.start, epg_program.stop):
                return False
            elif not do_calculate_title_sub_title_ratio:
                return True

        match_tuples = cls._create_match_tuples(smooth_streams_program, epg_program)
        if cls._is_match_found(smooth_streams_program, epg_program, match_tuples, do_perform_safe_match=True):
            return True
        elif do_check_start_stop_times_alignment and \
                cls._is_match_found(smooth_streams_program, epg_program, match_tuples, do_perform_safe_match=False):
            return True

        return False

    @classmethod
    def _does_program_match_ignored_smooth_streams_program_pattern(cls, smooth_streams_program):
        ignored_smooth_streams_program_pattern_records = cls._query_ignored_smooth_streams_program_pattern_table()
        if ignored_smooth_streams_program_pattern_records and re.search(r'|'.join(
                ['({0})'.format(ignored_smooth_streams_program_pattern_record['smooth_streams_program_pattern']) for
                 ignored_smooth_streams_program_pattern_record in ignored_smooth_streams_program_pattern_records]),
                smooth_streams_program.titles[0]['value']):
            logger.debug('SmoothStreams program matched a pattern in ignored_smooth_streams_program_pattern')

            return True

        return False

    @classmethod
    def _find_best_matching_program(cls, smooth_streams_program):
        did_apply_start_stop_time_changes = False
        potential_match_tuples = []

        matched_program = cls._find_forced_matched_program(smooth_streams_program)

        if matched_program is None:
            matched_program = cls._find_pattern_matched_program(smooth_streams_program)

        if matched_program is None:
            potential_match_tuples = cls._create_potential_match_tuples(
                cls._create_program_query_strings(smooth_streams_program))

            matched_program = cls._determine_matching_program(smooth_streams_program,
                                                              potential_match_tuples,
                                                              do_check_same_channel=True,
                                                              do_check_start_stop_times_alignment=True,
                                                              do_check_duration_equivalency=False)
        if matched_program is None:
            matched_program = cls._determine_matching_program(smooth_streams_program,
                                                              potential_match_tuples,
                                                              do_check_same_channel=False,
                                                              do_check_start_stop_times_alignment=True,
                                                              do_check_duration_equivalency=False)

        if matched_program is None:
            matched_program = cls._determine_matching_program(smooth_streams_program,
                                                              potential_match_tuples,
                                                              do_check_same_channel=True,
                                                              do_check_start_stop_times_alignment=False,
                                                              do_check_duration_equivalency=True)

            if matched_program is not None:
                did_apply_start_stop_time_changes = True

        if matched_program is None:
            matched_program = cls._determine_matching_program(smooth_streams_program,
                                                              potential_match_tuples,
                                                              do_check_same_channel=False,
                                                              do_check_start_stop_times_alignment=False,
                                                              do_check_duration_equivalency=True)

            if matched_program is not None:
                did_apply_start_stop_time_changes = True

        if matched_program is not None:
            logger.debug(
                'SmoothStreams program match processed{0}\n'
                'From\n'
                '  Title     => {1}\n'
                '  Start     => {2}\n'
                '  Stop      => {3}\n'
                'To\n'
                '  Title     => {4}\n'
                '{5}'
                '  Start     => {6}\n'
                '  Stop      => {7}'.format(
                    ' with start/stop time changes'
                    if did_apply_start_stop_time_changes
                    else '',
                    smooth_streams_program.titles[0]['value'],
                    smooth_streams_program.start,
                    smooth_streams_program.stop,
                    matched_program.titles[0]['value'],
                    '  Sub-Title => {0}\n'.format(matched_program.sub_titles[0]['value'])
                    if matched_program.sub_titles
                    else '',
                    matched_program.start,
                    matched_program.stop))

            return matched_program

        cls._insert_into_failed_program_match_table(smooth_streams_program)

        logger.debug('Failed to match sports program\n'
                     '  Title     => {0}\n'
                     '  Start     => {1}\n'
                     '  Stop      => {2}'.format(smooth_streams_program.titles[0]['value'],
                                                 smooth_streams_program.start,
                                                 smooth_streams_program.stop))

        return smooth_streams_program

    @classmethod
    def _find_forced_matched_program(cls, smooth_streams_program):
        forced_matched_program = None

        forced_program_match_records = cls._query_forced_program_match_table(smooth_streams_program)
        if forced_program_match_records:
            epg_program_title = forced_program_match_records[0]['epg_program_title']
            epg_program_sub_title = forced_program_match_records[0]['epg_program_sub_title']
            epg_program_channel = forced_program_match_records[0]['epg_program_channel']
            epg_program_start = forced_program_match_records[0]['epg_program_start']
            epg_program_stop = forced_program_match_records[0]['epg_program_stop']

            if not epg_program_sub_title:
                epg_program_sub_title = None

            potential_matching_program_key = None
            if epg_program_title in cls._parsed_programs_map:
                potential_matching_program_key = epg_program_title
            elif epg_program_sub_title in cls._parsed_programs_map:
                potential_matching_program_key = epg_program_sub_title

            if potential_matching_program_key:
                for potential_matching_program in cls._parsed_programs_map[potential_matching_program_key]:
                    if potential_matching_program.has_sub_titles():
                        potential_matching_program_sub_title = \
                            potential_matching_program.sub_titles[0]['value']
                    else:
                        potential_matching_program_sub_title = None

                    if epg_program_title == potential_matching_program.titles[0]['value'] and \
                            epg_program_sub_title == potential_matching_program_sub_title and \
                            epg_program_channel == potential_matching_program.channel and \
                            datetime.strptime(re.sub(r'\+00:00', '+0000', epg_program_start),
                                              '%Y-%m-%d %H:%M:%S%z') == potential_matching_program.start and \
                            datetime.strptime(re.sub(r'\+00:00', '+0000', epg_program_stop),
                                              '%Y-%m-%d %H:%M:%S%z') == potential_matching_program.stop:

                        if smooth_streams_program.start == potential_matching_program.start and \
                                smooth_streams_program.stop == potential_matching_program.stop:
                            forced_matched_program = potential_matching_program

                        else:
                            forced_matched_program = copy.deepcopy(potential_matching_program)
                            forced_matched_program.start = smooth_streams_program.start
                            forced_matched_program.stop = smooth_streams_program.stop

                        logger.debug('Forced program match detected')

                        return forced_matched_program

        return forced_matched_program

    @classmethod
    def _find_pattern_matched_program(cls, smooth_streams_program):
        pattern_matched_program = None

        pattern_program_match_records = cls._query_pattern_program_match_table(smooth_streams_program)
        if pattern_program_match_records:
            epg_program_pattern = pattern_program_match_records[0]['epg_program_pattern']

            pattern_matching_program_keys = [epg_program_title_sub_title
                                             for epg_program_title_sub_title in cls._parsed_programs_map
                                             if re.search(r'{0}'.format(epg_program_pattern),
                                                          epg_program_title_sub_title)]

            for pattern_matching_program_key in pattern_matching_program_keys:
                for potential_matching_program in cls._parsed_programs_map[pattern_matching_program_key]:
                    if cls._do_programs_match(smooth_streams_program,
                                              potential_matching_program,
                                              do_calculate_title_sub_title_ratio=False):
                        if smooth_streams_program.start == potential_matching_program.start and \
                                smooth_streams_program.stop == potential_matching_program.stop:
                            pattern_matched_program = potential_matching_program

                        else:
                            pattern_matched_program = copy.deepcopy(potential_matching_program)
                            pattern_matched_program.start = smooth_streams_program.start
                            pattern_matched_program.stop = smooth_streams_program.stop

                        logger.debug('Pattern program match detected')

                        return pattern_matched_program

        return pattern_matched_program

    @classmethod
    def _force_merge_smooth_streams_epg(cls):
        for channel in cls._smooth_streams_epg.values():
            logger.debug('Reconciling channel\n'
                         'Name   => {0}\n'
                         'Number => {1}'.format(channel.display_names[0]['value'], channel.id))

            epg_programs = cls._epg[channel.id].programs

            for smooth_streams_program in channel.programs:
                is_smooth_streams_program_processed = False

                for epg_program in cls._epg[channel.id].programs:
                    if smooth_streams_program.start < epg_program.start:
                        if smooth_streams_program.stop <= epg_program.start:
                            if not is_smooth_streams_program_processed:
                                logger.debug(
                                    'No overlap detected\n'
                                    'Sports program\n'
                                    '  Title     => {0}\n'
                                    '  Start     => {1}\n'
                                    '  Stop      => {2}'.format(
                                        smooth_streams_program.titles[0]['value'],
                                        smooth_streams_program.start,
                                        smooth_streams_program.stop))

                                bisect.insort(epg_programs, smooth_streams_program)
                                is_smooth_streams_program_processed = True

                                logger.debug(
                                    'No overlap processed\n'
                                    'SmoothStreams program inserted\n'
                                    '  Title     => {0}\n'
                                    '  Start     => {1}\n'
                                    '  Stop      => {2}'.format(
                                        smooth_streams_program.titles[0]['value'],
                                        smooth_streams_program.start,
                                        smooth_streams_program.stop))
                            else:
                                logger.debug(
                                    'Unexpected case #1 detected\n'
                                    'Sports program\n'
                                    '  Title     => {0}\n'
                                    '  Start     => {1}\n'
                                    '  Stop      => {2}\n'
                                    'EPG program\n'
                                    '  Title     => {3}\n'
                                    '{4}'
                                    '  Start     => {5}\n'
                                    '  Stop      => {6}'.format(
                                        smooth_streams_program.titles[0]['value'],
                                        smooth_streams_program.start,
                                        smooth_streams_program.stop,
                                        epg_program.titles[0]['value'],
                                        '  Sub-Title => {0}\n'.format(epg_program.sub_titles[0]['value'])
                                        if epg_program.sub_titles else '',
                                        epg_program.start,
                                        epg_program.stop))
                            break
                        elif smooth_streams_program.stop < epg_program.stop:
                            if is_smooth_streams_program_processed:
                                logger.debug(
                                    'Overlap continuation detected\n'
                                    '  Type      => Overflow\n'
                                    '  Alignment => Start to before stop\n'
                                    'Sports program\n'
                                    '  Title     => {0}\n'
                                    '  Start     => {1}\n'
                                    '  Stop      => {2}\n'
                                    'EPG program\n'
                                    '  Title     => {3}\n'
                                    '{4}'
                                    '  Start     => {5}\n'
                                    '  Stop      => {6}'.format(
                                        smooth_streams_program.titles[0]['value'],
                                        smooth_streams_program.start,
                                        smooth_streams_program.stop,
                                        epg_program.titles[0]['value'],
                                        '  Sub-Title => {0}\n'.format(epg_program.sub_titles[0]['value'])
                                        if epg_program.sub_titles else '',
                                        epg_program.start,
                                        epg_program.stop))

                                epg_program.start = smooth_streams_program.stop

                                logger.debug(
                                    'Overlap continuation processed\n'
                                    '  Type      => Overflow\n'
                                    '  Alignment => Start to before stop\n'
                                    'Sports program\n'
                                    '  Title     => {0}\n'
                                    '  Start     => {1}\n'
                                    '  Stop      => {2}\n'
                                    'EPG program modified\n'
                                    '  Title     => {3}\n'
                                    '{4}'
                                    '  Start     => {5}\n'
                                    '  Stop      => {6}'.format(
                                        smooth_streams_program.titles[0]['value'],
                                        smooth_streams_program.start,
                                        smooth_streams_program.stop,
                                        epg_program.titles[0]['value'],
                                        '  Sub-Title => {0}\n'.format(epg_program.sub_titles[0]['value'])
                                        if epg_program.sub_titles else '',
                                        epg_program.start,
                                        epg_program.stop))

                                break
                            else:
                                logger.debug(
                                    'Overlap continuation detected\n'
                                    '  Type      => Overflow\n'
                                    '  Alignment => Start to before stop\n'
                                    'Sports program\n'
                                    '  Title     => {0}\n'
                                    '  Start     => {1}\n'
                                    '  Stop      => {2}\n'
                                    'EPG program\n'
                                    '  Title     => {3}\n'
                                    '{4}'
                                    '  Start     => {5}\n'
                                    '  Stop      => {6}'.format(
                                        smooth_streams_program.titles[0]['value'],
                                        smooth_streams_program.start,
                                        smooth_streams_program.stop,
                                        epg_program.titles[0]['value'],
                                        '  Sub-Title => {0}\n'.format(epg_program.sub_titles[0]['value'])
                                        if epg_program.sub_titles else '',
                                        epg_program.start,
                                        epg_program.stop))

                                epg_program.start = smooth_streams_program.stop
                                bisect.insort(epg_programs, smooth_streams_program)
                                is_smooth_streams_program_processed = True

                                logger.debug(
                                    'Overlap continuation processed\n'
                                    '  Type      => Overflow\n'
                                    '  Alignment => Start to before stop\n'
                                    'SmoothStreams program inserted\n'
                                    '  Title     => {0}\n'
                                    '  Start     => {1}\n'
                                    '  Stop      => {2}\n'
                                    'EPG program removed\n'
                                    '  Title     => {3}\n'
                                    '{4}'
                                    '  Start     => {5}\n'
                                    '  Stop      => {6}'.format(
                                        smooth_streams_program.titles[0]['value'],
                                        smooth_streams_program.start,
                                        smooth_streams_program.stop,
                                        epg_program.titles[0]['value'],
                                        '  Sub-Title => {0}\n'.format(epg_program.sub_titles[0]['value'])
                                        if epg_program.sub_titles else '',
                                        epg_program.start,
                                        epg_program.stop))

                                break
                        elif smooth_streams_program.stop == epg_program.stop:
                            if is_smooth_streams_program_processed:
                                logger.debug(
                                    'Overlap continuation detected\n'
                                    '  Type      => Overflow\n'
                                    '  Alignment => Start to stop\n'
                                    'Sports program\n'
                                    '  Title     => {0}\n'
                                    '  Start     => {1}\n'
                                    '  Stop      => {2}\n'
                                    'EPG program\n'
                                    '  Title     => {3}\n'
                                    '{4}'
                                    '  Start     => {5}\n'
                                    '  Stop      => {6}'.format(
                                        smooth_streams_program.titles[0]['value'],
                                        smooth_streams_program.start,
                                        smooth_streams_program.stop,
                                        epg_program.titles[0]['value'],
                                        '  Sub-Title => {0}\n'.format(epg_program.sub_titles[0]['value'])
                                        if epg_program.sub_titles else '',
                                        epg_program.start,
                                        epg_program.stop))

                                epg_programs.remove(epg_program)

                                logger.debug(
                                    'Overlap continuation processed\n'
                                    '  Type      => Overflow\n'
                                    '  Alignment => Start to stop\n'
                                    'Sports program\n'
                                    '  Title     => {0}\n'
                                    '  Start     => {1}\n'
                                    '  Stop      => {2}\n'
                                    'EPG program removed\n'
                                    '  Title     => {3}\n'
                                    '{4}'
                                    '  Start     => {5}\n'
                                    '  Stop      => {6}'.format(
                                        smooth_streams_program.titles[0]['value'],
                                        smooth_streams_program.start,
                                        smooth_streams_program.stop,
                                        epg_program.titles[0]['value'],
                                        '  Sub-Title => {0}\n'.format(epg_program.sub_titles[0]['value'])
                                        if epg_program.sub_titles else '',
                                        epg_program.start,
                                        epg_program.stop))

                                break
                            else:
                                logger.debug(
                                    'Overlap continuation detected\n'
                                    '  Type      => Overflow\n'
                                    '  Alignment => Start to stop\n'
                                    'Sports program\n'
                                    '  Title     => {0}\n'
                                    '  Start     => {1}\n'
                                    '  Stop      => {2}\n'
                                    'EPG program\n'
                                    '  Title     => {3}\n'
                                    '{4}'
                                    '  Start     => {5}\n'
                                    '  Stop      => {6}'.format(
                                        smooth_streams_program.titles[0]['value'],
                                        smooth_streams_program.start,
                                        smooth_streams_program.stop,
                                        epg_program.titles[0]['value'],
                                        '  Sub-Title => {0}\n'.format(epg_program.sub_titles[0]['value'])
                                        if epg_program.sub_titles else '',
                                        epg_program.start,
                                        epg_program.stop))

                                epg_programs.remove(epg_program)
                                bisect.insort(epg_programs, smooth_streams_program)
                                is_smooth_streams_program_processed = True

                                logger.debug(
                                    'Overlap continuation processed\n'
                                    '  Type      => Overflow\n'
                                    '  Alignment => Start to stop\n'
                                    'SmoothStreams program inserted\n'
                                    '  Title     => {0}\n'
                                    '  Start     => {1}\n'
                                    '  Stop      => {2}\n'
                                    'EPG program removed\n'
                                    '  Title     => {3}\n'
                                    '{4}'
                                    '  Start     => {5}\n'
                                    '  Stop      => {6}'.format(
                                        smooth_streams_program.titles[0]['value'],
                                        smooth_streams_program.start,
                                        smooth_streams_program.stop,
                                        epg_program.titles[0]['value'],
                                        '  Sub-Title => {0}\n'.format(epg_program.sub_titles[0]['value'])
                                        if epg_program.sub_titles else '',
                                        epg_program.start,
                                        epg_program.stop))

                                break
                        elif smooth_streams_program.stop > epg_program.stop:
                            if is_smooth_streams_program_processed:
                                logger.debug(
                                    'Overlap continuation detected\n'
                                    '  Type      => Overflow\n'
                                    '  Alignment => Start to stop\n'
                                    'Sports program\n'
                                    '  Title     => {0}\n'
                                    '  Start     => {1}\n'
                                    '  Stop      => {2}\n'
                                    'EPG program\n'
                                    '  Title     => {3}\n'
                                    '{4}'
                                    '  Start     => {5}\n'
                                    '  Stop      => {6}'.format(
                                        smooth_streams_program.titles[0]['value'],
                                        smooth_streams_program.start,
                                        smooth_streams_program.stop,
                                        epg_program.titles[0]['value'],
                                        '  Sub-Title => {0}\n'.format(epg_program.sub_titles[0]['value'])
                                        if epg_program.sub_titles else '',
                                        epg_program.start,
                                        epg_program.stop))

                                epg_programs.remove(epg_program)

                                logger.debug(
                                    'Overlap continuation processed\n'
                                    '  Type      => Overflow\n'
                                    '  Alignment => Start to stop\n'
                                    'Sports program\n'
                                    '  Title     => {0}\n'
                                    '  Start     => {1}\n'
                                    '  Stop      => {2}\n'
                                    'EPG program removed\n'
                                    '  Title     => {3}\n'
                                    '{4}'
                                    '  Start     => {5}\n'
                                    '  Stop      => {6}'.format(
                                        smooth_streams_program.titles[0]['value'],
                                        smooth_streams_program.start,
                                        smooth_streams_program.stop,
                                        epg_program.titles[0]['value'],
                                        '  Sub-Title => {0}\n'.format(epg_program.sub_titles[0]['value'])
                                        if epg_program.sub_titles else '',
                                        epg_program.start,
                                        epg_program.stop))
                            else:
                                logger.debug(
                                    'Overlap continuation detected\n'
                                    '  Type      => Overflow\n'
                                    '  Alignment => Start to stop\n'
                                    'Sports program\n'
                                    '  Title     => {0}\n'
                                    '  Start     => {1}\n'
                                    '  Stop      => {2}\n'
                                    'EPG program\n'
                                    '  Title     => {3}\n'
                                    '{4}'
                                    '  Start     => {5}\n'
                                    '  Stop      => {6}'.format(
                                        smooth_streams_program.titles[0]['value'],
                                        smooth_streams_program.start,
                                        smooth_streams_program.stop,
                                        epg_program.titles[0]['value'],
                                        '  Sub-Title => {0}\n'.format(epg_program.sub_titles[0]['value'])
                                        if epg_program.sub_titles else '',
                                        epg_program.start,
                                        epg_program.stop))

                                epg_programs.remove(epg_program)
                                bisect.insort(epg_programs, smooth_streams_program)
                                is_smooth_streams_program_processed = True

                                logger.debug(
                                    'Overlap continuation processed\n'
                                    '  Type      => Overflow\n'
                                    '  Alignment => Start to stop\n'
                                    'SmoothStreams program inserted\n'
                                    '  Title     => {0}\n'
                                    '  Start     => {1}\n'
                                    '  Stop      => {2}\n'
                                    'EPG program removed\n'
                                    '  Title     => {3}\n'
                                    '{4}'
                                    '  Start     => {5}\n'
                                    '  Stop      => {6}'.format(
                                        smooth_streams_program.titles[0]['value'],
                                        smooth_streams_program.start,
                                        smooth_streams_program.stop,
                                        epg_program.titles[0]['value'],
                                        '  Sub-Title => {0}\n'.format(epg_program.sub_titles[0]['value'])
                                        if epg_program.sub_titles else '',
                                        epg_program.start,
                                        epg_program.stop))

                                break
                        else:
                            logger.debug(
                                'Unexpected case #2 detected\n'
                                'Sports program\n'
                                '  Title     => {0}\n'
                                '  Start     => {1}\n'
                                '  Stop      => {2}\n'
                                'EPG program\n'
                                '  Title     => {3}\n'
                                '{4}'
                                '  Start     => {5}\n'
                                '  Stop      => {6}'.format(
                                    smooth_streams_program.titles[0]['value'],
                                    smooth_streams_program.start,
                                    smooth_streams_program.stop,
                                    epg_program.titles[0]['value'],
                                    '  Sub-Title => {0}\n'.format(epg_program.sub_titles[0]['value'])
                                    if epg_program.sub_titles else '',
                                    epg_program.start,
                                    epg_program.stop))
                    elif smooth_streams_program.start == epg_program.start:
                        if smooth_streams_program.stop < epg_program.stop:
                            logger.debug(
                                'Overlap detected\n'
                                '  Type      => Partial\n'
                                '  Alignment => Start\n'
                                'Sports program\n'
                                '  Title     => {0}\n'
                                '  Start     => {1}\n'
                                '  Stop      => {2}\n'
                                'EPG program\n'
                                '  Title     => {3}\n'
                                '{4}'
                                '  Start     => {5}\n'
                                '  Stop      => {6}'.format(
                                    smooth_streams_program.titles[0]['value'],
                                    smooth_streams_program.start,
                                    smooth_streams_program.stop,
                                    epg_program.titles[0]['value'],
                                    '  Sub-Title => {0}\n'.format(epg_program.sub_titles[0]['value'])
                                    if epg_program.sub_titles else '',
                                    epg_program.start,
                                    epg_program.stop))

                            epg_program.start = smooth_streams_program.stop
                            bisect.insort(epg_programs, smooth_streams_program)
                            is_smooth_streams_program_processed = True

                            logger.debug(
                                'Overlap processed\n'
                                '  Type      => Partial\n'
                                '  Alignment => Start\n'
                                'SmoothStreams program inserted\n'
                                '  Title     => {0}\n'
                                '  Start     => {1}\n'
                                '  Stop      => {2}\n'
                                'EPG program modified\n'
                                '  Title     => {3}\n'
                                '{4}'
                                '  Start     => {5}\n'
                                '  Stop      => {6}'.format(
                                    smooth_streams_program.titles[0]['value'],
                                    smooth_streams_program.start,
                                    smooth_streams_program.stop,
                                    epg_program.titles[0]['value'],
                                    '  Sub-Title => {0}\n'.format(epg_program.sub_titles[0]['value'])
                                    if epg_program.sub_titles else '',
                                    epg_program.start,
                                    epg_program.stop))

                            break
                        elif smooth_streams_program.stop == epg_program.stop:
                            logger.debug(
                                'Overlap detected\n'
                                '  Type      => Full\n'
                                '  Alignment => Start to stop\n'
                                'Sports program\n'
                                '  Title     => {0}\n'
                                '  Start     => {1}\n'
                                '  Stop      => {2}\n'
                                'EPG program\n'
                                '  Title     => {3}\n'
                                '{4}'
                                '  Start     => {5}\n'
                                '  Stop      => {6}'.format(
                                    smooth_streams_program.titles[0]['value'],
                                    smooth_streams_program.start,
                                    smooth_streams_program.stop,
                                    epg_program.titles[0]['value'],
                                    '  Sub-Title => {0}\n'.format(epg_program.sub_titles[0]['value'])
                                    if epg_program.sub_titles else '',
                                    epg_program.start,
                                    epg_program.stop))

                            epg_programs.remove(epg_program)
                            bisect.insort(epg_programs, smooth_streams_program)
                            is_smooth_streams_program_processed = True

                            logger.debug(
                                'Overlap processed\n'
                                '  Type      => Full\n'
                                '  Alignment => Start to stop\n'
                                'SmoothStreams program inserted\n'
                                '  Title     => {0}\n'
                                '  Start     => {1}\n'
                                '  Stop      => {2}\n'
                                'EPG program removed\n'
                                '  Title     => {3}\n'
                                '{4}'
                                '  Start     => {5}\n'
                                '  Stop      => {6}'.format(
                                    smooth_streams_program.titles[0]['value'],
                                    smooth_streams_program.start,
                                    smooth_streams_program.stop,
                                    epg_program.titles[0]['value'],
                                    '  Sub-Title => {0}\n'.format(epg_program.sub_titles[0]['value'])
                                    if epg_program.sub_titles else '',
                                    epg_program.start,
                                    epg_program.stop))

                            break
                        elif smooth_streams_program.stop > epg_program.stop:
                            logger.debug(
                                'Overlap detected\n'
                                '  Type      => Overflow\n'
                                '  Alignment => Start to after stop\n'
                                'Sports program\n'
                                '  Title     => {0}\n'
                                '  Start     => {1}\n'
                                '  Stop      => {2}\n'
                                'EPG program\n'
                                '  Title     => {3}\n'
                                '{4}'
                                '  Start     => {5}\n'
                                '  Stop      => {6}'.format(
                                    smooth_streams_program.titles[0]['value'],
                                    smooth_streams_program.start,
                                    smooth_streams_program.stop,
                                    epg_program.titles[0]['value'],
                                    '  Sub-Title => {0}\n'.format(epg_program.sub_titles[0]['value'])
                                    if epg_program.sub_titles else '',
                                    epg_program.start,
                                    epg_program.stop))

                            epg_programs.remove(epg_program)
                            bisect.insort(epg_programs, smooth_streams_program)
                            is_smooth_streams_program_processed = True

                            logger.debug(
                                'Overlap processed\n'
                                '  Type      => Overflow\n'
                                '  Alignment => Start to after stop\n'
                                'SmoothStreams program inserted\n'
                                '  Title     => {0}\n'
                                '  Start     => {1}\n'
                                '  Stop      => {2}\n'
                                'EPG program removed\n'
                                '  Title     => {3}\n'
                                '{4}'
                                '  Start     => {5}\n'
                                '  Stop      => {6}'.format(
                                    smooth_streams_program.titles[0]['value'],
                                    smooth_streams_program.start,
                                    smooth_streams_program.stop,
                                    epg_program.titles[0]['value'],
                                    '  Sub-Title => {0}\n'.format(epg_program.sub_titles[0]['value'])
                                    if epg_program.sub_titles else '',
                                    epg_program.start,
                                    epg_program.stop))
                    elif smooth_streams_program.start > epg_program.start:
                        if smooth_streams_program.start >= epg_program.stop:
                            continue
                        elif smooth_streams_program.stop < epg_program.stop:
                            logger.debug(
                                'Overlap detected\n'
                                '  Type      => Partial\n'
                                '  Alignment => After start to before stop\n'
                                'Sports program\n'
                                '  Title     => {0}\n'
                                '  Start     => {1}\n'
                                '  Stop      => {2}\n'
                                'EPG program\n'
                                '  Title     => {3}\n'
                                '{4}'
                                '  Start     => {5}\n'
                                '  Stop      => {6}'.format(
                                    smooth_streams_program.titles[0]['value'],
                                    smooth_streams_program.start,
                                    smooth_streams_program.stop,
                                    epg_program.titles[0]['value'],
                                    '  Sub-Title => {0}\n'.format(epg_program.sub_titles[0]['value'])
                                    if epg_program.sub_titles else '',
                                    epg_program.start,
                                    epg_program.stop))

                            new_epg_program = copy.deepcopy(epg_program)

                            epg_program.stop = smooth_streams_program.start
                            bisect.insort(epg_programs, smooth_streams_program)
                            is_smooth_streams_program_processed = True

                            new_epg_program.start = smooth_streams_program.stop
                            bisect.insort(epg_programs, new_epg_program)

                            logger.debug(
                                'Overlap processed\n'
                                '  Type      => Partial\n'
                                '  Alignment => After start to before stop\n'
                                'SmoothStreams program inserted\n'
                                '  Title     => {0}\n'
                                '  Start     => {1}\n'
                                '  Stop      => {2}\n'
                                'EPG program modified\n'
                                '  Title     => {3}\n'
                                '{4}'
                                '  Start     => {5}\n'
                                '  Stop      => {6}\n'
                                'EPG program inserted\n'
                                '  Title     => {7}\n'
                                '{8}'
                                '  Start     => {9}\n'
                                '  Stop      => {10}'.format(
                                    smooth_streams_program.titles[0]['value'],
                                    smooth_streams_program.start,
                                    smooth_streams_program.stop,
                                    epg_program.titles[0]['value'],
                                    '  Sub-Title => {0}\n'.format(epg_program.sub_titles[0]['value'])
                                    if epg_program.sub_titles else '',
                                    epg_program.start,
                                    epg_program.stop,
                                    new_epg_program.titles[0]['value'],
                                    '  Sub-Title => {0}\n'.format(new_epg_program.sub_titles[0]['value'])
                                    if new_epg_program.sub_titles else '',
                                    new_epg_program.start,
                                    new_epg_program.stop))

                            break
                        elif smooth_streams_program.stop == epg_program.stop:
                            logger.debug(
                                'Overlap detected\n'
                                '  Type      => Partial\n'
                                '  Alignment => After start to stop\n'
                                'Sports program\n'
                                '  Title     => {0}\n'
                                '  Start     => {1}\n'
                                '  Stop      => {2}\n'
                                'EPG program\n'
                                '  Title     => {3}\n'
                                '{4}'
                                '  Start     => {5}\n'
                                '  Stop      => {6}'.format(
                                    smooth_streams_program.titles[0]['value'],
                                    smooth_streams_program.start,
                                    smooth_streams_program.stop,
                                    epg_program.titles[0]['value'],
                                    '  Sub-Title => {0}\n'.format(epg_program.sub_titles[0]['value'])
                                    if epg_program.sub_titles else '',
                                    epg_program.start,
                                    epg_program.stop))

                            epg_program.stop = smooth_streams_program.start
                            bisect.insort(epg_programs, smooth_streams_program)
                            is_smooth_streams_program_processed = True

                            logger.debug(
                                'Overlap processed\n'
                                '  Type      => Partial\n'
                                '  Alignment => After start to stop\n'
                                'SmoothStreams program inserted\n'
                                '  Title     => {0}\n'
                                '  Start     => {1}\n'
                                '  Stop      => {2}\n'
                                'EPG program modified\n'
                                '  Title     => {3}\n'
                                '{4}'
                                '  Start     => {5}\n'
                                '  Stop      => {6}'.format(
                                    smooth_streams_program.titles[0]['value'],
                                    smooth_streams_program.start,
                                    smooth_streams_program.stop,
                                    epg_program.titles[0]['value'],
                                    '  Sub-Title => {0}\n'.format(epg_program.sub_titles[0]['value'])
                                    if epg_program.sub_titles else '',
                                    epg_program.start,
                                    epg_program.stop))

                            break
                        elif smooth_streams_program.stop > epg_program.stop:
                            logger.debug(
                                'Overlap detected\n'
                                '  Type      => Overflow\n'
                                '  Alignment => After start to after stop\n'
                                'Sports program\n'
                                '  Title     => {0}\n'
                                '  Start     => {1}\n'
                                '  Stop      => {2}\n'
                                'EPG program\n'
                                '  Title     => {3}\n'
                                '{4}'
                                '  Start     => {5}\n'
                                '  Stop      => {6}'.format(
                                    smooth_streams_program.titles[0]['value'],
                                    smooth_streams_program.start,
                                    smooth_streams_program.stop,
                                    epg_program.titles[0]['value'],
                                    '  Sub-Title => {0}\n'.format(epg_program.sub_titles[0]['value'])
                                    if epg_program.sub_titles else '',
                                    epg_program.start,
                                    epg_program.stop))

                            epg_program.stop = smooth_streams_program.start
                            bisect.insort(epg_programs, smooth_streams_program)
                            is_smooth_streams_program_processed = True

                            logger.debug(
                                'Overlap processed\n'
                                '  Type      => Overflow\n'
                                '  Alignment => After start to after stop\n'
                                'SmoothStreams program iserted\n'
                                '  Title     => {0}\n'
                                '  Start     => {1}\n'
                                '  Stop      => {2}\n'
                                'EPG program modified\n'
                                '  Title     => {3}\n'
                                '{4}'
                                '  Start     => {5}\n'
                                '  Stop      => {6}'.format(
                                    smooth_streams_program.titles[0]['value'],
                                    smooth_streams_program.start,
                                    smooth_streams_program.stop,
                                    epg_program.titles[0]['value'],
                                    '  Sub-Title => {0}\n'.format(epg_program.sub_titles[0]['value'])
                                    if epg_program.sub_titles else '',
                                    epg_program.start,
                                    epg_program.stop))
                        else:
                            logger.debug(
                                'Unexpected case #3 detected\n'
                                'Sports program\n'
                                '  Title     => {0}\n'
                                '  Start     => {1}\n'
                                '  Stop      => {2}\n'
                                'EPG program\n'
                                '  Title     => {3}\n'
                                '{4}'
                                '  Start     => {5}\n'
                                '  Stop      => {6}'.format(
                                    smooth_streams_program.titles[0]['value'],
                                    smooth_streams_program.start,
                                    smooth_streams_program.stop,
                                    epg_program.titles[0]['value'],
                                    '  Sub-Title => {0}\n'.format(epg_program.sub_titles[0]['value'])
                                    if epg_program.sub_titles else '',
                                    epg_program.start,
                                    epg_program.stop))

                if not is_smooth_streams_program_processed:
                    bisect.insort(epg_programs, smooth_streams_program)

                    logger.debug('No overlap detected\n'
                                 'SmoothStreams program inserted\n'
                                 '  Title     => {0}\n'
                                 '  Start     => {1}\n'
                                 '  Stop      => {2}'.format(smooth_streams_program.titles[0]['value'],
                                                             smooth_streams_program.start,
                                                             smooth_streams_program.stop))

            cls._epg[channel.id].programs = epg_programs

    @classmethod
    def _generate_epg(cls,
                      output_directory_path,
                      is_forced,
                      number_of_days,
                      do_concatenate_sub_title_to_title=False,
                      do_generate_all_elements=True):
        cutoff_date_time_in_utc = cls._startup_date_time_in_utc.replace(
            hour=0,
            minute=0,
            second=0,
            microsecond=0) + timedelta(days=number_of_days + 1)

        channels_output = []
        programs_output = []

        for channel in cls._epg.values():
            channels_output.append('\t<channel id="{0}">\n'.format(channel.id))

            # <editor-fold desc="display-name">
            for display_name in channel.display_names:
                channels_output.append('\t\t<display-name{0}>{1}</display-name>\n'.format(
                    ' lang="{0}"'.format(saxutils.escape(display_name['language']))
                    if display_name['language'] is not None
                    else '',
                    saxutils.escape(display_name['value'])))

            channels_output.append('\t\t<display-name>{0}</display-name>\n'.format(channel.id))
            # </editor-fold>

            # <editor-fold desc="icon">
            for icon in channel.icons:
                channels_output.append('\t\t<icon {0}src="{1}"{2} />\n'.format(
                    'height="{0}" '.format(saxutils.escape(icon['height']))
                    if icon['height'] is not None
                    else '',
                    saxutils.escape(icon['source']),
                    ' width="{0}"'.format(saxutils.escape(icon['width']))
                    if icon['width'] is not None
                    else ''))
            # </editor-fold>

            # <editor-fold desc="url">
            for url in channel.urls:
                channels_output.append('\t\t<url>{0}</url>\n'.format(saxutils.escape(url['value'])))
            # </editor-fold>

            channels_output.append('\t</channel>\n')

            for program in channel.programs:
                if cutoff_date_time_in_utc > program.start and cls._startup_date_time_in_utc < program.stop:
                    programs_output.append('\t<programme start="{0}"{1}{2}{3}{4}{5} channel="{6}"{7}>\n'.format(
                        saxutils.escape(program.start.astimezone(pytz.utc).strftime('%Y%m%d%H%M%S %z')),
                        ' stop="{0}"'.format(
                            saxutils.escape(program.stop.astimezone(pytz.utc).strftime('%Y%m%d%H%M%S %z')))
                        if program.stop is not None
                        else '',
                        ' pdc-start="{0}"'.format(saxutils.escape(program.pdc_start))
                        if program.pdc_start is not None
                        else '',
                        ' vps-start="{0}"'.format(saxutils.escape(program.vps_start))
                        if program.vps_start is not None
                        else '',
                        ' showview="{0}"'.format(saxutils.escape(program.showview))
                        if program.showview is not None
                        else '',
                        ' videoplus="{0}"'.format(saxutils.escape(program.videoplus))
                        if program.videoplus is not None
                        else '',
                        channel.id,
                        ' clumpidx="{0}"'.format(saxutils.escape(program.clumpidx))
                        if program.clumpidx is not None
                        else ''))

                    if not do_concatenate_sub_title_to_title:
                        # <editor-fold desc="title">
                        for title in program.titles:
                            programs_output.append('\t\t<title{0}>{1}</title>\n'.format(
                                ' lang="{0}"'.format(saxutils.escape(title['language']))
                                if title['language'] is not None
                                else '',
                                saxutils.escape(re.sub(r'Live: ', '', title['value']))))
                        # </editor-fold>

                        # <editor-fold desc="sub-title">
                        for sub_title in program.sub_titles:
                            programs_output.append('\t\t<sub-title{0}>{1}</sub-title>\n'.format(
                                ' lang="{0}"'.format(saxutils.escape(sub_title['language']))
                                if sub_title['language'] is not None
                                else '',
                                saxutils.escape(sub_title['value'])))
                        # </editor-fold>
                    else:
                        # <editor-fold desc="title">
                        if program.has_sub_titles():
                            title = program.titles[0]
                            sub_title = program.sub_titles[0]

                            programs_output.append('\t\t<title{0}>{1}: {2}</title>\n'.format(
                                ' lang="{0}"'.format(saxutils.escape(title['language']))
                                if title['language'] is not None
                                else '',
                                saxutils.escape(re.sub(r'Live: ', '', title['value'])),
                                saxutils.escape(sub_title['value'])))
                        else:
                            title = program.titles[0]

                            programs_output.append('\t\t<title{0}>{1}</title>\n'.format(
                                ' lang="{0}"'.format(title['language'])
                                if title['language'] is not None
                                else '',
                                saxutils.escape(re.sub(r'Live: ', '', title['value']))))
                        # </editor-fold>

                    # <editor-fold desc="desc">
                    for description in program.descriptions:
                        programs_output.append('\t\t<desc{0}>{1}</desc>\n'.format(
                            ' lang="{0}"'.format(description['language'])
                            if description['language'] is not None
                            else '',
                            saxutils.escape(description['value'])))
                    # </editor-fold>

                    if do_generate_all_elements:
                        # <editor-fold desc="credits">
                        if program.has_credits():
                            programs_output.append('\t\t<credits>\n')

                            credits_ = program.credits
                            for director in credits_['directors']:
                                programs_output.append(
                                    '\t\t\t<director>{0}</director>\n'.format(saxutils.escape(director['value'])))
                            for actor in credits_['actors']:
                                programs_output.append('\t\t\t<actor{0}>{1}</actor>\n'.format(
                                    ' role="{0}"'.format(saxutils.escape(actor['role']))
                                    if actor['role'] is not None
                                    else '',
                                    saxutils.escape(actor['value'])))
                            for writer in credits_['writers']:
                                programs_output.append(
                                    '\t\t\t<writer>{0}</writer>\n'.format(saxutils.escape(writer['value'])))
                            for adapter in credits_['adapters']:
                                programs_output.append(
                                    '\t\t\t<adapter>{0}</adapter>\n'.format(saxutils.escape(adapter['value'])))
                            for producer in credits_['producers']:
                                programs_output.append(
                                    '\t\t\t<producer>{0}</producer>\n'.format(saxutils.escape(producer['value'])))
                            for composer in credits_['composers']:
                                programs_output.append(
                                    '\t\t\t<composer>{0}</composer>\n'.format(saxutils.escape(composer['value'])))
                            for editor in credits_['editors']:
                                programs_output.append('\t\t\t<editor>{0}</editor>\n'.format(
                                    saxutils.escape(editor['value'])))
                            for presenter in credits_['presenters']:
                                programs_output.append('\t\t\t<presenter>{0}</presenter>\n'.format(
                                    saxutils.escape(presenter['value'])))
                            for commentator in credits_['commentators']:
                                programs_output.append('\t\t\t<commentator>{0}</commentator>\n'.format(
                                    saxutils.escape(commentator['value'])))
                            for guest in credits_['guests']:
                                programs_output.append('\t\t\t<guest>{0}</guest>\n'.format(
                                    saxutils.escape(guest['value'])))

                            programs_output.append('\t\t</credits>\n')
                        # </editor-fold>

                        # <editor-fold desc="date">
                        if program.date is not None:
                            programs_output.append('\t\t<date>{0}</date>\n'.format(
                                saxutils.escape(program.date['value'])))
                        # </editor-fold>

                    # <editor-fold desc="category">
                    for category in program.categories:
                        programs_output.append('\t\t<category{0}>{1}</category>\n'.format(
                            ' lang="{0}"'.format(saxutils.escape(category['language']))
                            if category['language'] is not None
                            else '',
                            saxutils.escape(category['value'])))
                    # </editor-fold>

                    if do_generate_all_elements:
                        # <editor-fold desc="keyword">
                        for keyword in program.keywords:
                            programs_output.append('\t\t<keyword{0}>{1}</keyword>\n'.format(
                                ' lang="{0}"'.format(saxutils.escape(keyword['language']))
                                if keyword['language'] is not None
                                else '',
                                saxutils.escape(keyword['value'])))
                        # </editor-fold>

                        # <editor-fold desc="language">
                        if program.language is not None:
                            programs_output.append('\t\t<language{0}>{1}</language>\n'.format(
                                ' lang="{0}"'.format(saxutils.escape(program.language['language']))
                                if program.language['language'] is not None
                                else '',
                                saxutils.escape(program.language['value'])))
                        # </editor-fold>

                        # <editor-fold desc="orig-language">
                        if program.original_language is not None:
                            programs_output.append('\t\t<orig-language{0}>{1}</orig-language>\n'.format(
                                ' lang="{0}"'.format(saxutils.escape(program.original_language['language']))
                                if program.original_language['language'] is not None
                                else '',
                                saxutils.escape(program.original_language['value'])))
                        # </editor-fold>

                        # <editor-fold desc="length">
                        if program.length is not None:
                            programs_output.append('\t\t<length units="{0}">{1}</length>\n'.format(
                                saxutils.escape(program.length['units']),
                                saxutils.escape(program.length['value'])))
                        # </editor-fold>

                        # <editor-fold desc="icon">
                        for icon in program.icons:
                            programs_output.append('\t\t<icon {0}src="{1}"{2} />\n'.format(
                                'height="{0}" '.format(saxutils.escape(icon['height']))
                                if icon['height'] is not None
                                else '',
                                icon['source'],
                                ' width="{0}"'.format(saxutils.escape(icon['width']))
                                if icon['width'] is not None
                                else ''))
                        # </editor-fold>

                        # <editor-fold desc="url">
                        for url in program.urls:
                            programs_output.append('\t\t<url>{0}</url>\n'.format(saxutils.escape(url['value'])))
                        # </editor-fold>

                        # <editor-fold desc="country">
                        for country in program.countries:
                            programs_output.append('\t\t<country{0}>{1}</country>\n'.format(
                                ' lang="{0}"'.format(saxutils.escape(country['language']))
                                if country['language'] is not None
                                else '',
                                saxutils.escape(country['value'])))
                        # </editor-fold>

                        # <editor-fold desc="episode-num">
                        for episode_number in program.episode_numbers:
                            programs_output.append('\t\t<episode-num{0}>{1}</episode-num>\n'.format(
                                ' system="{0}"'.format(saxutils.escape(episode_number['system']))
                                if episode_number['system'] is not None
                                else '',
                                saxutils.escape(episode_number['value'])))
                        # </editor-fold>

                        # <editor-fold desc="video">
                        if program.has_video():
                            programs_output.append('\t\t<video>\n')

                            video = program.video
                            if video['present'] is not None:
                                programs_output.append('\t\t\t<present>{0}</present>\n'.format(
                                    saxutils.escape(video['present']['value'])))
                            if video['colour'] is not None:
                                programs_output.append('\t\t\t<colour>{0}</colour>\n'.format(
                                    saxutils.escape(video['colour']['value'])))
                            if video['aspect'] is not None:
                                programs_output.append('\t\t\t<aspect>{0}</aspect>\n'.format(
                                    saxutils.escape(video['aspect']['value'])))
                            if video['quality'] is not None:
                                programs_output.append('\t\t\t<quality>{0}</quality>\n'.format(
                                    saxutils.escape(video['quality']['value'])))

                            programs_output.append('\t\t</video>\n')
                        # </editor-fold>

                        # <editor-fold desc="audio">
                        if program.has_audio():
                            programs_output.append('\t\t<audio>\n')

                            audio = program.audio
                            if audio['present'] is not None:
                                programs_output.append('\t\t\t<present>{0}</present>\n'.format(
                                    saxutils.escape(audio['present']['value'])))
                            if audio['stereo'] is not None:
                                programs_output.append('\t\t\t<stereo>{0}</stereo>\n'.format(
                                    saxutils.escape(audio['stereo']['value'])))

                            programs_output.append('\t\t</audio>\n')
                        # </editor-fold>

                        # <editor-fold desc="previously-shown">
                        if program.previously_shown is not None:
                            programs_output.append('\t\t<previously-shown{0}{1} />\n'.format(
                                ' start="{0}"'.format(saxutils.escape(program.previously_shown['start']))
                                if program.previously_shown['start'] is not None
                                else '',
                                ' channel="{0}"'.format(saxutils.escape(program.previously_shown['channel']))
                                if program.previously_shown['channel'] is not None
                                else ''))
                        # </editor-fold>

                        # <editor-fold desc="premiere">
                        if program.premiere is not None:
                            programs_output.append('\t\t<premiere{0}{1}\n'.format(
                                ' lang="{0}"'.format(saxutils.escape(program.premiere['language']))
                                if program.premiere['language'] is not None
                                else '',
                                ' />' if program.premiere['value'] is None
                                else '>{0}</premiere>'.format(saxutils.escape(program.premiere['value']))))
                        # </editor-fold>

                        # <editor-fold desc="last-chance">
                        if program.last_chance is not None:
                            programs_output.append('\t\t<last-chance{0}{1}\n'.format(
                                ' lang="{0}"'.format(saxutils.escape(program.last_chance['language']))
                                if program.last_chance['language'] is not None
                                else '',
                                ' />' if program.last_chance['value'] is None
                                else '>{0}</last-chance>'.format(saxutils.escape(program.last_chance['value']))))
                        # </editor-fold>

                        # <editor-fold desc="new">
                        if program.new:
                            programs_output.append('\t\t<new />\n')
                        # </editor-fold>

                        # <editor-fold desc="subtitles">
                        for subtitles in program.subtitles:
                            programs_output.append('\t\t<subtitles{0}{1}>\n'.format(
                                ' type="{0}"'.format(saxutils.escape(subtitles['type']))
                                if subtitles['type'] is not None
                                else '',
                                ' /'
                                if 'language' not in subtitles
                                else ''))

                            if 'language' in subtitles:
                                programs_output.append('\t\t\t<language{0}>{1}</language>\n'.format(
                                    ' lang="{0}"'.format(saxutils.escape(subtitles['language']['language']))
                                    if subtitles['language']['language'] is not None
                                    else '',
                                    saxutils.escape(subtitles['language']['value'])))

                                programs_output.append('\t\t</subtitles>\n')
                        # </editor-fold>

                        # <editor-fold desc="rating">
                        for rating in program.ratings:
                            programs_output.append('\t\t<rating{0}>\n'.format(
                                ' system="{0}"'.format(saxutils.escape(rating['system']))
                                if rating['system'] is not None
                                else ''))

                            for icon in rating['icons']:
                                programs_output.append('\t\t\t<icon {0}src="{1}"{2} />\n'.format(
                                    'height="{0}" '.format(saxutils.escape(icon['height']))
                                    if icon['height'] is not None
                                    else '',
                                    saxutils.escape(icon['source']),
                                    ' width="{0}"'.format(saxutils.escape(icon['width']))
                                    if icon['width'] is not None
                                    else ''))

                            if 'value' in rating:
                                programs_output.append('\t\t\t<value>{0}</value>\n'.format(
                                    saxutils.escape(rating['value']['value'])))

                            programs_output.append('\t\t</rating>\n')
                        # </editor-fold>

                        # <editor-fold desc="star-rating">
                        for star_rating in program.star_ratings:
                            programs_output.append('\t\t<star-rating{0}>\n'.format(
                                ' system="{0}"'.format(saxutils.escape(star_rating['system']))
                                if star_rating['system'] is not None
                                else ''))

                            for icon in star_rating['icons']:
                                programs_output.append('\t\t\t<icon {0}src="{1}"{2} />\n'.format(
                                    'height="{0}" '.format(saxutils.escape(icon['height']))
                                    if icon['height'] is not None
                                    else '',
                                    saxutils.escape(icon['source']),
                                    ' width="{0}"'.format(saxutils.escape(icon['width']))
                                    if icon['width'] is not None
                                    else ''))

                            if 'value' in star_rating:
                                programs_output.append('\t\t\t<value>{0}</value>\n'.format(
                                    saxutils.escape(star_rating['value']['value'])))

                            programs_output.append('\t\t</star-rating>\n')
                        # </editor-fold>

                        # <editor-fold desc="review">
                        for review in program.reviews:
                            programs_output.append('\t\t<review type="{0}"{1}{2}{3}>{4}</review>\n'.format(
                                saxutils.escape(review['type']),
                                ' source="{0}"'.format(saxutils.escape(review['source']))
                                if review['source'] is not None
                                else '',
                                ' reviewer="{0}"'.format(saxutils.escape(review['reviewer']))
                                if review['reviewer'] is not None
                                else '',
                                ' lang="{0}"'.format(saxutils.escape(review['language']))
                                if review['language'] is not None
                                else '',
                                saxutils.escape(review['value'])))
                        # </editor-fold>

                    programs_output.append('\t</programme>\n')

        Privilege.become_privileged_user()
        Utility.write_file(
            os.path.join(output_directory_path,
                         DEFAULT_OUTPUT_XMLTV_FILE_NAME_FORMAT.format('f' if is_forced else 'r',
                                                                      'f' if do_generate_all_elements else 's',
                                                                      number_of_days)),
            '<?xml version="1.0" encoding="utf-8"?>\n'
            '<tv>\n'
            '{0}'
            '{1}'
            '</tv>\n'.format(''.join(channels_output), ''.join(programs_output)))
        Privilege.become_unprivileged_user()

    @classmethod
    def _generate_epgs(cls, output_directory_path, is_forced):
        for number_of_days in DEFAULT_OUTPUT_XMLTV_NUMBER_OF_DAYS:
            cls._generate_epg(output_directory_path, is_forced, number_of_days)
            cls._generate_epg(output_directory_path,
                              is_forced,
                              number_of_days,
                              do_concatenate_sub_title_to_title=True,
                              do_generate_all_elements=False)

    @classmethod
    def _insert_into_category_map_table(cls, smooth_streams_category, epg_category):
        sql_statement = "INSERT " \
                        "INTO category_map (smooth_streams_category, epg_category) " \
                        "VALUES (:smooth_streams_category, :epg_category)"
        try:
            Database.execute(sql_statement, {'smooth_streams_category': smooth_streams_category,
                                             'epg_category': epg_category})
            Database.commit()
        except sqlite3.IntegrityError:
            pass

    @classmethod
    def _insert_into_failed_program_match_table(cls, smooth_streams_program):
        sql_statement = "INSERT " \
                        "INTO failed_program_match (smooth_streams_program_title, smooth_streams_program_sub_title, " \
                        "smooth_streams_program_channel, smooth_streams_program_start, smooth_streams_program_stop, " \
                        "date_time_of_last_failure, number_of_occurrences, reviewed) " \
                        "VALUES (:smooth_streams_program_title, :smooth_streams_program_sub_title, " \
                        ":smooth_streams_program_channel, :smooth_streams_program_start, " \
                        ":smooth_streams_program_stop, :date_time_of_last_failure, :number_of_occurrences, :reviewed)"
        try:
            Database.execute(sql_statement,
                             {'smooth_streams_program_title': smooth_streams_program.titles[0]['value'],
                              'smooth_streams_program_sub_title': smooth_streams_program.sub_titles[0]['value']
                              if smooth_streams_program.has_sub_titles()
                              else '',
                              'smooth_streams_program_channel': smooth_streams_program.channel,
                              'smooth_streams_program_start': str(smooth_streams_program.start),
                              'smooth_streams_program_stop': str(smooth_streams_program.stop),
                              'date_time_of_last_failure': str(datetime.now(pytz.utc).replace(microsecond=0)),
                              'number_of_occurrences': 1,
                              'reviewed': 0})
            Database.commit()
        except sqlite3.IntegrityError as e:
            if 'UNIQUE constraint failed' in '{0}'.format(e):
                cls._update_failed_program_match_table(smooth_streams_program)

    @classmethod
    def _insert_into_program_match_table(cls,
                                         smooth_streams_program,
                                         epg_program,
                                         smooth_streams_program_string_compared,
                                         epg_program_string_compared,
                                         token_sort_ratio_score,
                                         jaro_winkler_ratio_score):
        regular_expression_match = re.search(r'I[0-9]+.[0-9]+(.[0-9]+)?', epg_program.channel)
        if regular_expression_match is not None:
            epg_program_channel_id = regular_expression_match.group(0)
        else:
            epg_program_channel_id = epg_program.channel

        sql_statement = "INSERT " \
                        "INTO program_match (smooth_streams_program_title, smooth_streams_program_sub_title, " \
                        "smooth_streams_program_channel, smooth_streams_program_start, smooth_streams_program_stop, " \
                        "epg_program_title, epg_program_sub_title, epg_program_channel, " \
                        "epg_program_start, epg_program_stop, smooth_streams_program_string_compared, " \
                        "epg_program_string_compared, token_sort_ratio_score, jaro_winkler_ratio_score, " \
                        "match_type, date_time_of_last_match, number_of_occurrences, is_valid, reviewed) " \
                        "VALUES (:smooth_streams_program_title, :smooth_streams_program_sub_title, " \
                        ":smooth_streams_program_channel, :smooth_streams_program_start, " \
                        ":smooth_streams_program_stop, :epg_program_title, :epg_program_sub_title, " \
                        ":epg_program_channel, :epg_program_start, :epg_program_stop, " \
                        ":smooth_streams_program_string_compared, :epg_program_string_compared, " \
                        ":token_sort_ratio_score, :jaro_winkler_ratio_score, :match_type, :date_time_of_last_match, " \
                        ":number_of_occurrences, :is_valid, :reviewed)"
        try:
            Database.execute(sql_statement,
                             {'smooth_streams_program_title': smooth_streams_program.titles[0]['value'],
                              'smooth_streams_program_sub_title': smooth_streams_program.sub_titles[0]['value']
                              if smooth_streams_program.has_sub_titles()
                              else '',
                              'smooth_streams_program_channel': smooth_streams_program.channel,
                              'smooth_streams_program_start': str(smooth_streams_program.start),
                              'smooth_streams_program_stop': str(smooth_streams_program.stop),
                              'epg_program_title': epg_program.titles[0]['value'],
                              'epg_program_sub_title': epg_program.sub_titles[0]['value']
                              if epg_program.has_sub_titles()
                              else '',
                              'epg_program_channel': cls._channel_id_map[epg_program_channel_id]
                              if epg_program_channel_id in cls._channel_id_map
                              else epg_program_channel_id,
                              'epg_program_start': str(epg_program.start),
                              'epg_program_stop': str(epg_program.stop),
                              'smooth_streams_program_string_compared': smooth_streams_program_string_compared,
                              'epg_program_string_compared': epg_program_string_compared,
                              'token_sort_ratio_score': token_sort_ratio_score,
                              'jaro_winkler_ratio_score': jaro_winkler_ratio_score,
                              'match_type': 'safe'
                              if token_sort_ratio_score >= SAFE_FUZZY_MATCH_PERCENTAGE or
                                 jaro_winkler_ratio_score >= SAFE_FUZZY_MATCH_PERCENTAGE
                              else 'risky',
                              'date_time_of_last_match': str(datetime.now(pytz.utc).replace(microsecond=0)),
                              'number_of_occurrences': 1,
                              'is_valid': None,
                              'reviewed': 0})
            Database.commit()
        except sqlite3.IntegrityError as e:
            if 'UNIQUE constraint failed' in '{0}'.format(e):
                cls._update_program_match_table(smooth_streams_program, epg_program)

    @classmethod
    def _is_match_found(cls, smooth_streams_program, epg_program, match_tuples, do_perform_safe_match=True):
        for match_tuple in match_tuples:
            token_sort_ratio_score = fuzz.token_sort_ratio(match_tuple[0], match_tuple[1])
            jaro_winkler_distance = int(round(jellyfish.jaro_winkler(match_tuple[0], match_tuple[1]), 2) * 100)
            if do_perform_safe_match:
                if token_sort_ratio_score >= SAFE_FUZZY_MATCH_PERCENTAGE or \
                        jaro_winkler_distance >= SAFE_FUZZY_MATCH_PERCENTAGE:
                    if token_sort_ratio_score < 100 and jaro_winkler_distance < 100:
                        cls._insert_into_program_match_table(smooth_streams_program,
                                                             epg_program,
                                                             match_tuple[0],
                                                             match_tuple[1],
                                                             token_sort_ratio_score,
                                                             jaro_winkler_distance)

                    cls._update_categories_map(smooth_streams_program, epg_program)

                    return True
            elif token_sort_ratio_score >= RISKY_FUZZY_MATCH_PERCENTAGE and \
                    jaro_winkler_distance >= RISKY_FUZZY_MATCH_PERCENTAGE:
                logger.debug('Risky overlap detected\n'
                             'Token sort ratio score    => {0}%\n'
                             'Jaro-Winkler ratio score  => {1}'.format(token_sort_ratio_score,
                                                                       jaro_winkler_distance))
                cls._insert_into_program_match_table(smooth_streams_program,
                                                     epg_program,
                                                     match_tuple[0],
                                                     match_tuple[1],
                                                     token_sort_ratio_score,
                                                     jaro_winkler_distance)

                return True

        return False

    @classmethod
    def _is_program_in_ignored_epg_program_match_table(cls, epg_program):
        ignored_epg_program_match_records = cls._query_ignored_epg_program_match_table(epg_program)
        if ignored_epg_program_match_records:
            logger.debug('EPG program matched a record in ignored_epg_prgram_match')

            return True

        return False

    @classmethod
    def _is_program_in_ignored_smooth_streams_program_match_table(cls, smooth_streams_program):
        ignored_smooth_streams_program_match_records = cls._query_ignored_smooth_streams_program_match_table(
            smooth_streams_program)
        if ignored_smooth_streams_program_match_records:
            logger.debug('SmoothStreams program matched a record in ignored_smooth_streams_program_match')

            return True

        return False

    @classmethod
    def _is_program_in_the_past(cls, smooth_streams_program):
        if smooth_streams_program.start < cls._startup_date_time_in_utc and \
                smooth_streams_program.stop <= cls._startup_date_time_in_utc:
            logger.debug('SmoothStreams program ended')

            return True

        return False

    @classmethod
    def _is_program_past_date_time_criteria(cls, smooth_streams_program):
        cutoff_date_time_in_utc = cls._startup_date_time_in_utc.replace(
            hour=0,
            minute=0,
            second=0,
            microsecond=0) + timedelta(days=max(DEFAULT_OUTPUT_XMLTV_NUMBER_OF_DAYS) + 1)

        if smooth_streams_program.start >= cutoff_date_time_in_utc or \
                smooth_streams_program.start >= cls._latest_date_time_epg_xml or \
                smooth_streams_program.stop >= cls._latest_date_time_epg_xml:
            logger.debug('SmoothStreams program is past the latest date/time criteria')

            return True

        return False

    @classmethod
    def _parse_epg_xml(cls, epg_xml_stream, is_smooth_streams_epg=False, parse_channels=True):
        tv_element = None

        for event, element in etree.iterparse(epg_xml_stream,
                                              events=('start', 'end'),
                                              tag=('channel', 'programme', 'tv')):
            if event == 'end':
                if element.tag == 'channel':
                    if parse_channels:
                        channel = EPGChannel()

                        channel.id = element.get('id')
                        for sub_element in list(element):
                            if sub_element.tag == 'display-name':
                                channel.add_display_name({'language': sub_element.get('lang'),
                                                          'value': sub_element.text})
                            elif sub_element.tag == 'icon':
                                channel.add_icon({'height': sub_element.get('height'), 'source': sub_element.get('src'),
                                                  'width': sub_element.get('width')})
                            elif sub_element.tag == 'url':
                                channel.add_url({'value': sub_element.text})

                        cls._epg[channel.id] = channel
                        cls._smooth_streams_epg[channel.id] = copy.deepcopy(channel)

                    element.clear()
                    tv_element.clear()
                elif element.tag == 'programme':
                    program = EPGProgram()

                    program.start = datetime.strptime(element.get('start'), '%Y%m%d%H%M%S %z').astimezone(pytz.utc)
                    program.stop = datetime.strptime(element.get('stop'), '%Y%m%d%H%M%S %z').astimezone(pytz.utc)

                    if is_smooth_streams_epg and \
                            cls._startup_date_time_in_utc.astimezone(tzlocal.get_localzone()).dst():
                        program.start = program.start - timedelta(hours=1)
                        program.stop = program.stop - timedelta(hours=1)

                    program.pdc_start = element.get('pdc-start')
                    program.vps_start = element.get('vps-start')
                    program.showview = element.get('showview')
                    program.videoplus = element.get('videoplus')
                    program.channel = element.get('channel')
                    program.clumpidx = element.get('clumpidx')

                    for sub_element in list(element):
                        if sub_element.tag == 'audio':
                            for sub_sub_element in list(sub_element):
                                if sub_sub_element.tag == 'present':
                                    program.audio_present = {'value': sub_sub_element.text}
                                elif sub_sub_element.tag == 'stereo':
                                    program.audio_stereo = {'value': sub_sub_element.text}
                        elif sub_element.tag == 'category':
                            program.add_category({'language': sub_element.get('lang'),
                                                  'value': sub_element.text})
                        elif sub_element.tag == 'credits':
                            for sub_sub_element in list(sub_element):
                                if sub_sub_element.tag == 'actor':
                                    program.add_credits_actor(
                                        {'role': sub_sub_element.get('role'),
                                         'value': sub_sub_element.text})
                                elif sub_sub_element.tag == 'adapter':
                                    program.add_credits_adapter({'value': sub_sub_element.text})
                                elif sub_sub_element.tag == 'commentator':
                                    program.add_credits_commentator({'value': sub_sub_element.text})
                                elif sub_sub_element.tag == 'composer':
                                    program.add_credits_composer({'value': sub_sub_element.text})
                                elif sub_sub_element.tag == 'director':
                                    program.add_credits_director({'value': sub_sub_element.text})
                                elif sub_sub_element.tag == 'editor':
                                    program.add_credits_editor({'value': sub_sub_element.text})
                                elif sub_sub_element.tag == 'guest':
                                    program.add_credits_guest({'value': sub_sub_element.text})
                                elif sub_sub_element.tag == 'presenter':
                                    program.add_credits_presenter({'value': sub_sub_element.text})
                                elif sub_sub_element.tag == 'producer':
                                    program.add_credits_producer({'value': sub_sub_element.text})
                                elif sub_sub_element.tag == 'writer':
                                    program.add_credits_writer({'value': sub_sub_element.text})
                        elif sub_element.tag == 'country':
                            program.add_country({'language': sub_element.get('lang'),
                                                 'value': sub_element.text})
                        elif sub_element.tag == 'date':
                            program.date = {'value': sub_element.text}
                        elif sub_element.tag == 'desc':
                            program.add_description({'language': sub_element.get('lang'),
                                                     'value': sub_element.text})
                        elif sub_element.tag == 'episode-num':
                            program.add_episode_number(
                                {'system': sub_element.get('system'), 'value': sub_element.text})
                        elif sub_element.tag == 'icon':
                            program.add_icon({'height': sub_element.get('height'),
                                              'source': sub_element.get('src'),
                                              'width': sub_element.get('width')})
                        elif sub_element.tag == 'language':
                            program.language = {'language': sub_element.get('lang'),
                                                'value': sub_element.text}
                        elif sub_element.tag == 'last-chance':
                            program.last_chance = {'language': sub_element.get('lang'),
                                                   'value': sub_element.text}
                        elif sub_element.tag == 'length':
                            program.length = {'units': sub_element.get('units'),
                                              'value': sub_element.text}
                        elif sub_element.tag == 'new':
                            program.new = True
                        elif sub_element.tag == 'orig-language':
                            program.original_language = {'language': sub_element.get('lang'),
                                                         'value': sub_element.text}
                        elif sub_element.tag == 'premiere':
                            program.premiere = {'language': sub_element.get('lang'),
                                                'value': sub_element.text}
                        elif sub_element.tag == 'previously-shown':
                            program.previously_shown = {'channel': sub_element.get('channel'),
                                                        'start': sub_element.get('start')}
                        elif sub_element.tag == 'rating':
                            rating = {'icons': [], 'system': sub_element.get('system')}

                            for sub_sub_element in list(sub_element):
                                if sub_sub_element.tag == 'icon':
                                    rating['icons'].append({'height': sub_sub_element.get('height'),
                                                            'source': sub_sub_element.get('src'),
                                                            'width': sub_sub_element.get('width')})
                                elif sub_sub_element.tag == 'value':
                                    rating['value'] = {'value': sub_sub_element.text}

                            program.add_rating(rating)
                        elif sub_element.tag == 'review':
                            program.add_review({'language': sub_element.get('lang'),
                                                'reviewer': sub_element.get('reviewer'),
                                                'source': sub_element.get('source'),
                                                'type': sub_element.get('type'),
                                                'value': sub_element.text})
                        elif sub_element.tag == 'star-rating':
                            star_rating = {'icons': [], 'system': sub_element.get('system')}

                            for sub_sub_element in list(sub_element):
                                if sub_sub_element.tag == 'icon':
                                    star_rating['icons'].append({'height': sub_sub_element.get('height'),
                                                                 'source': sub_sub_element.get('src'),
                                                                 'width': sub_sub_element.get('width')})
                                elif sub_sub_element.tag == 'value':
                                    star_rating['value'] = {'value': sub_sub_element.text}

                            program.add_star_rating(star_rating)
                        elif sub_element.tag == 'sub-title':
                            program.add_sub_title({'language': sub_element.get('lang'),
                                                   'value': sub_element.text})
                        elif sub_element.tag == 'subtitles':
                            subtitle = {'type': sub_element.get('type')}

                            for sub_sub_element in list(sub_element):
                                if sub_sub_element.tag == 'language':
                                    subtitle['language'] = {'language': sub_sub_element.get('lang'),
                                                            'value': sub_sub_element.text}

                            program.add_subtitle(subtitle)
                        elif sub_element.tag == 'title':
                            program.add_title({'language': sub_element.get('lang'),
                                               'value': sub_element.text})
                        elif sub_element.tag == 'url':
                            program.add_url({'value': sub_element.text})
                        elif sub_element.tag == 'video':
                            for sub_sub_element in list(sub_element):
                                if sub_sub_element.tag == 'aspect':
                                    program.video_aspect = {'value': sub_sub_element.text}
                                elif sub_sub_element.tag == 'colour':
                                    program.video_colour = {'value': sub_sub_element.text}
                                elif sub_sub_element.tag == 'present':
                                    program.video_present = {'value': sub_sub_element.text}
                                elif sub_sub_element.tag == 'quality':
                                    program.video_quality = {'value': sub_sub_element.text}

                    regular_expression_match = re.search(r'I[0-9]+.[0-9]+(.[0-9]+)?', program.channel)
                    if regular_expression_match is not None:
                        channel_id = regular_expression_match.group(0)
                    else:
                        channel_id = program.channel

                    if is_smooth_streams_epg:
                        cls._smooth_streams_epg[channel_id].add_program(program)
                    else:
                        cls._populate_parsed_programs_map(copy.deepcopy(program))

                        if channel_id in cls._channel_id_map:
                            cls._epg[cls._channel_id_map[channel_id]].add_program(program)

                            if cls._latest_date_time_epg_xml is None:
                                cls._latest_date_time_epg_xml = program.stop
                            elif cls._latest_date_time_epg_xml < program.stop:
                                cls._latest_date_time_epg_xml = program.stop

                        try:
                            cls._mc2xml_channel_ids_map[program.channel] = True
                        except KeyError:
                            pass

                    element.clear()
                    tv_element.clear()
            elif event == 'start':
                if element.tag == 'tv':
                    tv_element = element

    @classmethod
    def _populate_parsed_programs_map(cls, epg_program):
        if epg_program.titles[0]['value'] in cls._parsed_programs_map:
            bisect.insort(cls._parsed_programs_map[epg_program.titles[0]['value']], epg_program)
        else:
            cls._parsed_programs_map[epg_program.titles[0]['value']] = [epg_program]

        if epg_program.has_sub_titles():
            if epg_program.sub_titles[0]['value'] in cls._parsed_programs_map:
                bisect.insort(cls._parsed_programs_map[epg_program.sub_titles[0]['value']], epg_program)
            else:
                cls._parsed_programs_map[epg_program.sub_titles[0]['value']] = [epg_program]

    @classmethod
    def _purge_db_tables(cls):
        cls._delete_from_failed_program_match_table()
        logger.debug('Purged failed_program_match\n'
                     '# of records purged => {0}'.format(Database.get_row_count()))

        cls._delete_from_forced_program_match_table()
        logger.debug('Purged forced_program_match\n'
                     '# of records purged => {0}'.format(Database.get_row_count()))

        cls._delete_from_ignored_epg_program_match_table()
        logger.debug('Purged ignored_matched_program_match\n'
                     '# of records purged => {0}'.format(Database.get_row_count()))

        cls._delete_from_ignored_smooth_streams_program_match_table()
        logger.debug('Purged ignored_smooth_streams_program_match\n'
                     '# of records purged => {0}'.format(Database.get_row_count()))

        cls._delete_from_program_match_table()
        logger.debug('Purged program_match\n'
                     '# of records purged => {0}'.format(Database.get_row_count()))

    @classmethod
    def _query_category_map_table(cls, smooth_streams_category):
        sql_statement = 'SELECT * ' \
                        'FROM category_map ' \
                        'WHERE smooth_streams_category = :smooth_streams_category'
        records = Database.execute(sql_statement, {'smooth_streams_category': smooth_streams_category})

        return records

    @classmethod
    def _query_forced_program_match_table(cls, smooth_streams_program):
        sql_statement = 'SELECT * ' \
                        'FROM forced_program_match ' \
                        'WHERE smooth_streams_program_title = :smooth_streams_program_title ' \
                        '  AND smooth_streams_program_sub_title = :smooth_streams_program_sub_title ' \
                        '  AND smooth_streams_program_channel = :smooth_streams_program_channel ' \
                        '  AND smooth_streams_program_start = :smooth_streams_program_start ' \
                        '  AND smooth_streams_program_stop = :smooth_streams_program_stop'
        records = Database.execute(sql_statement,
                                   {'smooth_streams_program_title': smooth_streams_program.titles[0]['value'],
                                    'smooth_streams_program_sub_title': smooth_streams_program.sub_titles[0]['value']
                                    if smooth_streams_program.has_sub_titles()
                                    else '',
                                    'smooth_streams_program_channel': smooth_streams_program.channel,
                                    'smooth_streams_program_start': str(smooth_streams_program.start),
                                    'smooth_streams_program_stop': str(smooth_streams_program.stop)})

        return records

    @classmethod
    def _query_ignored_epg_program_match_table(cls, epg_program):
        sql_statement = 'SELECT * ' \
                        'FROM ignored_epg_program_match ' \
                        'WHERE epg_program_title = :epg_program_title ' \
                        '  AND ((epg_program_sub_title = :epg_program_sub_title ' \
                        '  AND epg_program_channel = :epg_program_channel ' \
                        '  AND epg_program_start = :epg_program_start ' \
                        '  AND epg_program_stop = :epg_program_stop) ' \
                        '  OR (epg_program_sub_title = :epg_program_sub_title ' \
                        '  AND epg_program_channel = \'\' ' \
                        '  AND epg_program_start = \'\' ' \
                        '  AND epg_program_stop = \'\') ' \
                        '  OR (epg_program_sub_title = \'\' ' \
                        '  AND epg_program_channel = \'\' ' \
                        '  AND epg_program_start = \'\' ' \
                        '  AND epg_program_stop = \'\'))'
        records = Database.execute(sql_statement,
                                   {'epg_program_title': epg_program.titles[0]['value'],
                                    'epg_program_sub_title': epg_program.sub_titles[0]['value']
                                    if epg_program.has_sub_titles()
                                    else '',
                                    'epg_program_channel': epg_program.channel,
                                    'epg_program_start': str(epg_program.start),
                                    'epg_program_stop': str(epg_program.stop)})

        return records

    @classmethod
    def _query_ignored_smooth_streams_program_match_table(cls, smooth_streams_program):
        sql_statement = 'SELECT * ' \
                        'FROM ignored_smooth_streams_program_match ' \
                        'WHERE smooth_streams_program_title = :smooth_streams_program_title ' \
                        '  AND smooth_streams_program_sub_title = :smooth_streams_program_sub_title ' \
                        '  AND ((smooth_streams_program_channel = :smooth_streams_program_channel ' \
                        '  AND smooth_streams_program_start = :smooth_streams_program_start ' \
                        '  AND smooth_streams_program_stop = :smooth_streams_program_stop) ' \
                        '  OR (smooth_streams_program_channel = \'\' ' \
                        '  AND smooth_streams_program_start = \'\' ' \
                        '  AND smooth_streams_program_stop = \'\'))'
        records = Database.execute(sql_statement,
                                   {'smooth_streams_program_title': smooth_streams_program.titles[0]['value'],
                                    'smooth_streams_program_sub_title': smooth_streams_program.sub_titles[0]['value']
                                    if smooth_streams_program.has_sub_titles()
                                    else '',
                                    'smooth_streams_program_channel': smooth_streams_program.channel,
                                    'smooth_streams_program_start': str(smooth_streams_program.start),
                                    'smooth_streams_program_stop': str(smooth_streams_program.stop)})

        return records

    @classmethod
    def _query_ignored_smooth_streams_program_pattern_table(cls):
        sql_statement = 'SELECT * ' \
                        'FROM ignored_smooth_streams_program_pattern'
        records = Database.execute(sql_statement, {})

        return records

    @classmethod
    def _query_pattern_program_match_table(cls, smooth_streams_program):
        sql_statement = 'SELECT * ' \
                        'FROM pattern_program_match ' \
                        'WHERE smooth_streams_program_title = :smooth_streams_program_title'

        records = Database.execute(sql_statement,
                                   {'smooth_streams_program_title': smooth_streams_program.titles[0]['value']})

        return records

    @classmethod
    def _query_program_match_table(cls, smooth_streams_program, epg_program):
        regular_expression_match = re.search(r'I[0-9]+.[0-9]+(.[0-9]+)?', epg_program.channel)
        if regular_expression_match is not None:
            epg_program_channel_id = regular_expression_match.group(0)
        else:
            epg_program_channel_id = epg_program.channel

        sql_statement = 'SELECT * ' \
                        'FROM program_match ' \
                        'WHERE smooth_streams_program_title = :smooth_streams_program_title ' \
                        '  AND smooth_streams_program_sub_title = :smooth_streams_program_sub_title ' \
                        '  AND smooth_streams_program_channel = :smooth_streams_program_channel ' \
                        '  AND smooth_streams_program_start = :smooth_streams_program_start ' \
                        '  AND smooth_streams_program_stop = :smooth_streams_program_stop' \
                        '  AND epg_program_title = :epg_program_title ' \
                        '  AND epg_program_sub_title = :epg_program_sub_title ' \
                        '  AND epg_program_channel = :epg_program_channel ' \
                        '  AND epg_program_start = :epg_program_start ' \
                        '  AND epg_program_stop = :epg_program_stop'

        records = Database.execute(sql_statement,
                                   {'smooth_streams_program_title': smooth_streams_program.titles[0]['value'],
                                    'smooth_streams_program_sub_title': smooth_streams_program.sub_titles[0]['value']
                                    if smooth_streams_program.has_sub_titles()
                                    else '',
                                    'smooth_streams_program_channel': smooth_streams_program.channel,
                                    'smooth_streams_program_start': str(smooth_streams_program.start),
                                    'smooth_streams_program_stop': str(smooth_streams_program.stop),
                                    'epg_program_title': epg_program.titles[0]['value'],
                                    'epg_program_sub_title': epg_program.sub_titles[0]['value']
                                    if epg_program.has_sub_titles()
                                    else '',
                                    'epg_program_channel': cls._channel_id_map[epg_program_channel_id]
                                    if epg_program_channel_id in cls._channel_id_map
                                    else epg_program_channel_id,
                                    'epg_program_start': str(epg_program.start),
                                    'epg_program_stop': str(epg_program.stop)})

        return records

    @classmethod
    def _read_mc2xml_channel_ids_map(cls, mc2xml_country):
        cls._mc2xml_channel_ids_map = {}

        for mc2xml_channel_id in Utility.read_file(
                os.path.join(DEFAULT_MC2XML_DIRECTORY_PATH, mc2xml_country, 'mc2xml.chl')).split('\n'):
            if mc2xml_channel_id.strip()[0] != '#':
                cls._mc2xml_channel_ids_map[mc2xml_channel_id] = False

    @classmethod
    def _relax_merge_smooth_streams_epg(cls):
        for channel in cls._smooth_streams_epg.values():
            logger.debug('Reconciling channel\n'
                         'Name   => {0}\n'
                         'Number => {1}'.format(channel.display_names[0]['value'], channel.id))

            epg_programs = cls._epg[channel.id].programs

            for smooth_streams_program in channel.programs:
                do_find_best_matching_program = True
                is_smooth_streams_program_processed = False

                while not is_smooth_streams_program_processed:
                    for epg_program in cls._epg[channel.id].programs:
                        if smooth_streams_program.start < epg_program.start:
                            if smooth_streams_program.stop <= epg_program.start:
                                if not is_smooth_streams_program_processed:
                                    if do_find_best_matching_program and not \
                                            cls._is_program_in_the_past(smooth_streams_program) and not \
                                            cls._is_program_past_date_time_criteria(
                                                smooth_streams_program) and not \
                                            cls._is_program_in_ignored_smooth_streams_program_match_table(
                                                smooth_streams_program) and not \
                                            cls._does_program_match_ignored_smooth_streams_program_pattern(
                                                smooth_streams_program):
                                        matching_program = cls._find_best_matching_program(smooth_streams_program)

                                        if smooth_streams_program is not matching_program:
                                            do_find_best_matching_program = False

                                            if smooth_streams_program.start != matching_program.start or \
                                                    smooth_streams_program.stop != matching_program.stop:
                                                smooth_streams_program = matching_program

                                                break
                                            else:
                                                smooth_streams_program = matching_program

                                    logger.debug(
                                        'No overlap detected\n'
                                        'Sports program\n'
                                        '  Title     => {0}\n'
                                        '  Start     => {1}\n'
                                        '  Stop      => {2}'.format(
                                            smooth_streams_program.titles[0]['value'],
                                            smooth_streams_program.start,
                                            smooth_streams_program.stop))

                                    bisect.insort(epg_programs, smooth_streams_program)
                                    is_smooth_streams_program_processed = True

                                    logger.debug(
                                        'No overlap processed\n'
                                        'SmoothStreams program inserted\n'
                                        '  Title     => {0}\n'
                                        '  Start     => {1}\n'
                                        '  Stop      => {2}'.format(
                                            smooth_streams_program.titles[0]['value'],
                                            smooth_streams_program.start,
                                            smooth_streams_program.stop))
                                else:
                                    is_smooth_streams_program_processed = True

                                    logger.debug(
                                        'Unexpected case #1 detected\n'
                                        'Sports program\n'
                                        '  Title     => {0}\n'
                                        '  Start     => {1}\n'
                                        '  Stop      => {2}\n'
                                        'EPG program\n'
                                        '  Title     => {3}\n'
                                        '{4}'
                                        '  Start     => {5}\n'
                                        '  Stop      => {6}'.format(
                                            smooth_streams_program.titles[0]['value'],
                                            smooth_streams_program.start,
                                            smooth_streams_program.stop,
                                            epg_program.titles[0]['value'],
                                            '  Sub-Title => {0}\n'.format(epg_program.sub_titles[0]['value'])
                                            if epg_program.sub_titles else '',
                                            epg_program.start,
                                            epg_program.stop))
                                break
                            elif smooth_streams_program.stop < epg_program.stop:
                                if is_smooth_streams_program_processed:
                                    logger.debug(
                                        'Overlap continuation detected\n'
                                        '  Type      => Overflow\n'
                                        '  Alignment => Start to before stop\n'
                                        'Sports program\n'
                                        '  Title     => {0}\n'
                                        '  Start     => {1}\n'
                                        '  Stop      => {2}\n'
                                        'EPG program\n'
                                        '  Title     => {3}\n'
                                        '{4}'
                                        '  Start     => {5}\n'
                                        '  Stop      => {6}'.format(
                                            smooth_streams_program.titles[0]['value'],
                                            smooth_streams_program.start,
                                            smooth_streams_program.stop,
                                            epg_program.titles[0]['value'],
                                            '  Sub-Title => {0}\n'.format(epg_program.sub_titles[0]['value'])
                                            if epg_program.sub_titles else '',
                                            epg_program.start,
                                            epg_program.stop))

                                    epg_program.start = smooth_streams_program.stop

                                    logger.debug(
                                        'Overlap continuation processed\n'
                                        '  Type      => Overflow\n'
                                        '  Alignment => Start to before stop\n'
                                        'Sports program\n'
                                        '  Title     => {0}\n'
                                        '  Start     => {1}\n'
                                        '  Stop      => {2}\n'
                                        'EPG program modified\n'
                                        '  Title     => {3}\n'
                                        '{4}'
                                        '  Start     => {5}\n'
                                        '  Stop      => {6}'.format(
                                            smooth_streams_program.titles[0]['value'],
                                            smooth_streams_program.start,
                                            smooth_streams_program.stop,
                                            epg_program.titles[0]['value'],
                                            '  Sub-Title => {0}\n'.format(epg_program.sub_titles[0]['value'])
                                            if epg_program.sub_titles else '',
                                            epg_program.start,
                                            epg_program.stop))

                                    break
                                else:
                                    if do_find_best_matching_program and not \
                                            cls._is_program_in_the_past(smooth_streams_program) and not \
                                            cls._is_program_past_date_time_criteria(
                                                smooth_streams_program) and not \
                                            cls._is_program_in_ignored_smooth_streams_program_match_table(
                                                smooth_streams_program) and not \
                                            cls._does_program_match_ignored_smooth_streams_program_pattern(
                                                smooth_streams_program):
                                        matching_program = cls._find_best_matching_program(smooth_streams_program)

                                        if smooth_streams_program is not matching_program:
                                            do_find_best_matching_program = False

                                            if smooth_streams_program.start != matching_program.start or \
                                                    smooth_streams_program.stop != matching_program.stop:
                                                smooth_streams_program = matching_program

                                                break
                                            else:
                                                smooth_streams_program = matching_program

                                    logger.debug(
                                        'Overlap detected\n'
                                        '  Type      => Partial\n'
                                        '  Alignment => After start to before stop\n'
                                        'Sports program\n'
                                        '  Title     => {0}\n'
                                        '  Start     => {1}\n'
                                        '  Stop      => {2}\n'
                                        'EPG program\n'
                                        '  Title     => {3}\n'
                                        '{4}'
                                        '  Start     => {5}\n'
                                        '  Stop      => {6}'.format(
                                            smooth_streams_program.titles[0]['value'],
                                            smooth_streams_program.start,
                                            smooth_streams_program.stop,
                                            epg_program.titles[0]['value'],
                                            '  Sub-Title => {0}\n'.format(epg_program.sub_titles[0]['value'])
                                            if epg_program.sub_titles else '',
                                            epg_program.start,
                                            epg_program.stop))

                                    epg_program.start = smooth_streams_program.stop
                                    bisect.insort(epg_programs, smooth_streams_program)
                                    is_smooth_streams_program_processed = True

                                    logger.debug(
                                        'Overlap processed\n'
                                        '  Type      => Partial\n'
                                        '  Alignment => After start to before stop\n'
                                        'SmoothStreams program inserted\n'
                                        '  Title     => {0}\n'
                                        '  Start     => {1}\n'
                                        '  Stop      => {2}\n'
                                        'EPG program removed\n'
                                        '  Title     => {3}\n'
                                        '{4}'
                                        '  Start     => {5}\n'
                                        '  Stop      => {6}'.format(
                                            smooth_streams_program.titles[0]['value'],
                                            smooth_streams_program.start,
                                            smooth_streams_program.stop,
                                            epg_program.titles[0]['value'],
                                            '  Sub-Title => {0}\n'.format(epg_program.sub_titles[0]['value'])
                                            if epg_program.sub_titles else '',
                                            epg_program.start,
                                            epg_program.stop))

                                    break
                            elif smooth_streams_program.stop == epg_program.stop:
                                if is_smooth_streams_program_processed:
                                    logger.debug(
                                        'Overlap continuation detected\n'
                                        '  Type      => Overflow\n'
                                        '  Alignment => Start to stop\n'
                                        'Sports program\n'
                                        '  Title     => {0}\n'
                                        '  Start     => {1}\n'
                                        '  Stop      => {2}\n'
                                        'EPG program\n'
                                        '  Title     => {3}\n'
                                        '{4}'
                                        '  Start     => {5}\n'
                                        '  Stop      => {6}'.format(
                                            smooth_streams_program.titles[0]['value'],
                                            smooth_streams_program.start,
                                            smooth_streams_program.stop,
                                            epg_program.titles[0]['value'],
                                            '  Sub-Title => {0}\n'.format(epg_program.sub_titles[0]['value'])
                                            if epg_program.sub_titles else '',
                                            epg_program.start,
                                            epg_program.stop))

                                    epg_programs.remove(epg_program)

                                    logger.debug(
                                        'Overlap continuation processed\n'
                                        '  Type      => Overflow\n'
                                        '  Alignment => Start to stop\n'
                                        'Sports program\n'
                                        '  Title     => {0}\n'
                                        '  Start     => {1}\n'
                                        '  Stop      => {2}\n'
                                        'EPG program removed\n'
                                        '  Title     => {3}\n'
                                        '{4}'
                                        '  Start     => {5}\n'
                                        '  Stop      => {6}'.format(
                                            smooth_streams_program.titles[0]['value'],
                                            smooth_streams_program.start,
                                            smooth_streams_program.stop,
                                            epg_program.titles[0]['value'],
                                            '  Sub-Title => {0}\n'.format(epg_program.sub_titles[0]['value'])
                                            if epg_program.sub_titles else '',
                                            epg_program.start,
                                            epg_program.stop))

                                    break
                                else:
                                    if do_find_best_matching_program and not \
                                            cls._is_program_in_the_past(smooth_streams_program) and not \
                                            cls._is_program_past_date_time_criteria(
                                                smooth_streams_program) and not \
                                            cls._is_program_in_ignored_smooth_streams_program_match_table(
                                                smooth_streams_program) and not \
                                            cls._does_program_match_ignored_smooth_streams_program_pattern(
                                                smooth_streams_program):
                                        matching_program = cls._find_best_matching_program(smooth_streams_program)

                                        if smooth_streams_program is not matching_program:
                                            do_find_best_matching_program = False

                                            if smooth_streams_program.start != matching_program.start or \
                                                    smooth_streams_program.stop != matching_program.stop:
                                                smooth_streams_program = matching_program

                                                break
                                            else:
                                                smooth_streams_program = matching_program

                                    logger.debug(
                                        'Overlap detected\n'
                                        '  Type      => Partial\n'
                                        '  Alignment => After start to stop\n'
                                        'Sports program\n'
                                        '  Title     => {0}\n'
                                        '  Start     => {1}\n'
                                        '  Stop      => {2}\n'
                                        'EPG program\n'
                                        '  Title     => {3}\n'
                                        '{4}'
                                        '  Start     => {5}\n'
                                        '  Stop      => {6}'.format(
                                            smooth_streams_program.titles[0]['value'],
                                            smooth_streams_program.start,
                                            smooth_streams_program.stop,
                                            epg_program.titles[0]['value'],
                                            '  Sub-Title => {0}\n'.format(epg_program.sub_titles[0]['value'])
                                            if epg_program.sub_titles else '',
                                            epg_program.start,
                                            epg_program.stop))

                                    epg_programs.remove(epg_program)
                                    bisect.insort(epg_programs, smooth_streams_program)
                                    is_smooth_streams_program_processed = True

                                    logger.debug(
                                        'Overlap processed\n'
                                        '  Type      => Partial\n'
                                        '  Alignment => After start to stop\n'
                                        'SmoothStreams program inserted\n'
                                        '  Title     => {0}\n'
                                        '  Start     => {1}\n'
                                        '  Stop      => {2}\n'
                                        'EPG program removed\n'
                                        '  Title     => {3}\n'
                                        '{4}'
                                        '  Start     => {5}\n'
                                        '  Stop      => {6}'.format(
                                            smooth_streams_program.titles[0]['value'],
                                            smooth_streams_program.start,
                                            smooth_streams_program.stop,
                                            epg_program.titles[0]['value'],
                                            '  Sub-Title => {0}\n'.format(epg_program.sub_titles[0]['value'])
                                            if epg_program.sub_titles else '',
                                            epg_program.start,
                                            epg_program.stop))

                                    break
                            elif smooth_streams_program.stop > epg_program.stop:
                                if is_smooth_streams_program_processed:
                                    logger.debug(
                                        'Overlap continuation detected\n'
                                        '  Type      => Overflow\n'
                                        '  Alignment => Start to stop\n'
                                        'Sports program\n'
                                        '  Title     => {0}\n'
                                        '  Start     => {1}\n'
                                        '  Stop      => {2}\n'
                                        'EPG program\n'
                                        '  Title     => {3}\n'
                                        '{4}'
                                        '  Start     => {5}\n'
                                        '  Stop      => {6}'.format(
                                            smooth_streams_program.titles[0]['value'],
                                            smooth_streams_program.start,
                                            smooth_streams_program.stop,
                                            epg_program.titles[0]['value'],
                                            '  Sub-Title => {0}\n'.format(epg_program.sub_titles[0]['value'])
                                            if epg_program.sub_titles else '',
                                            epg_program.start,
                                            epg_program.stop))

                                    epg_programs.remove(epg_program)

                                    logger.debug(
                                        'Overlap continuation processed\n'
                                        '  Type      => Overflow\n'
                                        '  Alignment => Start to stop\n'
                                        'Sports program\n'
                                        '  Title     => {0}\n'
                                        '  Start     => {1}\n'
                                        '  Stop      => {2}\n'
                                        'EPG program removed\n'
                                        '  Title     => {3}\n'
                                        '{4}'
                                        '  Start     => {5}\n'
                                        '  Stop      => {6}'.format(
                                            smooth_streams_program.titles[0]['value'],
                                            smooth_streams_program.start,
                                            smooth_streams_program.stop,
                                            epg_program.titles[0]['value'],
                                            '  Sub-Title => {0}\n'.format(epg_program.sub_titles[0]['value'])
                                            if epg_program.sub_titles else '',
                                            epg_program.start,
                                            epg_program.stop))
                                else:
                                    if do_find_best_matching_program and not \
                                            cls._is_program_in_the_past(smooth_streams_program) and not \
                                            cls._is_program_past_date_time_criteria(
                                                smooth_streams_program) and not \
                                            cls._is_program_in_ignored_smooth_streams_program_match_table(
                                                smooth_streams_program) and not \
                                            cls._does_program_match_ignored_smooth_streams_program_pattern(
                                                smooth_streams_program):
                                        matching_program = cls._find_best_matching_program(smooth_streams_program)

                                        if smooth_streams_program is not matching_program:
                                            do_find_best_matching_program = False

                                            if smooth_streams_program.start != matching_program.start or \
                                                    smooth_streams_program.stop != matching_program.stop:
                                                smooth_streams_program = matching_program

                                                break
                                            else:
                                                smooth_streams_program = matching_program

                                    logger.debug(
                                        'Overlap detected\n'
                                        '  Type      => Overflow\n'
                                        '  Alignment => After start to after stop\n'
                                        'Sports program\n'
                                        '  Title     => {0}\n'
                                        '  Start     => {1}\n'
                                        '  Stop      => {2}\n'
                                        'EPG program\n'
                                        '  Title     => {3}\n'
                                        '{4}'
                                        '  Start     => {5}\n'
                                        '  Stop      => {6}'.format(
                                            smooth_streams_program.titles[0]['value'],
                                            smooth_streams_program.start,
                                            smooth_streams_program.stop,
                                            epg_program.titles[0]['value'],
                                            '  Sub-Title => {0}\n'.format(epg_program.sub_titles[0]['value'])
                                            if epg_program.sub_titles else '',
                                            epg_program.start,
                                            epg_program.stop))

                                    epg_programs.remove(epg_program)
                                    bisect.insort(epg_programs, smooth_streams_program)
                                    is_smooth_streams_program_processed = True

                                    logger.debug(
                                        'Overlap processed\n'
                                        '  Type      => Overflow\n'
                                        '  Alignment => After start to after stop\n'
                                        'SmoothStreams program inserted\n'
                                        '  Title     => {0}\n'
                                        '  Start     => {1}\n'
                                        '  Stop      => {2}\n'
                                        'EPG program removed\n'
                                        '  Title     => {3}\n'
                                        '{4}'
                                        '  Start     => {5}\n'
                                        '  Stop      => {6}'.format(
                                            smooth_streams_program.titles[0]['value'],
                                            smooth_streams_program.start,
                                            smooth_streams_program.stop,
                                            epg_program.titles[0]['value'],
                                            '  Sub-Title => {0}\n'.format(epg_program.sub_titles[0]['value'])
                                            if epg_program.sub_titles else '',
                                            epg_program.start,
                                            epg_program.stop))

                                    break
                            else:
                                is_smooth_streams_program_processed = True

                                logger.debug(
                                    'Unexpected case #2 detected\n'
                                    'Sports program\n'
                                    '  Title     => {0}\n'
                                    '  Start     => {1}\n'
                                    '  Stop      => {2}\n'
                                    'EPG program\n'
                                    '  Title     => {3}\n'
                                    '{4}'
                                    '  Start     => {5}\n'
                                    '  Stop      => {6}'.format(
                                        smooth_streams_program.titles[0]['value'],
                                        smooth_streams_program.start,
                                        smooth_streams_program.stop,
                                        epg_program.titles[0]['value'],
                                        '  Sub-Title => {0}\n'.format(epg_program.sub_titles[0]['value'])
                                        if epg_program.sub_titles else '',
                                        epg_program.start,
                                        epg_program.stop))

                                break
                        elif smooth_streams_program.start == epg_program.start:
                            if smooth_streams_program.stop < epg_program.stop:
                                (do_process_overlap, matching_program) = cls._do_process_overlap(
                                    smooth_streams_program,
                                    epg_program,
                                    do_find_best_matching_program=do_find_best_matching_program,
                                    do_check_start_stop_times_alignment=False)

                                if smooth_streams_program is not matching_program:
                                    do_find_best_matching_program = False

                                    if smooth_streams_program.start != matching_program.start or \
                                            smooth_streams_program.stop != matching_program.stop:
                                        smooth_streams_program = matching_program

                                        break
                                    else:
                                        smooth_streams_program = matching_program

                                if smooth_streams_program == epg_program:
                                    do_process_overlap = False

                                if do_process_overlap:
                                    logger.debug(
                                        'Overlap detected\n'
                                        '  Type      => Partial\n'
                                        '  Alignment => Start\n'
                                        'Sports program\n'
                                        '  Title     => {0}\n'
                                        '  Start     => {1}\n'
                                        '  Stop      => {2}\n'
                                        'EPG program\n'
                                        '  Title     => {3}\n'
                                        '{4}'
                                        '  Start     => {5}\n'
                                        '  Stop      => {6}'.format(
                                            smooth_streams_program.titles[0]['value'],
                                            smooth_streams_program.start,
                                            smooth_streams_program.stop,
                                            epg_program.titles[0]['value'],
                                            '  Sub-Title => {0}\n'.format(epg_program.sub_titles[0]['value'])
                                            if epg_program.sub_titles else '',
                                            epg_program.start,
                                            epg_program.stop))

                                    epg_program.start = smooth_streams_program.stop
                                    bisect.insort(epg_programs, smooth_streams_program)
                                    is_smooth_streams_program_processed = True

                                    logger.debug(
                                        'Overlap processed\n'
                                        '  Type      => Partial\n'
                                        '  Alignment => Start\n'
                                        'SmoothStreams program inserted\n'
                                        '  Title     => {0}\n'
                                        '  Start     => {1}\n'
                                        '  Stop      => {2}\n'
                                        'EPG program modified\n'
                                        '  Title     => {3}\n'
                                        '{4}'
                                        '  Start     => {5}\n'
                                        '  Stop      => {6}'.format(
                                            smooth_streams_program.titles[0]['value'],
                                            smooth_streams_program.start,
                                            smooth_streams_program.stop,
                                            epg_program.titles[0]['value'],
                                            '  Sub-Title => {0}\n'.format(epg_program.sub_titles[0]['value'])
                                            if epg_program.sub_titles else '',
                                            epg_program.start,
                                            epg_program.stop))
                                else:
                                    is_smooth_streams_program_processed = True

                                    logger.debug(
                                        'Overlap skipped\n'
                                        '  Type      => Partial\n'
                                        '  Alignment => Start\n'
                                        'Sports program\n'
                                        '  Title     => {0}\n'
                                        '  Start     => {1}\n'
                                        '  Stop      => {2}\n'
                                        'EPG program\n'
                                        '  Title     => {3}\n'
                                        '{4}'
                                        '  Start     => {5}\n'
                                        '  Stop      => {6}'.format(
                                            smooth_streams_program.titles[0]['value'],
                                            smooth_streams_program.start,
                                            smooth_streams_program.stop,
                                            epg_program.titles[0]['value'],
                                            '  Sub-Title => {0}\n'.format(epg_program.sub_titles[0]['value'])
                                            if epg_program.sub_titles else '',
                                            epg_program.start,
                                            epg_program.stop))

                                break
                            elif smooth_streams_program.stop == epg_program.stop:
                                (do_process_overlap, matching_program) = cls._do_process_overlap(
                                    smooth_streams_program,
                                    epg_program,
                                    do_find_best_matching_program=do_find_best_matching_program,
                                    do_check_start_stop_times_alignment=False)

                                if smooth_streams_program is not matching_program:
                                    do_find_best_matching_program = False

                                    if smooth_streams_program.start != matching_program.start or \
                                            smooth_streams_program.stop != matching_program.stop:
                                        smooth_streams_program = matching_program

                                        break
                                    else:
                                        smooth_streams_program = matching_program

                                if smooth_streams_program == epg_program:
                                    do_process_overlap = False

                                if do_process_overlap:
                                    logger.debug(
                                        'Overlap detected\n'
                                        '  Type      => Full\n'
                                        '  Alignment => Start to stop\n'
                                        'Sports program\n'
                                        '  Title     => {0}\n'
                                        '  Start     => {1}\n'
                                        '  Stop      => {2}\n'
                                        'EPG program\n'
                                        '  Title     => {3}\n'
                                        '{4}'
                                        '  Start     => {5}\n'
                                        '  Stop      => {6}'.format(
                                            smooth_streams_program.titles[0]['value'],
                                            smooth_streams_program.start,
                                            smooth_streams_program.stop,
                                            epg_program.titles[0]['value'],
                                            '  Sub-Title => {0}\n'.format(epg_program.sub_titles[0]['value'])
                                            if epg_program.sub_titles else '',
                                            epg_program.start,
                                            epg_program.stop))

                                    epg_programs.remove(epg_program)
                                    bisect.insort(epg_programs, smooth_streams_program)
                                    is_smooth_streams_program_processed = True

                                    logger.debug(
                                        'Overlap processed\n'
                                        '  Type      => Full\n'
                                        '  Alignment => Start to stop\n'
                                        'SmoothStreams program inserted\n'
                                        '  Title     => {0}\n'
                                        '  Start     => {1}\n'
                                        '  Stop      => {2}\n'
                                        'EPG program removed\n'
                                        '  Title     => {3}\n'
                                        '{4}'
                                        '  Start     => {5}\n'
                                        '  Stop      => {6}'.format(
                                            smooth_streams_program.titles[0]['value'],
                                            smooth_streams_program.start,
                                            smooth_streams_program.stop,
                                            epg_program.titles[0]['value'],
                                            '  Sub-Title => {0}\n'.format(epg_program.sub_titles[0]['value'])
                                            if epg_program.sub_titles else '',
                                            epg_program.start,
                                            epg_program.stop))
                                else:
                                    is_smooth_streams_program_processed = True

                                    logger.debug(
                                        'Overlap skipped\n'
                                        '  Type      => Full\n'
                                        '  Alignment => Start to stop\n'
                                        'Sports program\n'
                                        '  Title     => {0}\n'
                                        '  Start     => {1}\n'
                                        '  Stop      => {2}\n'
                                        'EPG program\n'
                                        '  Title     => {3}\n'
                                        '{4}'
                                        '  Start     => {5}\n'
                                        '  Stop      => {6}'.format(
                                            smooth_streams_program.titles[0]['value'],
                                            smooth_streams_program.start,
                                            smooth_streams_program.stop,
                                            epg_program.titles[0]['value'],
                                            '  Sub-Title => {0}\n'.format(epg_program.sub_titles[0]['value'])
                                            if epg_program.sub_titles else '',
                                            epg_program.start,
                                            epg_program.stop))

                                break
                            elif smooth_streams_program.stop > epg_program.stop:
                                (do_process_overlap, matching_program) = cls._do_process_overlap(
                                    smooth_streams_program,
                                    epg_program,
                                    do_find_best_matching_program=do_find_best_matching_program,
                                    do_check_start_stop_times_alignment=False)

                                if smooth_streams_program is not matching_program:
                                    do_find_best_matching_program = False

                                    if smooth_streams_program.start != matching_program.start or \
                                            smooth_streams_program.stop != matching_program.stop:
                                        smooth_streams_program = matching_program

                                        break
                                    else:
                                        smooth_streams_program = matching_program

                                if smooth_streams_program == epg_program:
                                    do_process_overlap = False

                                if do_process_overlap:
                                    logger.debug(
                                        'Overlap detected\n'
                                        '  Type      => Overflow\n'
                                        '  Alignment => Start to after stop\n'
                                        'Sports program\n'
                                        '  Title     => {0}\n'
                                        '  Start     => {1}\n'
                                        '  Stop      => {2}\n'
                                        'EPG program\n'
                                        '  Title     => {3}\n'
                                        '{4}'
                                        '  Start     => {5}\n'
                                        '  Stop      => {6}'.format(
                                            smooth_streams_program.titles[0]['value'],
                                            smooth_streams_program.start,
                                            smooth_streams_program.stop,
                                            epg_program.titles[0]['value'],
                                            '  Sub-Title => {0}\n'.format(epg_program.sub_titles[0]['value'])
                                            if epg_program.sub_titles else '',
                                            epg_program.start,
                                            epg_program.stop))

                                    epg_programs.remove(epg_program)
                                    bisect.insort(epg_programs, smooth_streams_program)
                                    is_smooth_streams_program_processed = True

                                    logger.debug(
                                        'Overlap processed\n'
                                        '  Type      => Overflow\n'
                                        '  Alignment => Start to after stop\n'
                                        'SmoothStreams program inserted\n'
                                        '  Title     => {0}\n'
                                        '  Start     => {1}\n'
                                        '  Stop      => {2}\n'
                                        'EPG program removed\n'
                                        '  Title     => {3}\n'
                                        '{4}'
                                        '  Start     => {5}\n'
                                        '  Stop      => {6}'.format(
                                            smooth_streams_program.titles[0]['value'],
                                            smooth_streams_program.start,
                                            smooth_streams_program.stop,
                                            epg_program.titles[0]['value'],
                                            '  Sub-Title => {0}\n'.format(epg_program.sub_titles[0]['value'])
                                            if epg_program.sub_titles else '',
                                            epg_program.start,
                                            epg_program.stop))
                                else:
                                    is_smooth_streams_program_processed = True

                                    logger.debug(
                                        'Overlap skipped\n'
                                        '  Type      => Overflow\n'
                                        '  Alignment => Start to after stop\n'
                                        'Sports program\n'
                                        '  Title     => {0}\n'
                                        '  Start     => {1}\n'
                                        '  Stop      => {2}\n'
                                        'EPG program\n'
                                        '  Title     => {3}\n'
                                        '{4}'
                                        '  Start     => {5}\n'
                                        '  Stop      => {6}'.format(
                                            smooth_streams_program.titles[0]['value'],
                                            smooth_streams_program.start,
                                            smooth_streams_program.stop,
                                            epg_program.titles[0]['value'],
                                            '  Sub-Title => {0}\n'.format(epg_program.sub_titles[0]['value'])
                                            if epg_program.sub_titles else '',
                                            epg_program.start,
                                            epg_program.stop))

                                    break
                        elif smooth_streams_program.start > epg_program.start:
                            if smooth_streams_program.start >= epg_program.stop:
                                continue
                            elif smooth_streams_program.stop < epg_program.stop:
                                (do_process_overlap, matching_program) = cls._do_process_overlap(
                                    smooth_streams_program,
                                    epg_program,
                                    do_find_best_matching_program=do_find_best_matching_program,
                                    do_check_start_stop_times_alignment=False)

                                if smooth_streams_program is not matching_program:
                                    do_find_best_matching_program = False

                                    if smooth_streams_program.start != matching_program.start or \
                                            smooth_streams_program.stop != matching_program.stop:
                                        smooth_streams_program = matching_program

                                        break
                                    else:
                                        smooth_streams_program = matching_program

                                if smooth_streams_program == epg_program:
                                    do_process_overlap = False

                                if do_process_overlap:
                                    logger.debug(
                                        'Overlap detected\n'
                                        '  Type      => Partial\n'
                                        '  Alignment => After start to before stop\n'
                                        'Sports program\n'
                                        '  Title     => {0}\n'
                                        '  Start     => {1}\n'
                                        '  Stop      => {2}\n'
                                        'EPG program\n'
                                        '  Title     => {3}\n'
                                        '{4}'
                                        '  Start     => {5}\n'
                                        '  Stop      => {6}'.format(
                                            smooth_streams_program.titles[0]['value'],
                                            smooth_streams_program.start,
                                            smooth_streams_program.stop,
                                            epg_program.titles[0]['value'],
                                            '  Sub-Title => {0}\n'.format(epg_program.sub_titles[0]['value'])
                                            if epg_program.sub_titles else '',
                                            epg_program.start,
                                            epg_program.stop))

                                    new_epg_program = copy.deepcopy(epg_program)

                                    epg_program.stop = smooth_streams_program.start
                                    bisect.insort(epg_programs, smooth_streams_program)
                                    is_smooth_streams_program_processed = True

                                    new_epg_program.start = smooth_streams_program.stop
                                    bisect.insort(epg_programs, new_epg_program)

                                    logger.debug(
                                        'Overlap processed\n'
                                        '  Type      => Partial\n'
                                        '  Alignment => After start to before stop\n'
                                        'SmoothStreams program inserted\n'
                                        '  Title     => {0}\n'
                                        '  Start     => {1}\n'
                                        '  Stop      => {2}\n'
                                        'EPG program modified\n'
                                        '  Title     => {3}\n'
                                        '{4}'
                                        '  Start     => {5}\n'
                                        '  Stop      => {6}\n'
                                        'EPG program inserted\n'
                                        '  Title     => {7}\n'
                                        '{8}'
                                        '  Start     => {9}\n'
                                        '  Stop      => {10}'.format(
                                            smooth_streams_program.titles[0]['value'],
                                            smooth_streams_program.start,
                                            smooth_streams_program.stop,
                                            epg_program.titles[0]['value'],
                                            '  Sub-Title => {0}\n'.format(epg_program.sub_titles[0]['value'])
                                            if epg_program.sub_titles else '',
                                            epg_program.start,
                                            epg_program.stop,
                                            new_epg_program.titles[0]['value'],
                                            '  Sub-Title => {0}\n'.format(new_epg_program.sub_titles[0]['value'])
                                            if new_epg_program.sub_titles else '',
                                            new_epg_program.start,
                                            new_epg_program.stop))
                                else:
                                    is_smooth_streams_program_processed = True

                                    logger.debug(
                                        'Overlap skipped\n'
                                        '  Type      => Partial\n'
                                        '  Alignment => After start to before stop\n'
                                        'Sports program\n'
                                        '  Title     => {0}\n'
                                        '  Start     => {1}\n'
                                        '  Stop      => {2}\n'
                                        'EPG program\n'
                                        '  Title     => {3}\n'
                                        '{4}'
                                        '  Start     => {5}\n'
                                        '  Stop      => {6}'.format(
                                            smooth_streams_program.titles[0]['value'],
                                            smooth_streams_program.start,
                                            smooth_streams_program.stop,
                                            epg_program.titles[0]['value'],
                                            '  Sub-Title => {0}\n'.format(epg_program.sub_titles[0]['value'])
                                            if epg_program.sub_titles else '',
                                            epg_program.start,
                                            epg_program.stop))

                                break
                            elif smooth_streams_program.stop == epg_program.stop:
                                (do_process_overlap, matching_program) = cls._do_process_overlap(
                                    smooth_streams_program,
                                    epg_program,
                                    do_find_best_matching_program=do_find_best_matching_program,
                                    do_check_start_stop_times_alignment=False)

                                if smooth_streams_program is not matching_program:
                                    do_find_best_matching_program = False

                                    if smooth_streams_program.start != matching_program.start or \
                                            smooth_streams_program.stop != matching_program.stop:
                                        smooth_streams_program = matching_program

                                        break
                                    else:
                                        smooth_streams_program = matching_program

                                if smooth_streams_program == epg_program:
                                    do_process_overlap = False

                                if do_process_overlap:
                                    logger.debug(
                                        'Overlap detected\n'
                                        '  Type      => Partial\n'
                                        '  Alignment => After start to stop\n'
                                        'Sports program\n'
                                        '  Title     => {0}\n'
                                        '  Start     => {1}\n'
                                        '  Stop      => {2}\n'
                                        'EPG program\n'
                                        '  Title     => {3}\n'
                                        '{4}'
                                        '  Start     => {5}\n'
                                        '  Stop      => {6}'.format(
                                            smooth_streams_program.titles[0]['value'],
                                            smooth_streams_program.start,
                                            smooth_streams_program.stop,
                                            epg_program.titles[0]['value'],
                                            '  Sub-Title => {0}\n'.format(epg_program.sub_titles[0]['value'])
                                            if epg_program.sub_titles else '',
                                            epg_program.start,
                                            epg_program.stop))

                                    epg_program.stop = smooth_streams_program.start
                                    bisect.insort(epg_programs, smooth_streams_program)
                                    is_smooth_streams_program_processed = True

                                    logger.debug(
                                        'Overlap processed\n'
                                        '  Type      => Partial\n'
                                        '  Alignment => After start to stop\n'
                                        'SmoothStreams program inserted\n'
                                        '  Title     => {0}\n'
                                        '  Start     => {1}\n'
                                        '  Stop      => {2}\n'
                                        'EPG program modified\n'
                                        '  Title     => {3}\n'
                                        '{4}'
                                        '  Start     => {5}\n'
                                        '  Stop      => {6}'.format(
                                            smooth_streams_program.titles[0]['value'],
                                            smooth_streams_program.start,
                                            smooth_streams_program.stop,
                                            epg_program.titles[0]['value'],
                                            '  Sub-Title => {0}\n'.format(epg_program.sub_titles[0]['value'])
                                            if epg_program.sub_titles else '',
                                            epg_program.start,
                                            epg_program.stop))
                                else:
                                    is_smooth_streams_program_processed = True

                                    logger.debug(
                                        'Overlap skipped\n'
                                        '  Type      => Partial\n'
                                        '  Alignment => After start to stop\n'
                                        'Sports program\n'
                                        '  Title     => {0}\n'
                                        '  Start     => {1}\n'
                                        '  Stop      => {2}\n'
                                        'EPG program\n'
                                        '  Title     => {3}\n'
                                        '{4}'
                                        '  Start     => {5}\n'
                                        '  Stop      => {6}'.format(
                                            smooth_streams_program.titles[0]['value'],
                                            smooth_streams_program.start,
                                            smooth_streams_program.stop,
                                            epg_program.titles[0]['value'],
                                            '  Sub-Title => {0}\n'.format(epg_program.sub_titles[0]['value'])
                                            if epg_program.sub_titles else '',
                                            epg_program.start,
                                            epg_program.stop))

                                break
                            elif smooth_streams_program.stop > epg_program.stop:
                                (do_process_overlap, matching_program) = cls._do_process_overlap(
                                    smooth_streams_program,
                                    epg_program,
                                    do_find_best_matching_program=do_find_best_matching_program,
                                    do_check_start_stop_times_alignment=False)

                                if smooth_streams_program is not matching_program:
                                    do_find_best_matching_program = False

                                    if smooth_streams_program.start != matching_program.start or \
                                            smooth_streams_program.stop != matching_program.stop:
                                        smooth_streams_program = matching_program

                                        break
                                    else:
                                        smooth_streams_program = matching_program

                                if smooth_streams_program == epg_program:
                                    do_process_overlap = False

                                if do_process_overlap:
                                    logger.debug(
                                        'Overlap detected\n'
                                        '  Type      => Overflow\n'
                                        '  Alignment => After start to after stop\n'
                                        'Sports program\n'
                                        '  Title     => {0}\n'
                                        '  Start     => {1}\n'
                                        '  Stop      => {2}\n'
                                        'EPG program\n'
                                        '  Title     => {3}\n'
                                        '{4}'
                                        '  Start     => {5}\n'
                                        '  Stop      => {6}'.format(
                                            smooth_streams_program.titles[0]['value'],
                                            smooth_streams_program.start,
                                            smooth_streams_program.stop,
                                            epg_program.titles[0]['value'],
                                            '  Sub-Title => {0}\n'.format(epg_program.sub_titles[0]['value'])
                                            if epg_program.sub_titles else '',
                                            epg_program.start,
                                            epg_program.stop))

                                    epg_program.stop = smooth_streams_program.start
                                    bisect.insort(epg_programs, smooth_streams_program)
                                    is_smooth_streams_program_processed = True

                                    logger.debug(
                                        'Overlap processed\n'
                                        '  Type      => Overflow\n'
                                        '  Alignment => After start to after stop\n'
                                        'SmoothStreams program inserted\n'
                                        '  Title     => {0}\n'
                                        '  Start     => {1}\n'
                                        '  Stop      => {2}\n'
                                        'EPG program modified\n'
                                        '  Title     => {3}\n'
                                        '{4}'
                                        '  Start     => {5}\n'
                                        '  Stop      => {6}'.format(
                                            smooth_streams_program.titles[0]['value'],
                                            smooth_streams_program.start,
                                            smooth_streams_program.stop,
                                            epg_program.titles[0]['value'],
                                            '  Sub-Title => {0}\n'.format(epg_program.sub_titles[0]['value'])
                                            if epg_program.sub_titles else '',
                                            epg_program.start,
                                            epg_program.stop))
                                else:
                                    is_smooth_streams_program_processed = True

                                    logger.debug(
                                        'Overlap skipped\n'
                                        '  Type      => Overflow\n'
                                        '  Alignment => After start to after stop\n'
                                        'Sports program\n'
                                        '  Title     => {0}\n'
                                        '  Start     => {1}\n'
                                        '  Stop      => {2}\n'
                                        'EPG program\n'
                                        '  Title     => {3}\n'
                                        '{4}'
                                        '  Start     => {5}\n'
                                        '  Stop      => {6}'.format(
                                            smooth_streams_program.titles[0]['value'],
                                            smooth_streams_program.start,
                                            smooth_streams_program.stop,
                                            epg_program.titles[0]['value'],
                                            '  Sub-Title => {0}\n'.format(epg_program.sub_titles[0]['value'])
                                            if epg_program.sub_titles else '',
                                            epg_program.start,
                                            epg_program.stop))

                                    break
                            else:
                                logger.debug(
                                    'Unexpected case #3 detected\n'
                                    'Sports program\n'
                                    '  Title     => {0}\n'
                                    '  Start     => {1}\n'
                                    '  Stop      => {2}\n'
                                    'EPG program\n'
                                    '  Title     => {3}\n'
                                    '{4}'
                                    '  Start     => {5}\n'
                                    '  Stop      => {6}'.format(
                                        smooth_streams_program.titles[0]['value'],
                                        smooth_streams_program.start,
                                        smooth_streams_program.stop,
                                        epg_program.titles[0]['value'],
                                        '  Sub-Title => {0}\n'.format(epg_program.sub_titles[0]['value'])
                                        if epg_program.sub_titles else '',
                                        epg_program.start,
                                        epg_program.stop))
                    else:
                        if not is_smooth_streams_program_processed:
                            if do_find_best_matching_program and not \
                                    cls._is_program_in_the_past(smooth_streams_program) and not \
                                    cls._is_program_past_date_time_criteria(
                                        smooth_streams_program) and not \
                                    cls._is_program_in_ignored_smooth_streams_program_match_table(
                                        smooth_streams_program) and not \
                                    cls._does_program_match_ignored_smooth_streams_program_pattern(
                                        smooth_streams_program):
                                matching_program = cls._find_best_matching_program(smooth_streams_program)

                                if smooth_streams_program is not matching_program:
                                    do_find_best_matching_program = True

                                    smooth_streams_program = matching_program

                            bisect.insort(epg_programs, smooth_streams_program)
                            is_smooth_streams_program_processed = True

                            logger.debug('No overlap detected\n'
                                         'SmoothStreams program inserted\n'
                                         '  Title     => {0}\n'
                                         '  Start     => {1}\n'
                                         '  Stop      => {2}'.format(smooth_streams_program.titles[0]['value'],
                                                                     smooth_streams_program.start,
                                                                     smooth_streams_program.stop))

                cls._epg[channel.id].programs = epg_programs

    @classmethod
    def _request_epg_xml(cls, epg_base_url, epg_file_name):
        url = '{0}{1}'.format(epg_base_url, epg_file_name)

        logger.debug('Downloading {0}\n'
                     'URL => {1}'.format(epg_file_name, url))

        session = requests.Session()
        response = Utility.make_http_request(session.get, url, headers=session.headers, stream=True)

        if response.status_code == requests.codes.OK:
            response.raw.decode_content = True

            logger.debug(Utility.assemble_response_from_log_message(response))

            return response.raw
        else:
            logger.debug(Utility.assemble_response_from_log_message(response))

            response.raise_for_status()

    @classmethod
    def _update_categories_map(cls, smooth_streams_program, epg_program):
        if ': ' in smooth_streams_program.titles[0]['value']:
            smooth_streams_program_category = smooth_streams_program.titles[0]['value'][
                                              0:smooth_streams_program.titles[0]['value'].find(': ')]
            epg_program_title = re.sub(r'\A.*:\s+', '', epg_program.titles[0]['value'])

            if smooth_streams_program_category in cls._categories_map and \
                    epg_program_title in cls._categories_map[smooth_streams_program_category]:
                cls._categories_map[smooth_streams_program_category][epg_program_title] += 1
            else:
                cls._categories_map[smooth_streams_program_category] = {epg_program_title: 1}

    @classmethod
    def _update_program_match_table(cls, smooth_streams_program, epg_program):
        regular_expression_match = re.search(r'I[0-9]+.[0-9]+(.[0-9]+)?', epg_program.channel)
        if regular_expression_match is not None:
            epg_program_channel_id = regular_expression_match.group(0)
        else:
            epg_program_channel_id = epg_program.channel

        sql_statement = 'UPDATE program_match ' \
                        'SET date_time_of_last_match = :date_time_of_last_match, ' \
                        'number_of_occurrences = number_of_occurrences + 1 ' \
                        'WHERE smooth_streams_program_title = :smooth_streams_program_title ' \
                        '  AND smooth_streams_program_sub_title = :smooth_streams_program_sub_title ' \
                        '  AND smooth_streams_program_channel = :smooth_streams_program_channel ' \
                        '  AND smooth_streams_program_start = :smooth_streams_program_start ' \
                        '  AND smooth_streams_program_stop = :smooth_streams_program_stop' \
                        '  AND epg_program_title = :epg_program_title ' \
                        '  AND epg_program_sub_title = :epg_program_sub_title ' \
                        '  AND epg_program_channel = :epg_program_channel ' \
                        '  AND epg_program_start = :epg_program_start ' \
                        '  AND epg_program_stop = :epg_program_stop'

        Database.execute(sql_statement,
                         {'date_time_of_last_match': str(datetime.now(pytz.utc).replace(microsecond=0)),
                          'smooth_streams_program_title': smooth_streams_program.titles[0]['value'],
                          'smooth_streams_program_sub_title': smooth_streams_program.sub_titles[0]['value']
                          if smooth_streams_program.has_sub_titles()
                          else '',
                          'smooth_streams_program_channel': smooth_streams_program.channel,
                          'smooth_streams_program_start': str(smooth_streams_program.start),
                          'smooth_streams_program_stop': str(smooth_streams_program.stop),
                          'epg_program_title': epg_program.titles[0]['value'],
                          'epg_program_sub_title': epg_program.sub_titles[0]['value']
                          if epg_program.has_sub_titles()
                          else '',
                          'epg_program_channel': cls._channel_id_map[epg_program_channel_id]
                          if epg_program_channel_id in cls._channel_id_map
                          else epg_program_channel_id,
                          'epg_program_start': str(epg_program.start),
                          'epg_program_stop': str(epg_program.stop)})

        Database.commit()

    @classmethod
    def _update_failed_program_match_table(cls, smooth_streams_program):
        sql_statement = 'UPDATE failed_program_match ' \
                        'SET date_time_of_last_failure = :date_time_of_last_failure, ' \
                        'number_of_occurrences = number_of_occurrences + 1 ' \
                        'WHERE smooth_streams_program_title = :smooth_streams_program_title ' \
                        '  AND smooth_streams_program_sub_title = :smooth_streams_program_sub_title ' \
                        '  AND smooth_streams_program_channel = :smooth_streams_program_channel ' \
                        '  AND smooth_streams_program_start = :smooth_streams_program_start ' \
                        '  AND smooth_streams_program_stop = :smooth_streams_program_stop'

        Database.execute(sql_statement,
                         {'date_time_of_last_failure': str(datetime.now(pytz.utc).replace(microsecond=0)),
                          'smooth_streams_program_title': smooth_streams_program.titles[0]['value'],
                          'smooth_streams_program_sub_title': smooth_streams_program.sub_titles[0]['value']
                          if smooth_streams_program.has_sub_titles()
                          else '',
                          'smooth_streams_program_channel': smooth_streams_program.channel,
                          'smooth_streams_program_start': str(smooth_streams_program.start),
                          'smooth_streams_program_stop': str(smooth_streams_program.stop)})

        Database.commit()

    @classmethod
    def _validate_source_channels(cls):
        smooth_streams_channels_with_source = cls._channel_id_map.values()

        for channel in cls._epg.values():
            if not channel.programs and channel.id in smooth_streams_channels_with_source:
                error = 'EPG source issue encountered\n' \
                        'Channel id   => {0}\n' \
                        'Channel name => {1}'.format(channel.id, channel.display_names[0]['value'])

                logger.error(error)
                Error.add_error(error)

    @classmethod
    def _validate_mc2xml_source_channels(cls):
        for mc2xml_channel_id in cls._mc2xml_channel_ids_map:
            if not cls._mc2xml_channel_ids_map[mc2xml_channel_id]:
                error = 'mc2xml source issue encountered\n' \
                        'Channel id   => {0}'.format(mc2xml_channel_id)

                logger.error(error)
                Error.add_error(error)

    @classmethod
    def generate_epg(cls, output_directory_path, do_backup_output_xmltv_files):
        cls._startup_date_time_in_utc = datetime.now(pytz.utc).replace(microsecond=0)

        logger.info('Parsing default SmoothStreams channel map\n'
                    'File path => {0}'.format(DEFAULT_CHANNEL_MAP_FILE_PATH))
        cls._parse_epg_xml(DEFAULT_CHANNEL_MAP_FILE_PATH)

        for xmltv_file_name in os.listdir(DEFAULT_INPUT_XMLTV_DIRECTORY_PATH):
            if xmltv_file_name.endswith('.xml'):
                cls._read_mc2xml_channel_ids_map(xmltv_file_name[0:-4])

                logger.info('Parsing EPGs\n'
                            'File path => {0}'.format(xmltv_file_name))
                cls._parse_epg_xml(os.path.join(DEFAULT_INPUT_XMLTV_DIRECTORY_PATH, xmltv_file_name),
                                   parse_channels=False)

                cls._validate_mc2xml_source_channels()

        cls._validate_source_channels()

        logger.info('Parsing SmoothStreams Sports EPG')
        cls._parse_epg_xml(cls._request_epg_xml(SMOOTH_STREAMS_EPG_BASE_URL,
                                                SMOOTH_STREAMS_EPG_FILE_NAME),
                           is_smooth_streams_epg=True,
                           parse_channels=False)
        cls._cleanup_smooth_streams_epg()

        if do_backup_output_xmltv_files:
            Utility.backup_epgs(output_directory_path)

        cls._relax_merge_smooth_streams_epg()
        cls._generate_epgs(output_directory_path, is_forced=False)

        cls._force_merge_smooth_streams_epg()
        cls._generate_epgs(output_directory_path, is_forced=True)

        for smooth_streams_category in cls._categories_map:
            for epg_category in cls._categories_map[smooth_streams_category]:
                if cls._categories_map[smooth_streams_category][epg_category] > 3:
                    cls._insert_into_category_map_table(smooth_streams_category, epg_category)

        cls._purge_db_tables()


class EPGChannel(object):
    __slots__ = ['_display_names', '_icons', '_id', '_programs', '_urls']

    def __init__(self):
        self._display_names = []
        self._icons = []
        self._id = None
        self._programs = []
        self._urls = []

    def add_display_name(self, display_name):
        self._display_names.append(display_name)

    def add_icon(self, icon):
        self._icons.append(icon)

    def add_program(self, program):
        bisect.insort(self._programs, program)

    def add_url(self, url):
        self._urls.append(url)

    def remove_program(self, program):
        self._programs.remove(program)

    @property
    def id(self):
        return self._id

    @id.setter
    def id(self, id_):
        self._id = id_

    @property
    def display_names(self):
        return copy.copy(self._display_names)

    @display_names.setter
    def display_names(self, display_names):
        self._display_names = display_names

    @property
    def icons(self):
        return copy.copy(self._icons)

    @icons.setter
    def icons(self, icons):
        self._icons = icons

    @property
    def programs(self):
        return copy.copy(self._programs)

    @programs.setter
    def programs(self, programs):
        self._programs = programs

    @property
    def urls(self):
        return copy.copy(self._urls)

    @urls.setter
    def urls(self, urls):
        self._urls = urls


class EPGProgram(object):
    __slots__ = ['_audio', '_categories', '_channel', '_clumpidx', '_countries', '_credits', '_date', '_descriptions',
                 '_episode_numbers', '_icons', '_keywords', '_language', '_last_chance', '_length', '_new',
                 '_original_language', '_pdc_start', '_premiere', '_previously_shown', '_ratings', '_reviews',
                 '_showview', '_star_ratings', '_start', '_stop', '_sub_titles', '_subtitles', '_titles', '_urls',
                 '_video', '_videoplus', '_vps_start']

    def __eq__(self, other):
        if not isinstance(other, EPGProgram):
            return NotImplemented

        if self is other:
            return True

        return self._channel == other._channel and self._start == other._start and self._stop == other._stop

    def __init__(self):
        self._audio = {'present': None, 'stereo': None}
        self._categories = []
        self._channel = None
        self._clumpidx = None
        self._countries = []
        self._credits = {'actors': [], 'adapters': [], 'commentators': [], 'composers': [], 'directors': [],
                         'editors': [], 'guests': [], 'presenters': [], 'producers': [], 'writers': []}
        self._date = None
        self._descriptions = []
        self._episode_numbers = []
        self._icons = []
        self._keywords = []
        self._language = None
        self._last_chance = None
        self._length = None
        self._new = False
        self._original_language = None
        self._pdc_start = None
        self._premiere = None
        self._previously_shown = None
        self._ratings = []
        self._reviews = []
        self._showview = None
        self._star_ratings = []
        self._start = None
        self._stop = None
        self._sub_titles = []
        self._subtitles = []
        self._titles = []
        self._urls = []
        self._video = {'aspect': None, 'colour': None, 'present': None, 'quality': None}
        self._videoplus = None
        self._vps_start = None

    def __lt__(self, other):
        return self.start < other.start

    def add_category(self, category):
        self._categories.append(category)

    def add_country(self, country):
        self._countries.append(country)

    def add_credits_actor(self, actor):
        self._credits['actors'].append(actor)

    def add_credits_adapter(self, adapter):
        self._credits['adapters'].append(adapter)

    def add_credits_commentator(self, commentator):
        self._credits['commentators'].append(commentator)

    def add_credits_composer(self, composer):
        self._credits['composers'].append(composer)

    def add_credits_director(self, director):
        self._credits['directors'].append(director)

    def add_credits_editor(self, editor):
        self._credits['editors'].append(editor)

    def add_credits_guest(self, guest):
        self._credits['guests'].append(guest)

    def add_credits_presenter(self, presenter):
        self._credits['presenters'].append(presenter)

    def add_credits_producer(self, producer):
        self._credits['producers'].append(producer)

    def add_credits_writer(self, writer):
        self._credits['writers'].append(writer)

    def add_description(self, description):
        self._descriptions.append(description)

    def add_episode_number(self, episode_number):
        self._episode_numbers.append(episode_number)

    def add_icon(self, icon):
        self._icons.append(icon)

    def add_keyword(self, keyword):
        self._keywords.append(keyword)

    def add_rating(self, rating):
        self._ratings.append(rating)

    def add_review(self, review):
        self._reviews.append(review)

    def add_star_rating(self, star_rating):
        self._star_ratings.append(star_rating)

    def add_sub_title(self, sub_title):
        self._sub_titles.append(sub_title)

    def add_subtitle(self, subtitle):
        self._subtitles.append(subtitle)

    def add_title(self, title):
        self._titles.append(title)

    def add_url(self, url):
        self._urls.append(url)

    def has_audio(self):
        if self._audio['present'] is not None or self._audio['stereo'] is not None:
            return True

        return False

    def has_categories(self):
        if self._categories:
            return True

        return False

    def has_credits(self):
        if self._credits['actors'] or self._credits['adapters'] or self._credits['commentators'] or \
                self._credits['composers'] or self._credits['directors'] or self._credits['editors'] or \
                self._credits['guests'] or self._credits['presenters'] or self._credits['producers'] or \
                self._credits['writers']:
            return True

        return False

    def has_sub_titles(self):
        if self._sub_titles:
            return True

        return False

    def has_video(self):
        if self._video['aspect'] is not None or self._video['colour'] is not None or \
                self._video['present'] is not None or self._video['quality'] is not None:
            return True

        return False

    @property
    def audio(self):
        return copy.copy(self._audio)

    @audio.setter
    def audio(self, audio):
        self._audio = audio

    @property
    def audio_present(self):
        return self._audio['present']

    @audio_present.setter
    def audio_present(self, audio_present):
        self._audio['present'] = audio_present

    @property
    def audio_stereo(self):
        return self._audio['stereo']

    @audio_stereo.setter
    def audio_stereo(self, audio_stereo):
        self._audio['stereo'] = audio_stereo

    @property
    def categories(self):
        return copy.copy(self._categories)

    @categories.setter
    def categories(self, categories):
        self._categories = categories

    @property
    def channel(self):
        return self._channel

    @channel.setter
    def channel(self, channel):
        self._channel = channel

    @property
    def clumpidx(self):
        return self._clumpidx

    @clumpidx.setter
    def clumpidx(self, clumpidx):
        self._clumpidx = clumpidx

    @property
    def credits(self):
        return copy.copy(self._credits)

    @credits.setter
    def credits(self, credits_):
        self._credits = credits_

    @property
    def countries(self):
        return copy.copy(self._countries)

    @countries.setter
    def countries(self, countries):
        self._countries = countries

    @property
    def date(self):
        return self._date

    @date.setter
    def date(self, date):
        self._date = date

    @property
    def descriptions(self):
        return copy.copy(self._descriptions)

    @descriptions.setter
    def descriptions(self, descriptions):
        self._descriptions = descriptions

    @property
    def episode_numbers(self):
        return copy.copy(self._episode_numbers)

    @episode_numbers.setter
    def episode_numbers(self, episode_numbers):
        self._episode_numbers = episode_numbers

    @property
    def icons(self):
        return copy.copy(self._icons)

    @icons.setter
    def icons(self, icons):
        self._icons = icons

    @property
    def keywords(self):
        return copy.copy(self._keywords)

    @keywords.setter
    def keywords(self, keywords):
        self._keywords = keywords

    @property
    def language(self):
        return self._language

    @language.setter
    def language(self, language):
        self._language = language

    @property
    def last_chance(self):
        return self._last_chance

    @last_chance.setter
    def last_chance(self, last_chance):
        self._last_chance = last_chance

    @property
    def length(self):
        return self._length

    @length.setter
    def length(self, length):
        self._length = length

    @property
    def new(self):
        return self._new

    @new.setter
    def new(self, new):
        self._new = new

    @property
    def original_language(self):
        return self._original_language

    @original_language.setter
    def original_language(self, original_language):
        self._original_language = original_language

    @property
    def pdc_start(self):
        return self._pdc_start

    @pdc_start.setter
    def pdc_start(self, pdc_start):
        self._pdc_start = pdc_start

    @property
    def premiere(self):
        return self._premiere

    @premiere.setter
    def premiere(self, premiere):
        self._premiere = premiere

    @property
    def previously_shown(self):
        return self._previously_shown

    @previously_shown.setter
    def previously_shown(self, previously_shown):
        self._previously_shown = previously_shown

    @property
    def ratings(self):
        return copy.copy(self._ratings)

    @ratings.setter
    def ratings(self, ratings):
        self._ratings = ratings

    @property
    def reviews(self):
        return copy.copy(self._reviews)

    @reviews.setter
    def reviews(self, reviews):
        self._reviews = reviews

    @property
    def showview(self):
        return self._showview

    @showview.setter
    def showview(self, showview):
        self._showview = showview

    @property
    def star_ratings(self):
        return copy.copy(self._star_ratings)

    @star_ratings.setter
    def star_ratings(self, star_ratings):
        self._star_ratings = star_ratings

    @property
    def start(self):
        return self._start

    @start.setter
    def start(self, start):
        self._start = start

    @property
    def stop(self):
        return self._stop

    @stop.setter
    def stop(self, stop):
        self._stop = stop

    @property
    def sub_titles(self):
        return copy.copy(self._sub_titles)

    @sub_titles.setter
    def sub_titles(self, sub_titles):
        self._sub_titles = sub_titles

    @property
    def subtitles(self):
        return copy.copy(self._subtitles)

    @subtitles.setter
    def subtitles(self, subtitles):
        self._subtitles = subtitles

    @property
    def titles(self):
        return copy.copy(self._titles)

    @titles.setter
    def titles(self, titles):
        self._titles = titles

    @property
    def urls(self):
        return copy.copy(self._urls)

    @urls.setter
    def urls(self, urls):
        self._urls = urls

    @property
    def video(self):
        return copy.copy(self._video)

    @video.setter
    def video(self, video):
        self._video = video

    @property
    def videoplus(self):
        return self._videoplus

    @videoplus.setter
    def videoplus(self, videoplus):
        self._videoplus = videoplus

    @property
    def video_aspect(self):
        return self._video['aspect']

    @video_aspect.setter
    def video_aspect(self, video_aspect):
        self._video['aspect'] = video_aspect

    @property
    def video_colour(self):
        return self._video['colour']

    @video_colour.setter
    def video_colour(self, video_colour):
        self._video['colour'] = video_colour

    @property
    def video_present(self):
        return self._video['present']

    @video_present.setter
    def video_present(self, video_present):
        self._video['present'] = video_present

    @property
    def video_quality(self):
        return self._video['quality']

    @video_quality.setter
    def video_quality(self, video_quality):
        self._video['quality'] = video_quality

    @property
    def vps_start(self):
        return self._vps_start

    @vps_start.setter
    def vps_start(self, vps_start):
        self._vps_start = vps_start
