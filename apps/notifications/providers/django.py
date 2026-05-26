from django.core.mail import EmailMessage, EmailMultiAlternatives

from apps.notifications.providers.base import BaseEmailProvider, EmailRequest, ProviderSendResult


class DjangoEmailProvider(BaseEmailProvider):
    name = "django"

    def send(self, email_request: EmailRequest) -> ProviderSendResult:
        if email_request.html_body:
            message = EmailMultiAlternatives(
                subject=email_request.subject,
                body=email_request.text_body,
                from_email=email_request.from_email,
                to=email_request.to,
                bcc=email_request.bcc,
                cc=email_request.cc,
                reply_to=email_request.reply_to,
            )
            message.attach_alternative(email_request.html_body, "text/html")
        else:
            message = EmailMessage(
                subject=email_request.subject,
                body=email_request.text_body,
                from_email=email_request.from_email,
                to=email_request.to,
                bcc=email_request.bcc,
                cc=email_request.cc,
                reply_to=email_request.reply_to,
            )

        sent = message.send(fail_silently=False)
        return ProviderSendResult(sent=sent, response={"backend": "django"})
