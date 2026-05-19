import sys
from django.core.mail.backends.base import BaseEmailBackend


class ReadableConsoleEmailBackend(BaseEmailBackend):
    """
    Development-only email backend.
    Prints the raw email body directly to stdout without any MIME/QP encoding,
    so URLs are never corrupted or line-wrapped.
    """

    def send_messages(self, email_messages):
        num_sent = 0
        for message in email_messages:
            try:
                self._print(message)
                num_sent += 1
            except Exception:
                if not self.fail_silently:
                    raise
        return num_sent

    @staticmethod
    def _print(message):
        sep = "-" * 72
        recipients = ", ".join(str(a) for a in message.to)
        output = (
            f"\n{sep}\n"
            f"[EMAIL] To: {recipients}\n"
            f"[EMAIL] Subject: {message.subject}\n"
            f"{sep}\n"
            f"{message.body}\n"
            f"{sep}\n"
        )
        sys.stdout.write(output)
        sys.stdout.flush()
