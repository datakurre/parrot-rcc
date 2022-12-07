from concurrent.futures import ThreadPoolExecutor
from typing import Any
from typing import List
import asyncio
import magic


default_executor = ThreadPoolExecutor()


def s3_download_file_sync(
    s3_client: Any, s3_bucket_name: str, s3_key: str, local_path: str
) -> None:
    return s3_client.download_file(
        s3_bucket_name,
        s3_key,
        local_path,
    )


async def s3_download_file(
    s3_client: Any,
    s3_bucket_name: str,
    s3_key: str,
    local_path: str,
    loop=None,
    executor=None,
) -> None:
    return await (
        loop if loop is not None else asyncio.get_event_loop()
    ).run_in_executor(
        executor if executor is not None else default_executor,
        s3_download_file_sync,
        s3_client,
        s3_bucket_name,
        s3_key,
        local_path,
    )


def s3_generate_presigned_url_sync(
    s3_client: Any, s3_bucket_name: str, s3_key: str
) -> None:
    return s3_client.generate_presigned_url(
        ClientMethod="get_object",
        Params={
            "Bucket": s3_bucket_name,
            "Key": s3_key,
        },
        ExpiresIn=3600 * 24 * 7,  # one week in seconds
    )


async def s3_generate_presigned_url(
    s3_client: Any,
    s3_bucket_name: str,
    s3_key: str,
    loop=None,
    executor=None,
) -> None:
    return await (
        loop if loop is not None else asyncio.get_event_loop()
    ).run_in_executor(
        executor if executor is not None else default_executor,
        s3_generate_presigned_url_sync,
        s3_client,
        s3_bucket_name,
        s3_key,
    )


def s3_upload_file_sync(
    s3_client: Any, local_path: str, s3_bucket_name: str, s3_key: str
) -> None:
    return s3_client.upload_file(
        local_path,
        s3_bucket_name,
        s3_key,
        ExtraArgs={
            "ContentType": magic.detect_from_filename(
                local_path,
            ).mime_type
        },
    )


async def s3_upload_file(
    s3_client: Any,
    local_path: str,
    s3_bucket_name: str,
    s3_key: str,
    loop=None,
    executor=None,
) -> None:
    await (loop if loop is not None else asyncio.get_event_loop()).run_in_executor(
        executor if executor is not None else default_executor,
        s3_upload_file_sync,
        s3_client,
        local_path,
        s3_bucket_name,
        s3_key,
    )


def s3_put_object_sync(
    s3_client: Any, s3_bucket_name: str, s3_key: str, body: bytes, content_type: str
) -> None:
    # Upload a file to the bucket
    return s3_client.put_object(
        Bucket=s3_bucket_name,
        Key=s3_key,
        Body=body,
        ContentType=content_type,
    )


async def s3_put_object(
    s3_client: Any,
    s3_bucket_name: str,
    s3_key: str,
    body: bytes,
    content_type: str,
    loop=None,
    executor=None,
) -> None:
    await (loop if loop is not None else asyncio.get_event_loop()).run_in_executor(
        executor if executor is not None else default_executor,
        s3_put_object_sync,
        s3_client,
        s3_bucket_name,
        s3_key,
        body,
        content_type,
    )


def s3_list_files_sync(
    s3_resource: Any, s3_bucket_name: str, prefix: str = ""
) -> List[str]:
    return [
        o.key for o in s3_resource.Bucket(s3_bucket_name).objects.filter(Prefix=prefix)
    ]


async def s3_list_files(
    s3_resource: Any, s3_bucket_name: str, prefix: str, loop=None, executor=None
) -> List[str]:
    return await (
        loop if loop is not None else asyncio.get_event_loop()
    ).run_in_executor(
        executor if executor is not None else default_executor,
        s3_list_files_sync,
        s3_resource,
        s3_bucket_name,
        prefix,
    )