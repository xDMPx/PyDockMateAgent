from dataclasses import dataclass

@dataclass
class Host:
    hostname: str
    os: str
    docker_version: str


@dataclass
class AgentWithHost:
    version: str
    host: Host


@dataclass
class Container:
    uuid: str | None
    id: str
    image: str
    command: str
    created: str
    ports: str
    name: str


@dataclass
class ContainerStat:
    container_uuid: str
    status: str
    cpu: str | None
    memory: str | None
    timestamp: str
