import sentry_sdk
from sentry_sdk.integrations.atexit import AtexitIntegration
from sentry_sdk.integrations.dedupe import DedupeIntegration
from sentry_sdk.integrations.fastapi import FastApiIntegration
from sentry_sdk.integrations.starlette import StarletteIntegration

from app.core.config import settings


def setup_sentry():
    dsn = settings.SENTRY_DSN.get_secret_value()
    if dsn:
        sentry_sdk.init(
            dsn=dsn,
            default_integrations=False,
            integrations=[StarletteIntegration(), FastApiIntegration(), DedupeIntegration(), AtexitIntegration()],
            send_default_pii=False,
            include_local_variables=False,
            max_request_body_size="never",
        )
