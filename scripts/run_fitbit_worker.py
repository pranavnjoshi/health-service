import logging
import os

from dotenv import load_dotenv

from app.workers.fitbit_worker import run_worker


def configure_logger() -> logging.Logger:
    logger = logging.getLogger("fitbit_worker")
    configured_level = os.getenv("WORKER_LOG_LEVEL", "INFO").upper()
    level = getattr(logging, configured_level, logging.INFO)
    logger.setLevel(level)
    logger.handlers = []

    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    console = logging.StreamHandler()
    console.setFormatter(formatter)
    logger.addHandler(console)

    return logger


if __name__ == "__main__":
    load_dotenv(".env.local")
    worker_logger = configure_logger()
    run_worker(worker_logger)
