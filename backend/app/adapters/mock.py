from app.errors import Problem


class MockAdapter:
    kind = "mock"
    controls = ("start", "stop", "restart")
    console_available = True

    def __init__(self) -> None:
        self.running = False
        self.logs: list[str] = ["[mock] 模拟服务器已就绪"]

    async def status(self) -> str:
        return "running" if self.running else "stopped"

    async def start(self) -> None:
        if self.running:
            raise Problem(409, "SERVER_ALREADY_RUNNING")
        self.running = True
        self.logs = [*self.logs[-199:], "[mock] 模拟服务器已启动"]

    async def stop(self) -> None:
        if not self.running:
            raise Problem(409, "SERVER_NOT_RUNNING")
        self.running = False
        self.logs = [*self.logs[-199:], "[mock] 模拟服务器已停止"]

    async def console(self, command: str) -> None:
        if not self.running:
            raise Problem(409, "SERVER_NOT_RUNNING")
        self.logs = [*self.logs[-199:], f"[mock] {command}"]


class UnconfiguredAdapter:
    kind = "unconfigured"
    controls: tuple[str, ...] = ()

    async def status(self) -> str:
        return "unknown"

    async def start(self) -> None:
        raise Problem(503, "PROFILE_UNCONFIGURED")

    async def stop(self) -> None:
        raise Problem(503, "PROFILE_UNCONFIGURED")
