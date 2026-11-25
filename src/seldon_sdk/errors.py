"""Bounded errors that never include credentials or supplied payloads."""


class SeldonError(Exception):
    def __init__(
        self,
        code: str,
        *,
        status: int | None = None,
        correlation_id: str | None = None,
        param: str | None = None,
        execution_id: str | None = None,
    ) -> None:
        super().__init__(code)
        self.code = code
        self.status = status
        self.correlation_id = correlation_id
        self.param = param
        self.execution_id = execution_id


class SeldonConfigError(SeldonError):
    pass


class SeldonContractError(SeldonError):
    pass


class SeldonInputError(SeldonContractError):
    pass


class SeldonAuthError(SeldonError):
    pass


class SeldonSpendError(SeldonError):
    pass


class SeldonOutputValidationError(SeldonError):
    pass


class SeldonReferenceError(SeldonError):
    pass
