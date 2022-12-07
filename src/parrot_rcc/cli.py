from os.path import basename
from parrot_rcc.adapter import ZeebeVariablesAdapter
from parrot_rcc.errors import ItemReleaseWithBusinessError
from parrot_rcc.errors import ItemReleaseWithFailure
from parrot_rcc.s3 import s3_download_file
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

import os
import json

class WorkItemAdapter(FileAdapter):
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
"""


class lazypprint:
    def __init__(self, data):
        self.data = data

    def __str__(self):
        return pprint.pformat(self.data, indent=4)


class lazydecode:
    def __init__(self, data: str):
        self.data = data

    def __str__(self):
        return self.data.decode()


async def run(
    program: str, args: List[str], cwd: str, env: Dict[str, str]
) -> Tuple[bytes, bytes]:
    proc = await asyncio.create_subprocess_exec(
        program,
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=cwd,
        env=os.environ | env | {"PYTHONPATH": ""},
    )

    stdout, stderr = await proc.communicate()
    assert proc.returncode == 0, f"{stderr.decode()}"

    if stderr:
        logger.debug("%s", lazydecode(stderr))
    if stdout:
        logger.debug("%s", lazydecode(stdout))
    logger.debug(
        f"{program + ' ' + ' '.join(map(str, args))!r} exited with {proc.returncode}."
    )
    return stdout or b"", stderr or b""


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
                await run(
                    config.rcc_executable,
                    ["robot", "unwrap", "-d", robot_dir, "-z", robot],
                    os.getcwd(),
                    {},
                )
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
                    await s3_download_file(
                        s3_client, config.rcc_s3_bucket_data, key, str(file_path)
                    )
                    items_files[basename(key)] = key.split(",", 1)[-1]
                with open(items_json_path, "w", encoding="utf-8") as fp:
                    fp.write(
                        json.dumps(
                            [
                                {
                                    "payload": kwargs,
                                    "files": items_files,
                                }
                            ],
                            indent=4,
                        )
                    )
                stdout, stderr = await run(
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
    logger.exception(exception)
    if isinstance(exception, ItemReleaseWithBusinessError):
        await job.zeebe_adapter.set_variables(
            job.element_instance_key, job.variables, True
        )
        await job.set_error_status(str(exception), exception.code)
    elif isinstance(exception, ItemReleaseWithFailure):
        await job.zeebe_adapter.set_variables(
            job.element_instance_key, job.variables, True
        )
        await job.set_failure_status(str(exception) or exception.code)
    else:
        await job.set_failure_status(
            f"Failed to handle job {job}. Error: {str(exception)}"
        )


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
    logger.debug("Before job: %s", lazypprint(job))
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
    logger.debug("After job: %s", lazypprint(job))
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
    "--rcc-fixed-spaces", is_flag=True, default=False, envvar="RCC_FIXED_SPACES"
)
@click.option("--rcc-s3-url", default="http://localhost:9000", envvar="RCC_S3_URL")
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
):
    """Zeebe external task Robot Framework RCC client

    [ROBOTS] could also be passed as a space separated env RCC_ROBOTS
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
        rcc_telemetry=rcc_telemetry,
        task_timeout_ms=task_timeout_ms,
        task_max_jobs=task_max_jobs,
        zeebe_hostname=zeebe_hostname,
        zeebe_port=zeebe_port,
        camunda_client_id=camunda_client_id,
        camunda_client_secret=camunda_client_secret,
        camunda_cluster_id=camunda_cluster_id,
        camunda_region=camunda_region,
        log_level=LogLevel(log_level),
    )

    setup_logging(logger, config.log_level)
    logger.info(dataclasses.replace(config, camunda_client_secret="*" * 8))

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

    if tasks:
        logger.info("Tasks: %s", lazypprint(tasks))
    else:
        logger.warning("No tasks: %s", lazypprint(tasks))

    loop = asyncio.get_event_loop()
    loop.run_until_complete(
        run(
            config.rcc_executable,
            ["configuration", "identity", "-e" if config.rcc_telemetry else "-t"],
            os.getcwd(),
            {},
        )
    )
    loop.run_until_complete(worker.work())


if __name__ == "__main__":
    main(auto_envvar_prefix="RCC")
