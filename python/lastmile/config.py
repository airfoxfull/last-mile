"""配置管理 — ~/.lastmile.toml"""

import os
import toml
from pathlib import Path
from dataclasses import dataclass, field

CONFIG_PATH = Path.home() / ".lastmile.toml"


@dataclass
class Config:
    clawith_url: str = "http://localhost:8008"
    email: str = ""
    password: str = ""
    planner_id: str = ""
    executor_id: str = ""
    fool_id: str = ""
    token: str = ""


def load() -> Config:
    if not CONFIG_PATH.exists():
        return Config()
    data = toml.load(CONFIG_PATH)
    return Config(**{k: v for k, v in data.items() if k in Config.__dataclass_fields__})


def save(cfg: Config):
    data = {k: v for k, v in cfg.__dict__.items() if v}
    CONFIG_PATH.write_text(toml.dumps(data))


def ensure_config() -> Config:
    """加载配置，如果不存在则提示用户运行 lastmile init"""
    cfg = load()
    if not cfg.email or not cfg.planner_id:
        from rich.console import Console
        Console().print("[red]未初始化。请先运行: lastmile init[/red]")
        raise SystemExit(1)
    return cfg
