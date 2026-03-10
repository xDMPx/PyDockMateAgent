from pathlib import Path
import os
import time
import json
import docker
import sys
from pydockmate_dataclasses import Container, ContainerStat
from requests_utils import delete_host_container, get_host_containers, get_host_uuid, ping, register_agent, register_container, update_heartbeat

import asyncio
from rstream import Producer

# 5GB
STREAM_RETENTION = 5000000000


async def send(host: str, username, password, stream_name: str, message: str):
    async with Producer(
            host=host,
            username=username,
            password=password
    ) as producer:
        await producer.create_stream(
            stream_name, exists_ok=True, arguments={"max-length-bytes": STREAM_RETENTION}
        )

        await producer.send(stream=stream_name, message=message.encode())
        print(f"[x] {message} sent")


client = docker.from_env()
agent_version = "0.0.1-dev"


def config_dir() -> Path:
    xdg = os.getenv("XDG_CONFIG_HOME")
    if xdg:
        base = Path(xdg)
    else:
        home = os.getenv("HOME")
        if not home:
            raise RuntimeError("HOME not set")
        base = Path(home) / ".config"

    return base / "PyDockMateAgent"


def load_agent_id_from_config() -> str | None:
    try:
        cfg_dir = config_dir()
        cfg_file = cfg_dir / "config"
        if cfg_file.is_file():
            return cfg_file.read_text()
        else:
            return None
    except Exception:
        return None


def save_agent_id_to_config(url: str) -> None:
    try:
        cfg_dir = config_dir()
        cfg_dir.mkdir(parents=True, exist_ok=True)
        cfg_file = cfg_dir / "config"
        cfg_file.write_text(url)
    except Exception as e:
        raise RuntimeError(f"Failed to write config: {e}") from e


async def main():
    hub_address = ""
    if len(sys.argv) != 2:
        print("Provided ip or domain", file=sys.stderr)
        sys.exit(1)
    hub_address = sys.argv.pop()
    # TODO: validate
    rabbitmq_username = os.getenv("RABBITMQ_USERNAME")
    rabbitmq_password = os.getenv("RABBITMQ_PASSWORD")
    if rabbitmq_username is None:
        rabbitmq_username = "admin"
    if rabbitmq_password is None:
        rabbitmq_password = "password"

    ping_ok = await ping(hub_address)
    if not ping_ok:
        print(f"Could not reach PyDockMate Hub at {hub_address}", file=sys.stderr)
        sys.exit(1)

    agent_uuid = load_agent_id_from_config()
    if agent_uuid is None:
        agent_uuid = await register_agent(client, hub_address, agent_version)
        save_agent_id_to_config(agent_uuid)
        host_uuid = await get_host_uuid(hub_address, agent_uuid)
        await register_docker_containers(hub_address, host_uuid)
    host_uuid = await get_host_uuid(hub_address, agent_uuid)
    print(host_uuid)
    while True:
        await update(hub_address, rabbitmq_username, rabbitmq_password, agent_uuid, host_uuid)


async def update(hub_address: str, rabbitmq_username: str, rabbitmq_password: str, agent_uuid: str, host_uuid: str):
    update_tasks = [update_heartbeat(hub_address, agent_uuid),
                    update_containers(hub_address, rabbitmq_username, rabbitmq_password, host_uuid),
                    asyncio.sleep(60)]
    await asyncio.gather(*update_tasks)


async def register_docker_containers(hub_address: str, host_uuid: str):
    containers = await get_containers_from_docker_client()
    register_container_tasks = [
        asyncio.create_task(register_container(hub_address, host_uuid, container))
        for container in containers
    ]
    await asyncio.gather(*register_container_tasks)


async def _register_container(hub_address: str, host_uuid: str, container: Container):
    await register_container(hub_address, host_uuid, container)
    print(f"Registered container: {container}")

