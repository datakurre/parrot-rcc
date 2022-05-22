from dataclasses import dataclass
from enum import Enum
import multiprocessing


class LogLevel(str, Enum):
    DEBUG = "debug"
    ERROR = "error"
    INFO = "info"
    WARN = "warn"
    WARNING = "warning"

    def __repr__(self):
        return f"{self}".upper()

    def __str__(self):
        return super().__str__().upper()


@dataclass
class Options:
    rcc_executable: str = "rcc"
    rcc_controller: str = "parrot-rcc"
    rcc_fixed_spaces: bool = False
    rcc_telemetry: bool = False

    task_timeout_ms: int = (60 * 60 * 1000,)  # one hour
    task_max_jobs: int = (multiprocessing.cpu_count(),)

    log_level: LogLevel = "info"

    zeebe_hostname: str = "localhost"
    zeebe_port: int = 26500

    camunda_client_id: str = ""
    camunda_client_secret: str = ""
    camunda_cluster_id: str = ""
    camunda_region: str = ""

    @property
    def insecure(self) -> bool:
        return not all(
            [
                self.camunda_client_id,
                self.camunda_client_secret,
                self.camunda_cluster_id,
                self.camunda_region,
            ]
        )
