from dataclasses import dataclass
from pathlib import Path
from pyzeebe import create_insecure_channel
from pyzeebe import Job
from pyzeebe import TaskConfig
from pyzeebe import ZeebeWorker
from pyzeebe.task import task_builder
from tempfile import TemporaryDirectory
from typing import List
from zipfile import ZipFile
import asyncio
import click
import os
import uvloop
import yaml


os.environ["GRPC_ENABLE_FORK_SUPPORT"] = "0"


async def run(program: str, args: List[str], cwd: str):
    proc = await asyncio.create_subprocess_exec(
        program,
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=cwd,
        env=os.environ | {"PYTHONPATH": ""},
    )

    stdout, stderr = await proc.communicate()

    if stderr:
        print(f"[stderr]\n{stderr.decode()}")
    if stdout:
        print(f"[stdout]\n{stdout.decode()}")
    print(
        f"[{program + ' ' + ' '.join(map(str, args))!r} exited with {proc.returncode}]"
    )


@dataclass
class Options:
    rcc_executable: str = "rcc"


def create_task(task: str, robot: str, options: Options):
    async def execute_task(**kwargs):
        with TemporaryDirectory() as cwd:
            await run(
                options.rcc_executable, ["robot", "unwrap", "-d", cwd, "-z", robot], cwd
            )
            await run(
                options.rcc_executable,
                [
                    "run",
                    "--task",
                    task,
                ],
                cwd,
            )

    return execute_task


async def on_error(exception: Exception, job: Job):
    """
    on_error will be called when the task fails
    """
    print(exception)
    await job.set_error_status(f"Failed to handle job {job}. Error: {str(exception)}")


@click.command()
@click.argument("robots", nargs=-1, envvar="RCC_ROBOTS")
@click.option("--rcc-executable", default="rcc")
def main(robots, rcc_executable):
    """Zeebe external task Robot Framework RCC client

    [ROBOTS] could also be passed as a space separated env RCC_ROBOTS
    """
    options = Options(rcc_executable=rcc_executable)
    print(robots, options)
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
    channel = create_insecure_channel(hostname="localhost", port=26500)
    worker = ZeebeWorker(channel)

    for task, robot in tasks.items():
        config = TaskConfig(
            type=task,
            exception_handler=on_error,
            timeout_ms=10000,
            max_jobs_to_activate=32,
            max_running_jobs=32,
            variables_to_fetch=[],
            single_value=False,
            variable_name="",
            before=[],
            after=[],
        )
        worker._add_task(
            task_builder.build_task(create_task(task, str(robot), options), config)
        )

    loop = asyncio.get_event_loop()
    loop.run_until_complete(worker.work())


if __name__ == "__main__":
    main(auto_envvar_prefix="RCC")
