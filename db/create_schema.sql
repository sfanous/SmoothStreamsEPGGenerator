CREATE TABLE IF NOT EXISTS "failed_program_match" (
	"smooth_streams_program_title"	TEXT NOT NULL,
	"smooth_streams_program_sub_title"	TEXT NOT NULL DEFAULT '',
	"smooth_streams_program_channel"	TEXT NOT NULL,
	"smooth_streams_program_start"	TEXT NOT NULL,
	"smooth_streams_program_stop"	TEXT NOT NULL,
	"date_time_of_last_failure"	TEXT NOT NULL,
	"number_of_occurrences"	INTEGER NOT NULL,
	"reviewed"	INTEGER NOT NULL DEFAULT 0 CHECK(reviewed IN (0, 1)),
	PRIMARY KEY("smooth_streams_program_title","smooth_streams_program_sub_title","smooth_streams_program_channel","smooth_streams_program_start","smooth_streams_program_stop")
);
CREATE TABLE IF NOT EXISTS "ignored_smooth_streams_program_match" (
	"smooth_streams_program_title"	TEXT NOT NULL,
	"smooth_streams_program_sub_title"	TEXT NOT NULL,
	"smooth_streams_program_channel"	TEXT NOT NULL DEFAULT '',
	"smooth_streams_program_start"	TEXT NOT NULL DEFAULT '',
	"smooth_streams_program_stop"	TEXT NOT NULL DEFAULT '',
	PRIMARY KEY("smooth_streams_program_title","smooth_streams_program_sub_title","smooth_streams_program_channel","smooth_streams_program_start","smooth_streams_program_stop")
);
CREATE TABLE IF NOT EXISTS "ignored_epg_program_match"
(
	epg_program_title TEXT not null,
	epg_program_sub_title TEXT not null,
	epg_program_channel TEXT default '' not null,
	epg_program_start TEXT default '' not null,
	epg_program_stop TEXT default '' not null,
	primary key (epg_program_title, epg_program_sub_title, epg_program_channel, epg_program_start, epg_program_stop)
);
CREATE TABLE IF NOT EXISTS "ignored_smooth_streams_program_pattern" (
	"smooth_streams_program_pattern"	TEXT NOT NULL,
	PRIMARY KEY("smooth_streams_program_pattern")
);
CREATE TABLE IF NOT EXISTS "forced_program_match" (
	"smooth_streams_program_title"	TEXT NOT NULL,
	"smooth_streams_program_sub_title"	TEXT NOT NULL,
	"smooth_streams_program_channel"	TEXT NOT NULL,
	"smooth_streams_program_start"	TEXT NOT NULL,
	"smooth_streams_program_stop"	TEXT NOT NULL,
	"epg_program_title"	TEXT NOT NULL,
	"epg_program_sub_title"	TEXT NOT NULL,
	"epg_program_channel"	TEXT NOT NULL,
	"epg_program_start"	TEXT NOT NULL,
	"epg_program_stop"	TEXT NOT NULL,
	PRIMARY KEY("smooth_streams_program_title","smooth_streams_program_sub_title","smooth_streams_program_channel","smooth_streams_program_start","smooth_streams_program_stop")
);
CREATE TABLE IF NOT EXISTS "category_map" (
	"smooth_streams_category"	TEXT NOT NULL,
	"epg_category"	TEXT NOT NULL,
	"is_valid"	INTEGER,
	"reviewed"	INTEGER NOT NULL DEFAULT 0,
	PRIMARY KEY("smooth_streams_category","epg_category")
);
CREATE TABLE IF NOT EXISTS "pattern_program_match" (
	"smooth_streams_program_title"	TEXT NOT NULL,
	"epg_program_pattern"	TEXT NOT NULL,
	PRIMARY KEY("smooth_streams_program_title","epg_program_pattern")
);
CREATE TABLE IF NOT EXISTS "program_match" (
	"smooth_streams_program_title"	TEXT NOT NULL,
	"smooth_streams_program_sub_title"	TEXT NOT NULL DEFAULT '',
	"smooth_streams_program_channel"	TEXT NOT NULL,
	"smooth_streams_program_start"	TEXT NOT NULL,
	"smooth_streams_program_stop"	TEXT NOT NULL,
	"epg_program_title"	TEXT NOT NULL,
	"epg_program_sub_title"	TEXT NOT NULL DEFAULT '',
	"epg_program_channel"	TEXT NOT NULL,
	"epg_program_start"	TEXT NOT NULL,
	"epg_program_stop"	TEXT NOT NULL,
	"smooth_streams_program_string_compared"	TEXT NOT NULL,
	"epg_program_string_compared"	TEXT NOT NULL,
	"token_sort_ratio_score"	INTEGER NOT NULL,
	"jaro_winkler_ratio_score"	INTEGER NOT NULL,
	"match_type"	TEXT NOT NULL CHECK(match_type IN ('risky','safe')),
	"date_time_of_last_match"	TEXT NOT NULL,
	"number_of_occurrences"	INTEGER NOT NULL DEFAULT 1,
	"is_valid"	INTEGER CHECK(is_valid IN (0,1)),
	"reviewed"	INTEGER NOT NULL DEFAULT 0 CHECK(reviewed IN (0,1)),
	PRIMARY KEY("smooth_streams_program_title","smooth_streams_program_sub_title","smooth_streams_program_channel","smooth_streams_program_start","smooth_streams_program_stop","epg_program_title","epg_program_sub_title","epg_program_channel","epg_program_start","epg_program_stop")
);
