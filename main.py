"""
This script monitors specific URL for any changes in any CSS element
It has two topics to send notifications to: health status and 
If change is identified it send push 
"""

import time
import traceback
import hashlib
import logging
import sys

from typing import List

import boto3

from selenium import webdriver
from selenium.common.exceptions import NoSuchElementException
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.chrome.options import Options

from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# URL link of the page we want to monitor
URL_LINK = "https://canada.mid.ru/ru_RU/novosti"

# CSS class name that we are interested in
CLASS_ELEMENT = "portlet"

# Topic to push notifications about a change
CHANGE_STATUS_TOPIC = "arn:aws:sns:us-west-2:868131308206:RuEmbassyMonitor"

# Topic to push notification about a script status
HEALTH_STATUS_TOPIC = "arn:aws:sns:us-west-2:868131308206:ServerStatus"

# Message when the page content is changed
MSG_CHANGE_DETECTED = f"The page has been changed. Go check: {URL_LINK}"

# Not secure. Pass it over cli
ACCESS_KEY = "XXX"
SECRET_KEY = "XXXYYYZZZ"

# no point to monitor further if the page has been changed more than this
WEB_PAGE_MONITOR_CHANGES_TO_EXIT = 10

# Timeout for element to appear
TIMEOUT_SEC = 10

# Time to report the script status
TIME_TO_REPORT_STATUS_MIN = 120

# Period to check the page
INTERVAL_TO_CHECK_FOR_CHANGE_SEC = 60

logger = logging.getLogger(__name__)


def init_headless_webdriver(
    driver_path: str = "/usr/bin/chromedriver",
):
    """Initialize Chrome driver.

    :param driver_path: path to Chrome driver, defaults to "/usr/bin/chromedriver"
    :return: initialized Chrome driver
    """
    options = Options()
    options.add_argument("--headless")
    options.add_argument("--disable-gpu")
    return webdriver.Chrome(driver_path, chrome_options=options)


def init_sns_service(key_id: str, access_key: str):
    """Initialize SNS service.

    :param key_id: AWS access key ID
    :param access_key: AWS secret access key
    :return: initialized boto3 client
    """
    return boto3.client(
        "sns",
        region_name="us-west-2",
        aws_access_key_id=key_id,
        aws_secret_access_key=access_key,
    )


def get_sha1_hash(text: str) -> str:
    """Calculate SHA1 hash value for given text.

    :param text: text to calculate hash value for
    :return: hash string in HEX format
    """
    hash_object1 = hashlib.sha1(text.encode("utf-8"))
    return hash_object1.hexdigest()


def setup_logging() -> None:
    """Setup module-wide logging."""
    handler = logging.StreamHandler()
    formatter = logging.Formatter("%(asctime)s %(name)-12s %(levelname)-8s %(message)s")
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)


def main(script_args: List[str]) -> None:
    logger.debug("Starting session with %s arguments", str(script_args))
    logger.info("Start page monitor program")

    # Initialize web driver based on headless Chrome
    driver = init_headless_webdriver()

    # Set a timeout to wait for the element
    wait = WebDriverWait(driver, TIMEOUT_SEC)

    # Initialize SNS service
    sns = init_sns_service(ACCESS_KEY, SECRET_KEY)

    # Publish a message to the specified SNS topic
    sns.publish(
        TopicArn=HEALTH_STATUS_TOPIC,
        Message=f"Start monitoring {URL_LINK}",
    )

    # Get specified web page
    driver.get(URL_LINK)

    # Find html element based on CSS class name
    element = wait.until(EC.presence_of_element_located((By.CLASS_NAME, CLASS_ELEMENT)))

    # Calculate initial hash value
    init_hash = get_sha1_hash(text=element.text)

    change_counter = 0
    time_counter = 0

    while change_counter < WEB_PAGE_MONITOR_CHANGES_TO_EXIT:
        try:
            driver.get(URL_LINK)
            element = wait.until(
                EC.presence_of_element_located((By.CLASS_NAME, CLASS_ELEMENT))
            )
            current_hash = get_sha1_hash(element.text)

            if init_hash != current_hash:
                logger.info("The page has changed")

                # Publish a message to the specified SNS topic
                sns.publish(
                    TopicArn=CHANGE_STATUS_TOPIC,
                    Message=MSG_CHANGE_DETECTED,
                )

                sns.publish(
                    TopicArn=HEALTH_STATUS_TOPIC,
                    Message=MSG_CHANGE_DETECTED,
                )

                init_hash = current_hash
                change_counter += 1
            else:
                logger.info("No change, continue monitoring")

                if time_counter >= TIME_TO_REPORT_STATUS_MIN:
                    # Publish a message to the specified SNS topic
                    sns.publish(
                        TopicArn=HEALTH_STATUS_TOPIC,
                        Message="Status: No change. Keep monitoring",
                    )
                    time_counter = 0

                time_counter += 1

        except NoSuchElementException:
            logger.exception("Cannot find %s, keep monitoring", CLASS_ELEMENT)

        except TimeoutException:
            logger.exception("Timed out while waiting on element")

        except Exception:
            logger.exception("Unexpected exception occurred")
            # Publish a message to the specified SNS topic
            sns.publish(
                TopicArn=HEALTH_STATUS_TOPIC,
                Message=traceback.format_exc(),
            )

            # No point to continue if unexpected exception occurred.
            # We notified the users and good to exit
            break

        finally:
			# Do not want to overwhelm the resource. Sleep and 
			# go check again			
            time.sleep(INTERVAL_TO_CHECK_FOR_CHANGE_SEC)

    driver.quit()

    logger.info("End of program")

    # Publish a message to the specified SNS topic
    sns.publish(
        TopicArn=HEALTH_STATUS_TOPIC,
        Message=f"Script to monitor {URL_LINK} has stopped",
    )


if __name__ == "__main__":
    setup_logging()
    main(sys.argv[1:])
