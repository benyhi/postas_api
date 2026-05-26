from django.conf import settings

from apps.notifications.providers.base import BaseEmailProvider, EmailRequest, ProviderSendResult


class ResendEmailProvider(BaseEmailProvider):
    name = "resend"

    def send(self, email_request: EmailRequest) -> ProviderSendResult:
        try:
            import resend
        except ImportError as exc:
            raise RuntimeError("La dependencia 'resend' no esta instalada.") from exc

        if not settings.RESEND_API_KEY:
            raise ValueError("RESEND_API_KEY no esta configurado.")

        resend.api_key = settings.RESEND_API_KEY
        if getattr(settings, "RESEND_API_URL", "") and hasattr(resend, "api_url"):
            resend.api_url = settings.RESEND_API_URL

        params = {
            "from": email_request.from_email,
            "to": email_request.to,
            "subject": email_request.subject,
            "text": email_request.text_body,
        }
        if email_request.html_body:
            params["html"] = email_request.html_body
        if email_request.cc:
            params["cc"] = email_request.cc
        if email_request.bcc:
            params["bcc"] = email_request.bcc
        if email_request.reply_to:
            params["reply_to"] = email_request.reply_to
        response = resend.Emails.send(params)
        normalized_response = self._normalize_response(response)

        return ProviderSendResult(
            sent=1,
            external_id=str(normalized_response.get("id", "")),
            response=normalized_response,
        )

    def _normalize_response(self, response):
        if isinstance(response, dict):
            return response
        if hasattr(response, "dict"):
            return response.dict()
        if hasattr(response, "model_dump"):
            return response.model_dump()
        if hasattr(response, "__dict__"):
            return {
                key: value
                for key, value in response.__dict__.items()
                if not key.startswith("_")
            }
        return {"raw": str(response)}
