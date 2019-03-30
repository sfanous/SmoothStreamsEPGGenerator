.. :changelog:

Release History
===============
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
