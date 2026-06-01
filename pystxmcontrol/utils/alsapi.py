import json
import logging
import os
import time
from dotenv import load_dotenv
from httpx import Client as HttpClient, ConnectTimeout, Response
import httpx

beamline = "7.0.1.2"
from pystxmcontrol.utils.logger import get_logger
logger = get_logger(__name__)

ALSHUB_API_SERVERS = {
    "production": "https://api1-prd.als.lbl.gov:8083/alshub/",  # Latest STABLE version of the API
    "backup": "https://bl402ca.als.lbl.gov:8088/alshub/",  # Redundant copy of the production server
    "staging": "https://api1-stg.als.lbl.gov:8083/alshub/",  # Latest TESTING version of the API
}

EXPERIMENT_API_SERVERS = {
    "production": "http://bcgmds01.als.lbl.gov",#"https://experiment.als.lbl.gov/",  # Latest STABLE version of the API
    "backup": "https://experiment2.als.lbl.gov:8083/",  # Redundant copy of the production server
    "staging": "https://experiment-staging.als.lbl.gov/",  # Latest TESTING version of the API
}
ALSHUB_API_BASE_URL = ALSHUB_API_SERVERS["production"]
EXPERIMENT_API_BASE_URL = EXPERIMENT_API_SERVERS["production"]

load_dotenv("./.env")  # import environment variables from .env

try:
    API_KEY = os.environ['ALSHUB_API_KEY']
    ALSHUB_API_HEADERS = {'api-key': API_KEY}
    _API_KEY_AVAILABLE = True
except KeyError:
    logger.warning(
        "ALSHUB_API_KEY not set — ALS Hub API calls will be skipped. "
        "Set this env var to enable ESAF/proposal lookup."
    )
    ALSHUB_API_HEADERS = {}
    _API_KEY_AVAILABLE = False

client = httpx.Client(base_url='https://bcgmds01.als.lbl.gov', headers=ALSHUB_API_HEADERS)


def setupQuery():
    if not _API_KEY_AVAILABLE:
        logger.warning("setupQuery: skipped, no ALSHUB_API_KEY.")
        return
    try:
        query = "/als-cycles/relative"
        response = client.get(query)
        response.raise_for_status()
        global user_cycle_times
        user_cycle_times = response.json()
        global user_cycle
        user_cycle = "Current ALS Cycle"
        global start_time
        start_time = user_cycle_times[user_cycle]["start"]
        global stop_time
        stop_time = user_cycle_times[user_cycle]["stop"]
    except Exception as e:
        logger.warning("setupQuery failed: %s", e, exc_info=True)
        raise


def getCurrentProposalList():
    if not _API_KEY_AVAILABLE:
        logger.warning("getCurrentProposalList: skipped, no ALSHUB_API_KEY.")
        return []
    try:
        setupQuery()
        query = f"/{beamline}?start={start_time}&stop={stop_time}"
        response = client.get(query)
        response.raise_for_status()
        active_experiments = response.json()
        if not isinstance(active_experiments, list):
            logger.warning("getCurrentProposalList: unexpected response format: %s", active_experiments)
            return []
        return [b["ProposalFriendlyId"] for b in active_experiments]
    except Exception as e:
        logger.warning("getCurrentProposalList failed: %s", e, exc_info=True)
        return []


def getCurrentEsafList(beamline=beamline):
    if not _API_KEY_AVAILABLE:
        logger.warning("getCurrentEsafList: skipped, no ALSHUB_API_KEY.")
        return [], []
    try:
        setupQuery()
        query = f"/{beamline}?start={start_time}&stop={stop_time}"
        response = client.get(query)
        response.raise_for_status()
        active_experiments = response.json()
        if not isinstance(active_experiments, list):
            logger.warning("getCurrentEsafList: unexpected response format: %s", active_experiments)
            return [], []
        esaf_list = [b["EsafFriendlyId"] for b in active_experiments]
        participants_list = [
            [p['Name'] for p in exp.get('Participants', [])]
            for exp in active_experiments
        ]
        return esaf_list, participants_list
    except Exception as e:
        logger.warning("getCurrentEsafList failed: %s", e, exc_info=True)
        return [], []
