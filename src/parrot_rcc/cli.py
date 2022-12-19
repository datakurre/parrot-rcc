from os.path import basename
from parrot_rcc.adapter import ZeebeVariablesAdapter
from parrot_rcc.errors import ItemReleaseWithBusinessError
from parrot_rcc.errors import ItemReleaseWithFailure
from parrot_rcc.errors import ReleaseException
from parrot_rcc.s3 import s3_generate_presigned_url
from parrot_rcc.s3 import s3_list_files
from parrot_rcc.s3 import s3_put_object
from parrot_rcc.s3 import s3_upload_file
from parrot_rcc.types import ItemRelease
from parrot_rcc.types import ItemReleaseException
from parrot_rcc.types import ItemReleaseExceptionType
from parrot_rcc.types import ItemReleaseState
from parrot_rcc.types import LogLevel
from parrot_rcc.types import Options
from parrot_rcc.utils import inline_screenshots
from parrot_rcc.utils import setup_logging
from pathlib import Path
from pyzeebe import create_camunda_cloud_channel
from pyzeebe import create_insecure_channel
from pyzeebe import Job
from pyzeebe import JobStatus
from pyzeebe import TaskConfig
from pyzeebe import ZeebeWorker
from pyzeebe.task import task_builder
from tempfile import TemporaryDirectory
from typing import Dict
from typing import List
from typing import Tuple
from zipfile import ZipFile
import asyncio
import boto3
import click
import dataclasses
import json
import logging
import multiprocessing
import os
import pprint
import re
import uvloop
import yaml


os.environ["GRPC_ENABLE_FORK_SUPPORT"] = "0"

logger = logging.getLogger(__name__)

WORK_ITEM_ADAPTER = """\
from RPA.Robocorp.WorkItems import FileAdapter, RobocorpAdapter
from RPA.Robocorp.utils import Requests
from urllib.parse import urlparse

import os
import json
import logging

class WorkItemAdapter(FileAdapter):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._workitem_requests = Requests("", default_headers={})

    def release_input(self, item_id, state, exception=None):
        body = {"workItemId": item_id, "state": state.value}
        if exception:
            body["exception"] = {
                "type": (exception.get("type") or "").strip(),
                "code": (exception.get("code") or "").strip(),
                "message": (exception.get("message") or "").strip(),
            }
        path = os.environ["RPA_RELEASE_WORKITEM_PATH"]
        with open(path, "w", encoding="utf-8") as fp:
            fp.write(json.dumps(body))
        super(WorkItemAdapter, self).release_input(item_id, state, exception)

    def get_file(self, item_id: str, name: str) -> bytes:
        source, item = self._get_item(item_id)
        files = item.get("files", {})
        path = files[name]
        if urlparse(path).scheme in ["http", "https"]:
            # Path is expected to be S3 presigned URL
            logging.info("Downloading work item file at: %s", item_id)
            # Perform the actual file download.
            response = self._workitem_requests.get(
                path,
                _handle_error=lambda resp: resp.raise_for_status(),
                _sensitive=True,
                headers={},
            )
            return response.content
        else:
            return super().get_file(item_id, name)
"""


def job_to_dict(job: Job) -> dict:
    return {
        "jobKey": job.key,
        "taskType": job.type,
        "processInstanceKey": job.process_instance_key,
        "bpmnProcessId": job.bpmn_process_id,
        "processDefinitionVersion": job.process_definition_version,
        "processDefinitionKey": job.process_definition_key,
        "elementId": job.element_id,
        "elementInstanceKey": job.element_instance_key,
        "customHeaders": job.custom_headers,
        "worker": job.worker,
        "retries": job.retries,
        "deadline": job.deadline,
        "variables": job.variables,
    }


class lazypprint:
    def __init__(self, data):
        self.data = data

    def __str__(self):
        return pprint.pformat(self.data)


class lazydecode:
    def __init__(self, *data: bytes):
        self.data = data

    def __str__(self):
        return "\n".join([b.decode() for b in self.data])


