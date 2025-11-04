import json
import logging
import os
import time
from dotenv import load_dotenv
from httpx import Client as HttpClient, ConnectTimeout, Response

beamline = "7.0.1.2"
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
logger.addHandler(logging.StreamHandler())

ALSHUB_API_SERVERS = {
    "production": "https://api1-prd.als.lbl.gov:8083/alshub/",  # Latest STABLE version of the API
    "backup": "https://bl402ca.als.lbl.gov:8088/alshub/",  # Redundant copy of the production server
    "staging": "https://api1-stg.als.lbl.gov:8083/alshub/",  # Latest TESTING version of the API
}

EXPERIMENT_API_SERVERS = {
    "production": "http://bcgmds01.dhcp.lbl.gov:8080/beamlines",#"https://experiment.als.lbl.gov/",  # Latest STABLE version of the API
    "backup": "https://experiment2.als.lbl.gov:8083/",  # Redundant copy of the production server
    "staging": "https://experiment-staging.als.lbl.gov/",  # Latest TESTING version of the API
}
ALSHUB_API_BASE_URL = ALSHUB_API_SERVERS["production"]
EXPERIMENT_API_BASE_URL = EXPERIMENT_API_SERVERS["production"]

load_dotenv("./.env")  # import environment variables from .env

try:
    API_KEY = os.environ['ALSHUB_API_KEY']
    ALSHUB_API_HEADERS = {'api-key': API_KEY}
except KeyError:
    error_message = "Create a file named '.env' in the same directory as this notebook."
    error_message += " In that file, paste this text...\n"
    error_message += "ALSHUB_API_KEY='your-api-key-goes-here-inside-the-quotes'\n"
    error_message += "\n\nFix this before running any more cells in this notebook."
    logger.error(error_message)

def connection_guard(func):
    """Decorator to log a user-friendly message when the server does not respond"""
    def decorator(*args, **kwargs):
        try:
            response = func(*args, **kwargs)
        except ConnectTimeout:
            error_message = "Server is not responding."
            error_message += " Ask Dylan and Padraic to add your IP address to the firewall settings."
            error_message += "\nTry another API server in the meantime."
            logger.error(error_message)
            response = None
        return response
    return decorator

def authorization_guard(func):
    """Decorator to log a user-friendly message when the server rejects a request"""
    def decorator(*args, **kwargs):
        response = func(*args, **kwargs)
        if response.status_code == 403:
            error_message = "Request is not authorized. Your API key might be missing."
            error_message += " Create a file named '.env' in the same directory as this notebook."
            error_message += " In that file, paste this text...\n"
            error_message += "ALSHUB_API_KEY='your-api-key-goes-here-inside-the-quotes'\n"
            error_message += "\nIf that does not work, ask Padraic to add your IP address to the firewall settings."
            error_message += "\nTry another API server in the meantime."
            logger.error(error_message)
        return response
    return decorator

@connection_guard
@authorization_guard
def api_response(
        query: str,
        *,
        base_url: str = EXPERIMENT_API_BASE_URL,
        headers: dict = ALSHUB_API_HEADERS,
        timeout: float = 2.0,
) -> Response:
    """Fetch the response to an API query"""
    response = None
    with HttpClient(
            base_url=base_url,
            headers=headers,
            timeout=timeout,
    ) as api_client:
        response = api_client.get(query)
    return response

def api_streaming_response(
        query: str,
        *,
        base_url: str = EXPERIMENT_API_BASE_URL,
        headers: dict = ALSHUB_API_HEADERS,
        timeout: float = 2.0,
) -> Response:
    """Fetch the response to an API query"""
    responses = list()
    with HttpClient(
            base_url=base_url,
            headers=headers,
            timeout=timeout,
    ) as api_client:
        content = ''
        _start_time = time.monotonic()
        with api_client.stream("GET", query) as response:
            for (idx, chunk) in enumerate(response.iter_text()):
                content += chunk
                responses.append((time.monotonic() - _start_time, f"Received chunk# {idx}"))
    return {"responses": responses, "status_code": response.status_code, "content": content}

def setupQuery():
    query = "/als-cycles/relative"
    response = api_response(query, base_url=EXPERIMENT_API_BASE_URL)
    response.json()
    global user_cycle_times
    user_cycle_times = response.json()
    global user_cycle
    user_cycle = "Current ALS Cycle"
    global start_time
    start_time = user_cycle_times[user_cycle]["start"]
    global stop_time
    stop_time = user_cycle_times[user_cycle]["stop"]

def getCurrentProposalList():
    setupQuery()
    query = f"/{beamline}?start={start_time}&stop={stop_time}"
    response = api_response(query, base_url=EXPERIMENT_API_BASE_URL)
    active_experiments = response.json()
    return [b["ProposalFriendlyId"] for b in active_experiments]

def getCurrentEsafList(beamline = beamline):
    setupQuery()
    query = f"/{beamline}?start={start_time}&stop={stop_time}"
    response = api_response(query, base_url=EXPERIMENT_API_BASE_URL)
    active_experiments = response.json()
    esaf_list = [b["EsafFriendlyId"] for b in active_experiments]
    participants_list = []
    i = 0
    for i in range(len(esaf_list)):
        participants_list.append([active_experiments[i]['Participants'][j]['Name'] for j in range(len(active_experiments[i]['Participants']))])
    return esaf_list, participants_list



