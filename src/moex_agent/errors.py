from typing import Optional


class ToolProblem(Exception):
    def __init__(self, kind: str, message: str, hint: str, retryable: bool = False):
        super().__init__(message)
        self.kind = kind
        self.message = message
        self.hint = hint
        self.retryable = retryable

    def as_dict(self) -> dict:
        return {
            "error": {
                "type": self.kind,
                "message": self.message,
                "hint": self.hint,
                "retryable": self.retryable,
            }
        }


class ServiceTimeout(ToolProblem):
    def __init__(self, message: str = "Сервис не ответил вовремя", hint: Optional[str] = None):
        super().__init__(
            "timeout",
            message,
            hint or "Повтори чтение не более двух раз или используй сохранённый снапшот",
            True,
        )