async def run(
    program: str, args: List[str], cwd: str, env: Dict[str, str]
) -> Tuple[int, bytes, bytes]:
    logger.debug(f"{program + ' ' + ' '.join(map(str, args))}")
    proc = await asyncio.create_subprocess_exec(
        program,
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=cwd,
        env=os.environ | env | {"PYTHONPATH": ""},
    )

    stdout, stderr = await proc.communicate()
    stdout = stdout.strip() or b""
    stderr = stderr.strip() or b""

    if stderr:
        logger.debug("%s", lazydecode(stderr))
    if stdout:
        logger.debug("%s", lazydecode(stdout))

    logger.debug(f"exit code {proc.returncode}")

    return proc.returncode, stdout, stderr


def fail_reason(robot_dir: str) -> str:
    reason = ""
    for file_path in Path(robot_dir).glob("*/**/output.xml"):
        xml = file_path.read_text()
        for match in re.findall(r'status="FAIL"[^>]*.([^<]*)', xml, re.M):
            match = match.strip()
            reason = match if match else reason
    return reason


def create_task(task: str, robot: str, semaphore: asyncio.Semaphore, config: Options):
    task_config = TaskConfig(
        type=task,
        exception_handler=on_error,
        timeout_ms=config.task_timeout_ms,
        max_jobs_to_activate=config.task_max_jobs,
        max_running_jobs=config.task_max_jobs,
        variables_to_fetch=[],
        single_value=False,
        variable_name="",
        before=[before_job],
        after=[after_job],
    )

    async def execute_task(
        __process_instance_key: int, __element_instance_key: int, **kwargs
    ):
        async with semaphore:
            # https://gist.github.com/heitorlessa/5b709df96ea6ac5ddc600545c0683d3b
            s3_client = boto3.client(
                "s3",
                endpoint_url=config.rcc_s3_url,
                aws_access_key_id=config.rcc_s3_access_key_id,
                aws_secret_access_key=config.rcc_s3_secret_access_key,
                aws_session_token=None,
                config=boto3.session.Config(signature_version="s3v4"),
                region_name=config.rcc_s3_region,
                verify=False,
            )
            s3_resource = boto3.resource(
                "s3",
                endpoint_url=config.rcc_s3_url,
                aws_access_key_id=config.rcc_s3_access_key_id,
                aws_secret_access_key=config.rcc_s3_secret_access_key,
                aws_session_token=None,
                config=boto3.session.Config(signature_version="s3v4"),
                region_name=config.rcc_s3_region,
                verify=False,
            )
            if config.rcc_fixed_spaces:
                space = "parrot-" + (
                    "".join(re.findall(r"[\w-]", re.sub(r"\W+", "-", task.lower())))
                    or "0000"
                )
            else:
                idx = config.task_max_jobs - semaphore._value
                space = f"parrot-{idx:04}"
            with TemporaryDirectory() as robot_dir, TemporaryDirectory() as data_dir:
                return_code, stdout, stderr = await run(
                    config.rcc_executable,
                    ["robot", "unwrap", "-d", robot_dir, "-z", robot],
                    os.getcwd(),
                    {},
                )
                assert return_code == 0, lazydecode(stderr)

                (Path(robot_dir) / "WorkItemAdapter.py").write_text(
                    WORK_ITEM_ADAPTER, encoding="utf-8"
                )
                vault_json_path = Path(data_dir) / "vault.json"
                items_json_path = Path(data_dir) / "items.json"
                output_json_path = Path(data_dir) / "items.output.json"
                release_json_path = Path(data_dir) / "items.release.json"
                with open(vault_json_path, "w", encoding="utf-8") as fp:
                    fp.write(json.dumps({"env": dict(os.environ)}, indent=4))
                items_files = {}
                for key in await s3_list_files(
                    s3_resource,
                    config.rcc_s3_bucket_data,
                    f"{__process_instance_key}/",
                ):
                    file_path = Path(data_dir) / key.split(",", 1)[-1]
                    file_path.parent.mkdir(parents=True, exist_ok=True)
                    items_files[basename(key)] = await s3_generate_presigned_url(
                        s3_client,
                        config.rcc_s3_bucket_data,
                        key,
                        max(1, int(config.task_timeout_ms / 1000)),
                    )

                with open(items_json_path, "w", encoding="utf-8") as fp:
                    items_json_dump = json.dumps(
                        [
                            {
                                "payload": kwargs,
                                "files": items_files,
                            }
                        ],
                        indent=4,
                    )
                    fp.write(items_json_dump)
                    logger.debug("Work item: %s", items_json_dump)

                return_code, stdout, stderr = await run(
                    config.rcc_executable,
                    [
                        "run",
                        "--controller",
                        config.rcc_controller,
                        "--space",
                        space,
                        "--task",
                        task,
                    ],
                    robot_dir,
                    {
                        "RPA_SECRET_MANAGER": "RPA.Robocloud.Secrets.FileSecrets",
                        "RPA_SECRET_FILE": f"{vault_json_path}",
                        "RPA_WORKITEMS_ADAPTER": "WorkItemAdapter.WorkItemAdapter",
                        "RPA_INPUT_WORKITEM_PATH": f"{items_json_path}",
                        "RPA_OUTPUT_WORKITEM_PATH": f"{output_json_path}",
                        "RPA_RELEASE_WORKITEM_PATH": f"{release_json_path}",
                        "RC_WORKSPACE_ID": "1",
                        "RC_WORKITEM_ID": "1",
                    },
                )

                files = {}
                payload = {}
                if output_json_path.exists():
                    with open(output_json_path, "r", encoding="utf-8") as fp:
                        output_json = json.loads(fp.read())
                        for item in output_json:
                            files = item.get("files") or {}
                            payload = item.get("payload") or {}
                            break

                for key, value in files.items():
                    file_path = (
                        Path(data_dir) / value
                        if (Path(data_dir) / value).exists()
                        else value
                        if value.exists()
                        else None
                    )
                    if file_path:
                        await s3_upload_file(
                            s3_client,
                            str(file_path),
                            config.rcc_s3_bucket_data,
                            f"{__process_instance_key}/{key}",
                        )
                        payload[key] = await s3_generate_presigned_url(
                            s3_client,
                            config.rcc_s3_bucket_data,
                            f"{__process_instance_key}/{key}",
                            config.rcc_s3_url_expires_in,
                        )

                for file_path in Path(robot_dir).glob("*/**/log.html"):
                    inline_screenshots(str(file_path))
                    await s3_upload_file(
                        s3_client,
                        str(file_path),
                        config.rcc_s3_bucket_logs,
                        f"{__process_instance_key}/{__element_instance_key}/log.html",
                    )
                    payload["log.html"] = await s3_generate_presigned_url(
                        s3_client,
                        config.rcc_s3_bucket_logs,
                        f"{__process_instance_key}/{__element_instance_key}/log.html",
                        config.rcc_s3_url_expires_in,
                    )
                for file_path in Path(robot_dir).glob("*/**/output.xml"):
                    inline_screenshots(str(file_path))
                    await s3_upload_file(
                        s3_client,
                        str(file_path),
                        config.rcc_s3_bucket_logs,
                        f"{__process_instance_key}/{__element_instance_key}/output.xml",
                    )
                    payload["output.xml"] = await s3_generate_presigned_url(
                        s3_client,
                        config.rcc_s3_bucket_logs,
                        f"{__process_instance_key}/{__element_instance_key}/output.xml",
                        config.rcc_s3_url_expires_in,
                    )
                await s3_put_object(
                    s3_client,
                    config.rcc_s3_bucket_logs,
                    f"{__process_instance_key}/{__element_instance_key}/stdout.txt",
                    stdout,
                    "text/plain",
                )
                payload["stdout.txt"] = await s3_generate_presigned_url(
                    s3_client,
                    config.rcc_s3_bucket_logs,
                    f"{__process_instance_key}/{__element_instance_key}/stdout.txt",
                    config.rcc_s3_url_expires_in,
                )
                await s3_put_object(
                    s3_client,
                    config.rcc_s3_bucket_logs,
                    f"{__process_instance_key}/{__element_instance_key}/stderr.txt",
                    stderr,
                    "text/plain",
                )
                payload["stderr.txt"] = await s3_generate_presigned_url(
                    s3_client,
                    config.rcc_s3_bucket_logs,
                    f"{__process_instance_key}/{__element_instance_key}/stderr.txt",
                    config.rcc_s3_url_expires_in,
                )

                # Fail job with non-zero exit code
                if return_code != 0:
                    reason = fail_reason(robot_dir)
                    raise ReleaseException(
                        code="",
                        message=reason
                        or "".join([stderr.decode(), stdout.decode()]).strip(),
                        payload=payload,
                    )

                # Resolve possible item release state
                if release_json_path.exists():
                    with open(release_json_path, "r", encoding="utf-8") as fp:
                        release_json = json.loads(fp.read())
                else:
                    release_json = {}
                release = ItemRelease(
                    state=ItemReleaseState.FAILED
                    if release_json.get("state") == "FAILED"
                    else ItemReleaseState.DONE,
                    exception=None
                    if not release_json.get("exception")
                    else ItemReleaseException(
                        type=ItemReleaseExceptionType.BUSINESS
                        if (release_json.get("exception") or {}).get("type")
                        == "BUSINESS"
                        else ItemReleaseExceptionType.APPLICATION,
                        code=(release_json.get("exception") or {}).get("code") or "",
                        message=(release_json.get("exception") or {}).get("message")
                        or "",
                    ),
                )

                # Raise possible release exception
                if release.state == ItemReleaseState.FAILED:
                    if release.exception.type == ItemReleaseExceptionType.BUSINESS:
                        raise ItemReleaseWithBusinessError(
                            release.exception.message,
                            code=release.exception.code,
                            payload=payload,
                        )
                    else:
                        raise ItemReleaseWithFailure(
                            release.exception.message,
                            code=release.exception.code,
                            payload=payload,
                        )

                return payload

    return execute_task, task_config


