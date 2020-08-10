import logging.handlers
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from .configuration import Configuration
from .constants import GMAIL_SERVER_HOSTNAME

logger = logging.getLogger(__name__)


class Notifier(object):
    __slots__ = []

    @classmethod
    def send_email(cls, body):
        try:
            connection = smtplib.SMTP_SSL(GMAIL_SERVER_HOSTNAME, 465)
            connection.ehlo()
            connection.login(
                Configuration.get_configuration_parameter('GMAIL_USERNAME'),
                Configuration.get_configuration_parameter('GMAIL_PASSWORD'),
            )

            message = MIMEMultipart()
            message['From'] = Configuration.get_configuration_parameter(
                'GMAIL_USERNAME'
            )
            message['To'] = Configuration.get_configuration_parameter('GMAIL_USERNAME')
            message['Subject'] = 'SmoothStreamsEPGGenerator Error'
            message.attach(MIMEText(body, 'plain'))

            connection.sendmail(
                Configuration.get_configuration_parameter('GMAIL_USERNAME'),
                Configuration.get_configuration_parameter('GMAIL_USERNAME'),
                message.as_string(),
            )

            connection.close()
        except smtplib.SMTPException:
            logger.error('Failed to send Email')
