from __future__ import annotations
from functools import lru_cache
from pathlib import Path
from pydantic import BaseModel
import yaml


class ModelConfig(BaseModel):
    provider: str = "openai"
    name: str = "gpt-4o-mini"


class DatabaseConfig(BaseModel):
    backend: str = "sqlite"
    path: str = "./data/evals.db"
    url: str | None = None

    def get_url(self) -> str:
        if self.backend == "postgres" and self.url:
            return self.url
        path = Path(self.path)
        path.parent.mkdir(parents=True, exist_ok=True)
        return f"sqlite:///{path}"


class SecurityConfig(BaseModel):
    enable_auth: bool = True
    jwt_secret: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 480
    rate_limit_per_minute: int = 20


class EvaluationWeights(BaseModel):
    objective: float = 0.4
    code: float = 0.3
    ui: float = 0.3


class CodeSubWeights(BaseModel):
    cleanliness: float = 0.15
    modularity: float = 0.25
    security: float = 0.30
    robustness: float = 0.20
    best_practices: float = 0.10


class EvaluationConfig(BaseModel):
    weights: EvaluationWeights = EvaluationWeights()
    code_sub_weights: CodeSubWeights = CodeSubWeights()
    agent_timeout_seconds: int = 30


class RepoConfig(BaseModel):
    max_files: int = 50
    recent_commits: int = 10


class JudgeConfig(BaseModel):
    username: str
    password_hash: str


class AppConfig(BaseModel):
    model: ModelConfig = ModelConfig()
    database: DatabaseConfig = DatabaseConfig()
    security: SecurityConfig = SecurityConfig()
    evaluation: EvaluationConfig = EvaluationConfig()
    repo: RepoConfig = RepoConfig()
    judges: list[JudgeConfig] = []


@lru_cache(maxsize=1)
def load_config(path: str = "config.yaml") -> AppConfig:
    config_path = Path(path)
    if not config_path.exists():
        return AppConfig()
    with open(config_path) as f:
        data = yaml.safe_load(f) or {}
    return AppConfig(**data)


config = load_config()
