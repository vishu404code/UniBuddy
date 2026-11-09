"""The error every data layer raises. Services catch this one type, whichever backend is used."""


class DataServiceError(Exception):
    def __init__(self, status_code: int, detail: str):
        super().__init__(f"Data request failed with HTTP {status_code}")
        self.status_code = status_code
        self.detail = detail
