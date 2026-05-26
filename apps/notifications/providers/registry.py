from apps.notifications.providers.django import DjangoEmailProvider
from apps.notifications.providers.resend_provider import ResendEmailProvider


PROVIDERS = {
    "django": DjangoEmailProvider,
    "resend": ResendEmailProvider,
}


def get_email_provider(name):
    try:
        provider_class = PROVIDERS[name]
    except KeyError as exc:
        raise ValueError(f"EMAIL_PROVIDER invalido: {name}") from exc
    return provider_class()
