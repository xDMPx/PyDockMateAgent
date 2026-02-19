from pathlib import Path
import os
import time
import requests
import socket
import platform
import json
import docker
import sys
from dataclasses import dataclass

client = docker.from_env()
agent_version = "0.0.1-dev"

@dataclass
class Host:
    hostname: str
    os: str
    docker_version: str

@dataclass
class AgentWithHost:
    version: str
    host: Host

def agent_with_host_to_json(agent_with_host: AgentWithHost):
    agent_with_host_dict = agent_with_host.__dict__
    agent_with_host_dict["host"] = agent_with_host.host.__dict__
    return json.dumps(agent_with_host_dict)

def main():
    hub_address = ""
    if len(sys.argv) != 2: 
        print("Provided ip or domain",file=sys.stderr)
        sys.exit(1)
    hub_address = sys.argv.pop()
    uuid = register_agent(hub_address)
    while True:
        update(hub_address, uuid)

def update(hub_address: str ,uuid: str):
    update_heartbeat(hub_address, uuid)
    time.sleep(60) 

def update_heartbeat(hub_address: str, uuid: str):
    pydockmate_url = f"{hub_address}:8000"
    if not pydockmate_url.startswith("http"):
        pydockmate_url = f"http://{pydockmate_url}"
    heartbeat_url = f"{pydockmate_url}/api/agent/{uuid}/heartbeat/"
    response = requests.put(heartbeat_url)
    print(response.text)

def register_agent(hub_address: str) -> str:
    pydockmate_url = f"{hub_address}:8000"
    if not pydockmate_url.startswith("http"):
        pydockmate_url = f"http://{pydockmate_url}"
    register_url = f"{pydockmate_url}/api/agent/register"

    hostname = socket.gethostname()
    os = platform.system() + " " + platform.release()
    docker_version = client.version()["Version"]
    host = Host(hostname,os,docker_version)
    agent_with_host = AgentWithHost(agent_version, host)
    agent_with_host_json = agent_with_host_to_json(agent_with_host)
    print(agent_with_host_json)


    headers = {
        "Content-Type": "application/json"
    }

    response = requests.post(register_url, data=agent_with_host_json, headers=headers)
    uuid: str = response.json()["uuid"]
    print(uuid)
    return uuid 

if __name__ == "__main__":
    main()
