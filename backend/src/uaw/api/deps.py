from fastapi import Request

from uaw.services import Services


def get_services(request: Request) -> Services:
    """Services built at startup (see ``main.lifespan``). Tests override this."""
    services: Services = request.app.state.services
    return services
