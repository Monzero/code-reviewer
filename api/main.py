from fastapi import FastAPI
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from core.observability.logger import setup_logging
from api.routes import auth, evaluate, metrics, reports

setup_logging()

limiter = Limiter(key_func=get_remote_address)
app = FastAPI(title="AI Project Evaluator", version="1.0.0")
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.include_router(auth.router)
app.include_router(evaluate.router)
app.include_router(reports.router)
app.include_router(metrics.router)
