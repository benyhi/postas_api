from django.template.loader import render_to_string


def render_notification(template_name, context):
    text_body = render_to_string(f"notifications/{template_name}.txt", context).strip()
    html_body = render_to_string(f"notifications/{template_name}.html", context).strip()
    return text_body, html_body