async def on_error(exception: Exception, job: Job):
    """
    on_error will be called when the task fails
    """
    logger.error(str(exception))
    if isinstance(exception, ItemReleaseWithBusinessError):
        # RPA.Robocorp.WorkItems business error
        job.variables = exception.payload
        await job.zeebe_adapter.set_variables(
            job.element_instance_key, job.variables, True
        )
        await job.set_error_status(str(exception), exception.code)
    elif isinstance(exception, ItemReleaseWithFailure):
        # RPA.Robocorp.WorkItems retryable application failure
        job.variables = exception.payload
        await job.zeebe_adapter.set_variables(
            job.element_instance_key, job.variables, True
        )
        await job.set_failure_status(str(exception) or exception.code)
    elif isinstance(exception, ReleaseException):
        # Robot Framework test / task failure -> fail job without retries
        job.variables = exception.payload
        await job.zeebe_adapter.set_variables(
            job.element_instance_key, job.variables, True
        )
        job.status = JobStatus.Failed
        await job.zeebe_adapter.fail_job(
            job_key=job.key, retries=0, message=str(exception)
        )
    else:
        # Unexpected exception -> fail job without retries
        message = f"Failed to handle job {job}. Error: {str(exception)}"
        job.status = JobStatus.Failed
        await job.zeebe_adapter.fail_job(job_key=job.key, retries=0, message=message)


