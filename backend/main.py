# NOTE: Not the HTTP server entrypoint. Run `uv run python app.py` or gunicorn `app:app`.
from core.observability import get_logger

log = get_logger(__name__)


def main():
    log.info("backend_placeholder", message="Use app.py / gunicorn for the API server")


if __name__ == "__main__":
    main()
