SmoothStreamsEPGGenerator: A full EPG generator for SmoothStreams written in Python 3
======================================================================================

Introduction
============
SmoothStreamsEPGGenerator is a full EPG generator for SmoothStreams.

Installation
============
At this point the only way to install IPTVProxy is by downloading `git <https://git-scm.com/downloads>`_ and cloning the repository

.. code-block:: bash

    $ git clone https://github.com/sfanous/SmoothStreamsEPGGenerator.git

Updating to the latest version is just a matter of updating your local repository to the newest commit

.. code-block:: bash

    $ git pull

SmoothStreamsEPGGenerator depends on a few required packages. To install these packages run the following command

.. code-block:: bash

    $ pip install -r requirements.txt

SmoothStreamsEPGGenerator performance depends on an optional package. To install this package run the following command

.. code-block:: bash

    $ pip install -r optional-requirements.txt

Running
=======
To start SmoothStreamsEPGGenerator run the following command

.. code-block:: bash

    $ python smooth_streams_epg_generator_runner.py

SmoothStreamsEPGGenerator supports a number of command line arguments. Run the following command to get a help message with all the options

.. code-block:: bash

    $ python smooth_streams_epg_generator_runner.py -h

Configuration
==============
Use your favourite text editor and edit smooth_streams_epg_generator.ini before running SmoothStreamsEPGGenerator

Understanding the Configuration Options
---------------------------------------
####
Rovi
####
api_key
    * The API Key assigned to your Rovi account
shared_secret
    * The Shared Secret assigned to your Rovi account
listings
    * A comma separated list of listings to generate from Rovi
    * The format of each entry is country_code:postal_code

###############
SchedulesDirect
###############
Username
    * The SchedulesDirect account username
Password
    * The SchedulesDirect account password
listings
    * A comma separated list of listings to generate from Rovi
    * The format of each entry is country_code:postal_code:lineup_name

#####
GMail
#####
Username
    * The GMail account username
Password
    * The GMail account password
    * Recommended value: A GMail Application-Specific Password

#######
Logging
#######
Level
    * The logging level
    * Recommended value: "Info". Other values are for debugging purposes and will result in large log files