class VariablesDict(dict):
    def update(self, d):
        # pyzeebe simply updates original job variables on worker completion
        # and returns all task variables back on job completion
        #
        # this patches it to only return variables returned by the worker
        self.clear()
        super().update(d)


async def before_job(job: Job) -> Job:
    # Ensure that job variables contain only the variables returned by the worker
    for name in list(job.variables.keys()):
        if "." in name:
            job.variables.pop(name)
    logger.debug("Before job: %s", lazypprint(job_to_dict(job)))
    job.variables = VariablesDict(
        job.variables
        | {
            "__process_instance_key": f"{job.bpmn_process_id}-{job.process_instance_key}",
            "__element_instance_key": f"{job.element_id}-{job.element_instance_key}",
        }
    )
    return job


async def after_job(job: Job) -> Job:
    # Save all variables as local variables and clear variables for complete call
    logger.debug("After job: %s", lazypprint(job_to_dict(job)))
    if job.status == JobStatus.Running:
        await job.zeebe_adapter.set_variables(
            job.element_instance_key, job.variables, True
        )
        job.variables.clear()
    return job


@click.command()
@click.argument("robots", nargs=-1, envvar="RCC_ROBOTS")
@click.option("--rcc-executable", default="rcc", envvar="RCC_EXECUTABLE")
@click.option("--rcc-controller", default="parrot-rcc", envvar="RCC_CONTROLLER")
@click.option(
    "--rcc-fixed-spaces",
    is_flag=True,
    default=False,
    envvar="RCC_FIXED_SPACES",
    help="Allows RCC to execute multiple tasks concurrently in the same dependency environment.",
)
@click.option(
    "--rcc-s3-url",
    default="http://localhost:9000",
    envvar="RCC_S3_URL",
    help="Base URL of the S3 compatible service used to store execution artifacts and work item files.",
)
@click.option(
    "--rcc-s3-access-key-id", default="minioadmin", envvar="RCC_S3_ACCESS_KEY_ID"
)
@click.option(
    "--rcc-s3-secret-access-key",
    default="minioadmin",
    envvar="RCC_S3_SECRET_ACCESS_KEY",
)
@click.option("--rcc-s3-region", default="us-east-1", envvar="RCC_S3_REGION")
@click.option("--rcc-s3-bucket-logs", default="rcc", envvar="RCC_S3_BUCKET_LOGS")
@click.option("--rcc-s3-bucket-data", default="zeebe", envvar="RCC_S3_BUCKET_DATA")
@click.option(
    "--rcc-s3-url-expires-in",
    default=3600 * 24 * 7,
    envvar="RCC_S3_URL_EXPIRES_IN",
    help="Amount of seconds after generated presigned URLs to download S3 stored files without further authorization expire.",
)
@click.option("--rcc-telemetry", is_flag=True, default=False, envvar="RCC_TELEMETRY")
@click.option("--task-timeout-ms", default=60 * 60 * 1000, envvar="TASK_TIMEOUT_MS")
@click.option(
    "--task-max-jobs", default=multiprocessing.cpu_count(), envvar="TASK_MAX_JOBS"
)
@click.option("--zeebe-hostname", default="localhost", envvar="ZEEBE_HOSTNAME")
@click.option("--zeebe-port", default=26500, envvar="ZEEBE_PORT")
@click.option("--camunda-client-id", default="", envvar="CAMUNDA_CLIENT_ID")
@click.option("--camunda-client-secret", default="", envvar="CAMUNDA_CLIENT_SECRET")
@click.option("--camunda-cluster-id", default="", envvar="CAMUNDA_CLIENT_SECRET")
@click.option("--camunda-region", default="", envvar="CAMUNDA_CLIENT_SECRET")
@click.option("--log-level", default="info", envvar="LOG_LEVEL")
@click.option("--debug", is_flag=True, default=False, envvar="DEBUG")
def main(
    robots,
    rcc_executable,
    rcc_controller,
    rcc_fixed_spaces,
    rcc_s3_url,
    rcc_s3_access_key_id,
    rcc_s3_secret_access_key,
    rcc_s3_region,
    rcc_s3_bucket_logs,
    rcc_s3_bucket_data,
    rcc_s3_url_expires_in,
    rcc_telemetry,
    task_timeout_ms,
    task_max_jobs,
    zeebe_hostname,
    zeebe_port,
    camunda_client_id,
    camunda_client_secret,
    camunda_cluster_id,
    camunda_region,
    log_level,
    debug,
):
    """Zeebe external task Robot Framework RCC client

    ROBOTS are RCC compatible automation code packages,
    which are most often created with `rcc robot wrap [-z robot.zip]`.
    They can also be passed as a space separated env RCC_ROBOTS

    """
    config = Options(
        rcc_executable=rcc_executable,
        rcc_controller=rcc_controller,
        rcc_fixed_spaces=rcc_fixed_spaces,
        rcc_s3_url=rcc_s3_url,
        rcc_s3_access_key_id=rcc_s3_access_key_id,
        rcc_s3_secret_access_key=rcc_s3_secret_access_key,
        rcc_s3_region=rcc_s3_region,
        rcc_s3_bucket_logs=rcc_s3_bucket_logs,
        rcc_s3_bucket_data=rcc_s3_bucket_data,
        rcc_s3_url_expires_in=rcc_s3_url_expires_in,
        rcc_telemetry=rcc_telemetry,
        task_timeout_ms=task_timeout_ms,
        task_max_jobs=task_max_jobs,
        zeebe_hostname=zeebe_hostname,
        zeebe_port=zeebe_port,
        camunda_client_id=camunda_client_id,
        camunda_client_secret=camunda_client_secret,
        camunda_cluster_id=camunda_cluster_id,
        camunda_region=camunda_region,
        log_level=LogLevel(log_level) if not debug else LogLevel("debug"),
        debug=debug,
    )

    setup_logging(logger, config.log_level, debug)
    logger.info(
        dataclasses.replace(
            config,
            camunda_client_secret="*" * 8,
            rcc_s3_access_key_id="*" * 8,
            rcc_s3_secret_access_key="*" * 8,
        )
    )

    if len(robots) == 1 and "," in robots[0]:
        robots = [x.strip() for x in robots[0].split(",")]

    tasks = {}
    for robot in robots:
        robot = Path(robot)
        if not robot.exists():
            continue
        with ZipFile(robot, "r") as fp:
            robot_yaml = yaml.safe_load(fp.read("robot.yaml"))
            for task in robot_yaml.get("tasks") or {}:
                tasks[task] = robot.resolve()

    uvloop.install()

    if config.insecure:
        channel = create_insecure_channel(
            hostname=config.zeebe_hostname,
            port=config.zeebe_port,
        )
    else:
        channel = create_camunda_cloud_channel(
            client_id=config.camunda_client_id,
            client_secret=config.camunda_client_secret,
            cluster_id=config.camunda_cluster_id,
            region=config.camunda_region,
        )

    worker = ZeebeWorker(channel)
    worker.zeebe_adapter.__class__.__bases__ = (
        worker.zeebe_adapter.__class__.__bases__ + (ZeebeVariablesAdapter,)
    )
    semaphore = asyncio.Semaphore(config.task_max_jobs)

    for task, robot in tasks.items():
        worker._add_task(
            task_builder.build_task(*create_task(task, str(robot), semaphore, config))
        )

    loop = asyncio.get_event_loop()
    if tasks:
        logger.info("Tasks: %s", lazypprint(tasks))
        return_code, stdout, stderr = loop.run_until_complete(
            run(
                config.rcc_executable,
                ["configuration", "identity", "-e" if config.rcc_telemetry else "-t"],
                os.getcwd(),
                {},
            )
        )
        assert return_code == 0, lazydecode(stderr)
        loop.run_until_complete(worker.work())
    else:
        logger.error("No tasks: %s", lazypprint(tasks))
        loop.run_until_complete(sleep(3))


async def sleep(timeout: int):
    return await asyncio.sleep(timeout)


if __name__ == "__main__":
    main(auto_envvar_prefix="RCC")
