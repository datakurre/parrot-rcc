from aiohttp import web
from parrot_rcc.adapter import ZeebeTopologyAdapter
from parrot_rcc.types import Options
from pyzeebe import create_camunda_cloud_channel
from pyzeebe import create_insecure_channel
from pyzeebe import ZeebeClient
import aiohttp
import asyncio


class Healthz:
    def __init__(self, client: ZeebeClient):
        self.client = client

    async def healthz(self, request: web.Request) -> web.Response:
        try:
            await self.client.zeebe_adapter.topology()
            return web.json_response({"status": "ok"})
        except Exception as e:
            return web.json_response({"status": "error", "error": str(e)}, status=500)


def app(config: Options) -> web.Application:
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
    client = ZeebeClient(channel)
    client.zeebe_adapter.__class__.__bases__ = (
        client.zeebe_adapter.__class__.__bases__ + (ZeebeTopologyAdapter,)
    )
    healthz_app = web.Application()
    healthz_app.add_routes([web.get("/healthz", Healthz(client).healthz)])
    return healthz_app
