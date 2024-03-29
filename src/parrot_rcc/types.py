from dataclasses import dataclass
from enum import Enum
from typing import Optional
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


class ItemReleaseState(str, Enum):
    """Work item state. (set when released)"""

    DONE = "COMPLETED"
    FAILED = "FAILED"

    def __repr__(self):
        return f"{self}".upper()

    def __str__(self):
        return super().__str__().upper()


class ItemReleaseExceptionType(str, Enum):
    """Work item state. (set when released)"""

    APPLICATION = "APPLICATION"
    BUSINESS = "BUSINESS"

    def __repr__(self):
        return f"{self}".upper()

    def __str__(self):
        return super().__str__().upper()


@dataclass
class ItemReleaseException:
    type: ItemReleaseExceptionType
    code: str
    message: str


@dataclass
class ItemRelease:
    state: ItemReleaseState
    exception: Optional[ItemReleaseException]


@dataclass
class Options:
    business_key: str = "businessKey"
    rcc_executable: str = "rcc"
    rcc_controller: str = "parrot-rcc"
    rcc_fixed_spaces: bool = False
    rcc_telemetry: bool = False

    rcc_s3_url: str = "http://localhost:9000"
    rcc_s3_access_key_id: str = "minioadmin"
    rcc_s3_secret_access_key: str = "minioadmin"
    rcc_s3_region: str = "us-east-1"
    rcc_s3_bucket_logs: str = "rcc"
    rcc_s3_bucket_data: str = "zeebe"
    rcc_s3_url_expires_in: int = 3600 * 24 * 7  # one week

    task_timeout_ms: int = 60 * 60 * 1000  # one hour
    task_max_jobs: int = (multiprocessing.cpu_count(),)

    zeebe_hostname: str = "localhost"
    zeebe_port: int = 26500

    vault_addr: str = "http://127.0.0.1:8200"
    vault_token: str = "secret"

    healthz_hostname: str = ""
    healthz_port: int = 8001

    log_level: LogLevel = "info"
    debug: bool = False

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
