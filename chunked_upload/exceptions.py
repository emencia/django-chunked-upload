"""
Exceptions raised by django-chunked-upload.
"""

from rest_framework.exceptions import APIException


class BadRequest(APIException):
    status_code = 400


class Gone(APIException):
    status_code = 410
