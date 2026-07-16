"""Production target entrypoint staged for the authorized offline replacement."""

from core.logging_config import configure_logging

configure_logging()

from target_application import create_production_target_application

app = create_production_target_application()