async def _delete_host_container(hub_address: str, host_uuid: str, container: Container):
    if container.uuid != None:
        await delete_host_container(hub_address, host_uuid, container.uuid)
        print(f"Removed container: {container}")

async def update_containers(hub_address: str, rabbitmq_username: str, rabbitmq_password: str, host_uuid: str):
    registered_containers = await get_host_containers(hub_address, host_uuid)
    system_containers = await get_containers_from_docker_client()
    diff_ids = set(c.id for c in system_containers) - set(c.id for c in registered_containers)
    diff = list(filter(lambda c: c.id in diff_ids, system_containers)) 
    
    asyncio.gather(*[asyncio.create_task(_register_container(hub_address, host_uuid, container)) for container in diff])

    registered_containers = await get_host_containers(hub_address, host_uuid)
    system_containers = await get_containers_from_docker_client()
    diff_ids = set(c.id for c in registered_containers) - set(c.id for c in system_containers)
    diff = list(filter(lambda c: c.id in diff_ids, registered_containers))

    asyncio.gather(*[asyncio.create_task(_delete_host_container(hub_address,host_uuid,container)) for container in diff])

    containers_to_update = await get_host_containers(hub_address, host_uuid)
    await update_containers_stats(containers_to_update, hub_address, rabbitmq_username, rabbitmq_password, host_uuid)


async def update_containers_stats(containers_to_update: list[Container], hub_address: str, rabbitmq_username: str, rabbitmq_password: str, host_uuid: str):
    update_tasks = [
        asyncio.create_task(update_container_stats(container, hub_address, rabbitmq_username, rabbitmq_password, host_uuid))
        for container in containers_to_update
    ]
    await asyncio.gather(*update_tasks)


async def update_container_stats(container: Container, hub_address: str, rabbitmq_username: str, rabbitmq_password: str, host_uuid: str):
    c = await asyncio.to_thread(client.containers.get, container.id)
    if container.uuid == None:
        return
    stats = await asyncio.to_thread(c.stats, stream=False)
    if not isinstance(stats, dict):
        return

    cpu_perc = None
    memory_prec = None
    network_rx_bytes = None
    # https://stackoverflow.com/a/77924494
    try:
        cpu_usage = (stats["cpu_stats"]["cpu_usage"]["total_usage"] - stats["precpu_stats"]["cpu_usage"]["total_usage"])
        cpu_system = (stats["cpu_stats"]["system_cpu_usage"] - stats["precpu_stats"]["system_cpu_usage"])
        num_cpus = stats["cpu_stats"]["online_cpus"]
        cpu_perc = round((cpu_usage / cpu_system) * num_cpus * 100, 2)
    except: pass
    try: 
        mem_bytes_used = stats["memory_stats"]["usage"]
        mem_bytes_avail = stats["memory_stats"]["limit"]
        memory_prec = round(mem_bytes_used/mem_bytes_avail*100, 2)
    except: pass
    try:
        rx_bytes = 0
        for interface in stats["networks"]:
            rx_bytes += int(stats["networks"][interface]["rx_bytes"])
        network_rx_bytes = str(rx_bytes)
    except: pass

    cs = ContainerStat(
        container_uuid=container.uuid,
        status=c.status,
        cpu=cpu_perc,
        memory=memory_prec,
        network_rx_bytes=network_rx_bytes,
        timestamp=str(time.time()),
    )
    await send(hub_address, rabbitmq_username, rabbitmq_password, host_uuid, json.dumps(cs.__dict__))


async def get_containers_from_docker_client() -> list[Container]:
    containers = await asyncio.to_thread(client.containers.list, all=True)
    containers_list = [
        Container(
            uuid=None,
            id=str(c.id),
            image=(c.image.tags[0] if c.image else ""),
            command=str(c.attrs["Path"]),
            created=str(c.attrs["Created"]),
            ports=str(c.ports),
            name=str(c.name)
        )
        for c in containers
    ]
    return containers_list


if __name__ == "__main__":
    asyncio.run(main())
