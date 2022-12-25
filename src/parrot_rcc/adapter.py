from parrot_rcc.errors import ElementInstanceNotFoundError
from pyzeebe.errors import InvalidJSONError
from pyzeebe.grpc_internals.grpc_utils import is_error_status
from pyzeebe.grpc_internals.zeebe_adapter_base import ZeebeAdapterBase
from typing import Dict
from zeebe_grpc.gateway_pb2 import SetVariablesRequest
from zeebe_grpc.gateway_pb2 import SetVariablesResponse
from zeebe_grpc.gateway_pb2 import TopologyRequest
from zeebe_grpc.gateway_pb2 import TopologyResponse
import grpc
import json
import logging


logger = logging.getLogger(__name__)


class ZeebeTopologyAdapter(ZeebeAdapterBase):
    async def topology(self) -> TopologyResponse:
        return await self._gateway_stub.Topology(TopologyRequest)


class ZeebeVariablesAdapter(ZeebeAdapterBase):
    async def set_variables(
        self, element_instance_key: int, variables: Dict, local: bool
    ) -> SetVariablesResponse:
        try:
            return await self._gateway_stub.SetVariables(
                SetVariablesRequest(
                    elementInstanceKey=element_instance_key,
                    variables=json.dumps(variables),
                    local=local,
                )
            )
        except grpc.aio.AioRpcError as grpc_error:
            if is_error_status(grpc_error, grpc.StatusCode.NOT_FOUND):
                raise ElementInstanceNotFoundError(
                    element_instance_key=element_instance_key
                ) from grpc_error
            elif is_error_status(grpc_error, grpc.StatusCode.INVALID_ARGUMENT):
                raise InvalidJSONError(json.dumps(variables)) from grpc_error
            await self._handle_grpc_error(grpc_error)
