.. :changelog:

Release History
===============
1.3.8 (08-09-2020)
------------------
* Migrate from PyCharm to VSCode
* Code refactoring and cleanup using Black and Pylint

1.3.7.5 (06-02-2020)
--------------------
* Make sending of email through GMail optional.

1.3.7.3 (02-18-2020)
--------------------
* Minor enhancements

1.3.7.2 (01-31-2020)
--------------------
* Update mapping

1.3.7.1 (11-11-2019)
--------------------
* Update mapping

1.3.7 (26-10-2019)
------------------
* Update mapping

1.3.6 (04-10-2019)
------------------
* Update mapping

1.3.5 (27-09-2019)
------------------
* Update mapping

1.3.4 (18-06-2019)
------------------
* Ignore commented out channel ids in mc2xml.chl files

1.3.3 (30-04-2019)
------------------
* Add display-name element with channel number to output XMLTV files

1.3.2 (30-03-2019)
------------------
* Don't generate XMLTV from Rovi unless XMLTV file doesn't exist or is stale (Over 18 hours old)

1.3.1 (27-03-2019)
------------------
* Fix missing > in case of empty premiere and last-change elements

1.3.0 (27-03-2019)
------------------
* Add saxutil.escape() around every attribute or text value

1.2.1 (24-03-2019)
------------------
* Fix bug in _find_forced_matched_program. The %z directive can only handle UTC offsets with a colon starting Python 3.7

1.2.0 (23-03-2019)
------------------
* Add optional-requirements.txt
* Remove newlines at end of mc2xml.chl files

1.1.0 (22-03-2019)
------------------
* Introduce the -b command line argument
    * If passed then the previously generated XMLTV files will be backed up prior to generating the new XMLTV files

1.0.0 (22-03-2019)
------------------
* First public release
