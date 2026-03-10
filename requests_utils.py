from pydockmate_dataclasses import AgentWithHost, Container, Host
from docker import DockerClient
import requests
import platform
import asyncio
import socket
import json

async def register_container(hub_address: str, host_uuid: str, container: Container):
    pydockmate_url = f"{hub_address}:8000"
    if not pydockmate_url.startswith("http"):
        pydockmate_url = f"http://{pydockmate_url}"
    register_url = f"{pydockmate_url}/api/host/{host_uuid}/container/register"

    headers = {
        "Content-Type": "application/json"
    }
    await asyncio.to_thread(requests.post, register_url, data=json.dumps(container.__dict__), headers=headers)


async def register_agent(client: DockerClient, hub_address: str, agent_version: str) -> str:
    pydockmate_url = f"{hub_address}:8000"
    if not pydockmate_url.startswith("http"):
        pydockmate_url = f"http://{pydockmate_url}"
    register_url = f"{pydockmate_url}/api/agent/register"

    hostname = await asyncio.to_thread(socket.gethostname)
    system = await asyncio.to_thread(platform.system)
    release = await asyncio.to_thread(platform.release)
    os = system + " " + release
    docker_version = (await asyncio.to_thread(client.version))["Version"]
    host = Host(hostname, os, docker_version)
    agent_with_host = AgentWithHost(agent_version, host)
    agent_with_host_json = agent_with_host_to_json(agent_with_host)
    print(agent_with_host_json)

    headers = {
        "Content-Type": "application/json"
    }

    response = await asyncio.to_thread(requests.post, register_url, data=agent_with_host_json, headers=headers)
    uuid: str = response.json()["uuid"]
    print(uuid)
    return uuid


async def get_host_uuid(hub_address: str, agent_uuid: str) -> str:
    pydockmate_url = f"{hub_address}:8000"
    if not pydockmate_url.startswith("http"):
        pydockmate_url = f"http://{pydockmate_url}"
    agent_host_id_url = f"{pydockmate_url}/api/agent/{agent_uuid}/host"

    response = await asyncio.to_thread(requests.get, agent_host_id_url)
    host_uuid = response.json()["host_uuid"]
    return host_uuid


async def get_host_containers(hub_address: str, host_uuid: str) -> list[Container]:
    pydockmate_url = f"{hub_address}:8000"
    if not pydockmate_url.startswith("http"):
        pydockmate_url = f"http://{pydockmate_url}"
    host_containers_id_url = f"{pydockmate_url}/api/host/{host_uuid}/containers"

    response = await asyncio.to_thread(requests.get, host_containers_id_url)
    json = response.json()
    containers = parse_containers_json(json)
    return containers


async def delete_host_container(hub_address: str, host_uuid: str, container_uuid: str):
    pydockmate_url = f"{hub_address}:8000"
    if not pydockmate_url.startswith("http"):
        pydockmate_url = f"http://{pydockmate_url}"
    destroy_containers_id_url = f"{pydockmate_url}/api/host/{host_uuid}/container/{container_uuid}/destroy"

    await asyncio.to_thread(requests.delete, destroy_containers_id_url)


async def ping(hub_address: str):
    pydockmate_url = f"{hub_address}:8000"
    if not pydockmate_url.startswith("http"):
        pydockmate_url = f"http://{pydockmate_url}"
    ping_url = f"{pydockmate_url}/api/ping"
    return (await asyncio.to_thread(requests.get, ping_url)).ok


async def update_heartbeat(hub_address: str, uuid: str):
    pydockmate_url = f"{hub_address}:8000"
    if not pydockmate_url.startswith("http"):
        pydockmate_url = f"http://{pydockmate_url}"
    heartbeat_url = f"{pydockmate_url}/api/agent/{uuid}/heartbeat/"
    response = await asyncio.to_thread(requests.put, heartbeat_url)
    print(response.text)


def agent_with_host_to_json(agent_with_host: AgentWithHost):
    agent_with_host_dict = agent_with_host.__dict__
    agent_with_host_dict["host"] = agent_with_host.host.__dict__
    return json.dumps(agent_with_host_dict)


def parse_containers_json(json: list[dict[str, str]]) -> list[Container]:
    containers_list = [
        Container(
            uuid=jo["uuid"],
            id=jo["id"],
            image=jo["image"],
            command=jo["command"],
            created=jo["created"],
            ports=jo["ports"],
            name=jo["name"]
        )
        for jo in json
    ]
    return containers_list
