from parrot_rcc.types import LogLevel
from parrot_rcc.types import Options
from parrot_rcc.utils import setup_logging
from pathlib import Path
from pyzeebe import create_camunda_cloud_channel
from pyzeebe import create_insecure_channel
from pyzeebe import Job
from pyzeebe import TaskConfig
from pyzeebe import ZeebeWorker
from pyzeebe.task import task_builder
from tempfile import TemporaryDirectory
from typing import Dict
from typing import List
from zipfile import ZipFile
import asyncio
import click
import dataclasses
import json
import logging
import multiprocessing
import os
import re
import uvloop
import yaml


os.environ["GRPC_ENABLE_FORK_SUPPORT"] = "0"

logger = logging.getLogger(__name__)


async def run(program: str, args: List[str], cwd: str, env: Dict[str, str]):
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
        logger.debug(f"{stderr.decode()}")
    if stdout:
        logger.debug(f"{stdout.decode()}")
    logger.debug(
        f"{program + ' ' + ' '.join(map(str, args))!r} exited with {proc.returncode}."
    )


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

    async def execute_task(**kwargs):
        async with semaphore:
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
                vault_json_path = Path(data_dir) / "vault.json"
                items_json_path = Path(data_dir) / "items.json"
                output_json_path = Path(data_dir) / "items.output.json"
                with open(vault_json_path, "w", encoding="utf-8") as fp:
                    fp.write(json.dumps({"env": dict(os.environ)}, indent=4))
                with open(items_json_path, "w", encoding="utf-8") as fp:
                    fp.write(
                        json.dumps(
                            [
                                {
                                    "payload": kwargs,
                                    "files": {},
                                }
                            ],
                            indent=4,
                        )
                    )
                await run(
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
                        "RPA_WORKITEMS_ADAPTER": "RPA.Robocloud.Items.FileAdapter",
                        "RPA_INPUT_WORKITEM_PATH": f"{items_json_path}",
                        "RPA_OUTPUT_WORKITEM_PATH": f"{output_json_path}",
                        "RC_WORKSPACE_ID": "1",
                        "RC_WORKITEM_ID": "1",
                    },
                )
                if (output_json_path).exists():
                    with open(output_json_path, "r", encoding="utf-8") as fp:
                        output_json = json.loads(fp.read())
                        for item in output_json:
                            return item.get("payload") or {}

    return execute_task, task_config


async def on_error(exception: Exception, job: Job):
    """
    on_error will be called when the task fails
    """
    logger.exception(exception)
    await job.set_error_status(f"Failed to handle job {job}. Error: {str(exception)}")


def before_job(job: Job) -> Job:
    logger.debug(f"Before job: {job}")
    return job


def after_job(job: Job) -> Job:
    logger.debug(f"After job: {job}")
    return job


@click.command()
@click.argument("robots", nargs=-1, envvar="RCC_ROBOTS")
@click.option("--rcc-executable", default="rcc", envvar="RCC_EXECUTABLE")
@click.option("--rcc-controller", default="parrot-rcc", envvar="RCC_CONTROLLER")
@click.option("--rcc-fixed-spaces", default=False, envvar="RCC_FIXED_SPACES")
@click.option("--rcc-telemetry", default=False, envvar="RCC_TELEMETRY")
@click.option("--task-timeout-ms", default=60 * 60 * 1000, envvar="TASK_TIMEOUT_MS")
@click.option(
    "--task-max-jobs", default=multiprocessing.cpu_count(), envvar="TASK_MAX_JOBS"
)
@click.option("--zeebe-hostname", default="localhost", envvar="ZEEBE_HOSTNAME")
@click.option("--zeebe-port", default=26500, envvar="ZEEBE_PORT")
@click.option("--camunda-client-id", default="", envvar="CAMUNDA_CLIENT_ID")
@click.option("--camunda-client-secret", default="", envvar="CAAMUNDA_CLIENT_SECRET")
@click.option("--camunda-cluster-id", default="", envvar="CAUNDA_CLIENT_SECRET")
@click.option("--camunda-region", default="", envvar="CAMUNDA_CLIENT_SECRET")
@click.option("--log-level", default="info", envvar="LOG_LEVEL")
def main(
    robots,
    rcc_executable,
    rcc_controller,
    rcc_fixed_spaces,
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
    semaphore = asyncio.Semaphore(config.task_max_jobs)

    for task, robot in tasks.items():
        worker._add_task(
            task_builder.build_task(*create_task(task, str(robot), semaphore, config))
        )

    if tasks:
        logger.info(f"Tasks: {tasks}")
    else:
        logger.warning(f"No tasks: {tasks}")

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
