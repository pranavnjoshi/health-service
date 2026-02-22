from app.services.apple_health_pull import AppleHealthPullService
from app.services.apple_health_push import AppleHealthPushService
from app.services.fitbit_pull import FitbitPullService
from app.services.fitbit_push import FitbitPushService
from app.services.google_fit_pull import GoogleFitPullService
from app.services.google_fit_push import GoogleFitPushService


class ProviderServiceRegistry:
    def __init__(self, push_services: dict, pull_services: dict):
        self._push_services = push_services
        self._pull_services = pull_services

    def get_push(self, provider: str):
        key = provider.lower()
        if key not in self._push_services:
            raise KeyError(f"No push service registered for provider '{provider}'")
        return self._push_services[key]

    def get_pull(self, provider: str):
        key = provider.lower()
        if key not in self._pull_services:
            raise KeyError(f"No pull service registered for provider '{provider}'")
        return self._pull_services[key]


def create_provider_service_registry(*, logger, queue_client=None, event_bus=None):
    bus = queue_client or event_bus
    if bus is None:
        raise ValueError("queue_client (or event_bus) is required")
    push_services = {
        "fitbit": FitbitPushService(event_bus=bus, logger=logger),
        "google": GoogleFitPushService(logger=logger),
        "apple": AppleHealthPushService(logger=logger),
    }

    pull_services = {
        "fitbit": FitbitPullService(logger=logger),
        "google": GoogleFitPullService(logger=logger),
        "apple": AppleHealthPullService(logger=logger),
    }

    return ProviderServiceRegistry(push_services=push_services, pull_services=pull_services)
