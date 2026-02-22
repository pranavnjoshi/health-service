import logging

from app.workers.fitbit_worker import run_worker


def configure_logger() -> logging.Logger:
    logger = logging.getLogger("fitbit_worker")
    logger.setLevel(logging.INFO)
    logger.handlers = []

    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    console = logging.StreamHandler()
    console.setFormatter(formatter)
    logger.addHandler(console)

    return logger


if __name__ == "__main__":
    worker_logger = configure_logger()
    run_worker(worker_logger)
