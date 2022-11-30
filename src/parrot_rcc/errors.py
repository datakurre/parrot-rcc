from typing import Dict

from pyzeebe.errors import PyZeebeError


class ElementInstanceNotFoundError(PyZeebeError):
    def __init__(self, element_instance_key: int):
        super().__init__(f"No element with the given {element_instance_key} exists")
        self.job_key = element_instance_key


class ReleaseException(Exception):
    def __init__(self, message: str, code: str, payload: Dict):
        super().__init__(message)
        self.code = code
        self.payload = payload


class ItemReleaseWithBusinessError(ReleaseException):
    pass


class ItemReleaseWithFailure(ReleaseException):
    pass
