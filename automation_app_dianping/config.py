from dataclasses import dataclass


@dataclass(frozen=True)
class DianpingAppConfig:
    city: str
    app_id: str
