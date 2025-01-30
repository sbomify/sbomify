from ninja import Schema


class ErrorResponse(Schema):
    detail: str