import json
import uuid
from email.utils import parseaddr

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import DatabaseError

from apps.notifications.models import EmailDelivery
from apps.notifications.rendering import render_notification
from apps.notifications.services import send_email
from apps.tenants.models import TenantConfig


class Command(BaseCommand):
    help = "Print sanitized email settings and optionally send a tracked test email."

    def add_arguments(self, parser):
        parser.add_argument(
            "--tenant-id",
            type=str,
            help="Tenant UUID to inspect. If omitted and there is one TenantConfig, it is used.",
        )
        parser.add_argument(
            "--to",
            type=str,
            help="Recipient for the test email. Defaults to TenantConfig.notification_email.",
        )
        parser.add_argument(
            "--send",
            action="store_true",
            help="Send a test email with the configured EMAIL_PROVIDER.",
        )
        parser.add_argument(
            "--skip-db",
            action="store_true",
            help="Only print email settings; do not inspect TenantConfig or delivery rows.",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=5,
            help="Number of recent tracked email deliveries to print for the tenant.",
        )

    def handle(self, *args, **options):
        if options["skip_db"] and options["send"]:
            raise CommandError("--send requiere DB para registrar EmailDelivery; quitá --skip-db.")

        self._print_settings()
        self._print_warnings()

        config = None
        if not options["skip_db"]:
            tenant_id = self._parse_tenant_id(options.get("tenant_id"))
            config = self._get_tenant_config(tenant_id)
            self._print_tenant_config(config)

        if config:
            self._print_recent_deliveries(config.tenant_id, options["limit"])

        if options["send"]:
            recipient = options["to"] or (config.notification_email if config else "")
            if not recipient:
                raise CommandError("Use --to or configure TenantConfig.notification_email before --send.")
            self._send_test_email(recipient, config.tenant_id if config else None)
        elif options["to"]:
            self.stdout.write(self.style.WARNING("--to was provided without --send; no email was sent."))

    def _parse_tenant_id(self, raw_tenant_id):
        if not raw_tenant_id:
            return None
        try:
            return uuid.UUID(raw_tenant_id)
        except ValueError as exc:
            raise CommandError(f"Invalid --tenant-id: {raw_tenant_id}") from exc

    def _get_tenant_config(self, tenant_id):
        if tenant_id:
            try:
                config = TenantConfig.objects.filter(tenant_id=tenant_id).first()
            except DatabaseError as exc:
                self.stdout.write(self.style.WARNING(f"TenantConfig lookup failed: {exc}"))
                return None
            if not config:
                self.stdout.write(self.style.WARNING(f"No TenantConfig found for tenant {tenant_id}."))
            return config

        try:
            configs = list(TenantConfig.objects.select_related("tenant")[:2])
        except DatabaseError as exc:
            self.stdout.write(self.style.WARNING(f"TenantConfig lookup failed: {exc}"))
            return None
        if len(configs) == 1:
            return configs[0]
        if len(configs) > 1:
            self.stdout.write(self.style.WARNING("Multiple TenantConfig rows found; pass --tenant-id to inspect one."))
        else:
            self.stdout.write(self.style.WARNING("No TenantConfig rows found."))
        return None

    def _print_settings(self):
        self.stdout.write("\nEmail settings")
        self.stdout.write(f"  EMAIL_PROVIDER={settings.EMAIL_PROVIDER}")
        self.stdout.write(f"  EMAIL_FALLBACK_PROVIDER={settings.EMAIL_FALLBACK_PROVIDER or '(empty)'}")
        self.stdout.write(f"  EMAIL_PROVIDER_FALLBACK_ENABLED={settings.EMAIL_PROVIDER_FALLBACK_ENABLED}")
        self.stdout.write(f"  EMAIL_BACKEND={settings.EMAIL_BACKEND}")
        self.stdout.write(f"  EMAIL_HOST={settings.EMAIL_HOST}")
        self.stdout.write(f"  EMAIL_PORT={settings.EMAIL_PORT}")
        self.stdout.write(f"  EMAIL_USE_TLS={settings.EMAIL_USE_TLS}")
        self.stdout.write(f"  EMAIL_USE_SSL={settings.EMAIL_USE_SSL}")
        self.stdout.write(f"  EMAIL_HOST_USER={self._mask_email(settings.EMAIL_HOST_USER)}")
        self.stdout.write(f"  EMAIL_HOST_PASSWORD={self._secret_status(settings.EMAIL_HOST_PASSWORD)}")
        self.stdout.write(f"  DEFAULT_FROM_EMAIL={settings.DEFAULT_FROM_EMAIL}")
        self.stdout.write(f"  EMAIL_TIMEOUT={settings.EMAIL_TIMEOUT}")
        self.stdout.write(f"  RESEND_API_KEY={self._secret_status(settings.RESEND_API_KEY)}")
        self.stdout.write(f"  RESEND_API_URL={settings.RESEND_API_URL}")
        self.stdout.write(f"  RESEND_COST_PER_1000_EMAILS={settings.RESEND_COST_PER_1000_EMAILS}")
        self.stdout.write(f"  DJANGO_EMAIL_COST_PER_1000_EMAILS={settings.DJANGO_EMAIL_COST_PER_1000_EMAILS}")

    def _print_tenant_config(self, config):
        self.stdout.write("\nTenantConfig")
        if not config:
            self.stdout.write("  (not selected)")
            return
        self.stdout.write(f"  tenant_id={config.tenant_id}")
        self.stdout.write(f"  notification_email={config.notification_email or '(empty)'}")
        self.stdout.write(f"  cashbox_email_notifications_enabled={config.cashbox_email_notifications_enabled}")

    def _print_recent_deliveries(self, tenant_id, limit):
        if limit <= 0:
            return
        deliveries = EmailDelivery.objects.filter(tenant_id=tenant_id).order_by("-created_at")[:limit]

        self.stdout.write("\nRecent email deliveries")
        if not deliveries:
            self.stdout.write("  (no rows)")
            return

        for delivery in deliveries:
            metadata = json.dumps(delivery.metadata, ensure_ascii=True)
            self.stdout.write(
                "  "
                f"{delivery.created_at:%Y-%m-%d %H:%M:%S} "
                f"{delivery.notification_type} {delivery.provider} {delivery.status} "
                f"recipients={delivery.recipient_count} cost={delivery.estimated_cost_usd} "
                f"metadata={metadata}"
            )

    def _print_warnings(self):
        self.stdout.write("\nChecks")
        if settings.EMAIL_PROVIDER == "resend" and not settings.RESEND_API_KEY:
            self.stdout.write(self.style.WARNING("  RESEND_API_KEY is empty."))
        if settings.EMAIL_PROVIDER == "django" and settings.EMAIL_BACKEND == "django.core.mail.backends.console.EmailBackend":
            self.stdout.write(self.style.WARNING("  Django fallback backend is console.EmailBackend; it prints emails instead of sending SMTP."))
        if settings.EMAIL_USE_TLS and settings.EMAIL_USE_SSL:
            self.stdout.write(self.style.WARNING("  EMAIL_USE_TLS and EMAIL_USE_SSL are both true; use one mode only."))

        from_address = parseaddr(settings.DEFAULT_FROM_EMAIL)[1]
        host_user = settings.EMAIL_HOST_USER
        if settings.EMAIL_PROVIDER == "django" and "gmail" in settings.EMAIL_HOST.lower() and from_address and host_user:
            if from_address.lower() != host_user.lower():
                self.stdout.write(self.style.WARNING("  Gmail may reject DEFAULT_FROM_EMAIL unless it is the same account or a verified alias."))

    def _send_test_email(self, recipient, tenant_id):
        self.stdout.write(f"\nSending test email to {recipient}...")
        text_body, html_body = render_notification(
            "debug_email",
            {
                "brand_name": "POSTAS",
                "title": "Prueba de email",
                "preheader": "Mensaje de prueba para validar la configuracion de email de POSTAS.",
            },
        )
        try:
            result = send_email(
                tenant_id=tenant_id,
                notification_type=EmailDelivery.NotificationType.DEBUG,
                subject="POSTAS email debug",
                text_body=text_body,
                html_body=html_body,
                to=[recipient],
                metadata={"source": "debug_email"},
            )
        except Exception as exc:
            raise CommandError(f"Email send failed: {type(exc).__name__}: {exc}") from exc
        self.stdout.write(self.style.SUCCESS(f"Email sent with provider={result['provider']} delivery={result['delivery_uuid']}."))

    def _secret_status(self, value):
        if not value:
            return "(empty)"

        notes = []
        if value != value.strip():
            notes.append("leading/trailing whitespace")
        if value.startswith(("'", '"')) or value.endswith(("'", '"')):
            notes.append("quote wrapper")
        suffix = f"; {', '.join(notes)}" if notes else ""
        return f"set len={len(value)}{suffix}"

    def _mask_email(self, value):
        if not value:
            return "(empty)"
        local, separator, domain = value.partition("@")
        if not separator:
            return f"set len={len(value)}"
        prefix = local[:2] if len(local) > 1 else local[:1]
        return f"{prefix}***@{domain}"
