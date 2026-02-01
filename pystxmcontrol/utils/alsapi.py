import json
import logging
import os
import time
from dotenv import load_dotenv
from httpx import Client as HttpClient, ConnectTimeout, Response
import httpx

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
except KeyError:
    print("ERROR: API Key not found.")

client = httpx.Client(base_url = 'https://bcgmds01.als.lbl.gov',headers=ALSHUB_API_HEADERS)

def setupQuery():
    query = "/als-cycles/relative"
    response = client.get(query)
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
    response = client.get(query)
    active_experiments = response.json()
    return [b["ProposalFriendlyId"] for b in active_experiments]

def getCurrentEsafList(beamline = beamline):
    setupQuery()
    query = f"/{beamline}?start={start_time}&stop={stop_time}"
    response = client.get(query)
    active_experiments = response.json()
    esaf_list = [b["EsafFriendlyId"] for b in active_experiments]
    participants_list = []
    i = 0
    for i in range(len(esaf_list)):
        participants_list.append([active_experiments[i]['Participants'][j]['Name'] for j in range(len(active_experiments[i]['Participants']))])
    return esaf_list, participants_list



