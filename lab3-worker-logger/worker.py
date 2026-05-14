import os
import time
import smtplib
import logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from dotenv import load_dotenv
import requests
import structlog
from opentelemetry.sdk.resources import *

load_dotenv()


SERVICE_NAME_VALUE = os.getenv("OTEL_SERVIE_NAME", "email-worker")
OTLP_ENDPOINT = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4318")
PROMETHEUS_PORT = os.getenv("PROMETHEUSE_PORT", 8000)



resource = Resource.create(attributes = {SERVICE_NAME : SERVICE_NAME_VALUE, SERVICE_VERSION : "1.0.0"})

# TODO: step 3.2 


processors = [
        structlog.processors.TimeStamper(fmt="iso"), # Aggiunge il timestamp in formato ISO
        structlog.processors.add_log_level,      # Aggiunge "level": "info", "error", ecc.
        structlog.contextvars.merge_contextvars, # Permette di aggiungere variabili di contesto (come trace_id) in futuro
        structlog.processors.JSONRenderer()      # Trasforma tutto in un dizionario JSON
    ]

structlog.configure(processors=processors)

log = structlog.get_logger(service="email-worker")



POLL_INTERVAL = int(os.getenv("POLL_INTERVAL_SECONDS", 5))
SMTP_HOST = os.getenv("SMTP_HOST", "localhost")
SMTP_PORT = int(os.getenv("SMTP_PORT", 1025))
EMAIL_FROM = os.getenv("EMAIL_FROM", "worker@mzinga.io")

MZINGA_URL = os.getenv("MZINGA_URL")
MZINGA_PASSWORD = os.getenv("MZINGA_PASSWORD")
MZINGA_EMAIL = os.getenv("MZINGA_EMAIL")


PENDING_STATUS = "pending"
PROCESSING_STATUS = "processing"
SENT_STATUS = "sent"
FAILED_STATUS = "failed"


def slate_to_html(nodes: list) -> str:
    """Minimal Slate AST → HTML serialiser."""
    html = ""
    for node in nodes or []:
        if node.get("type") == "paragraph":
            html += f"<p>{slate_to_html(node.get('children', []))}</p>"
        elif node.get("type") == "h1":
            html += f"<h1>{slate_to_html(node.get('children', []))}</h1>"
        elif node.get("type") == "h2":
            html += f"<h2>{slate_to_html(node.get('children', []))}</h2>"
        elif node.get("type") == "ul":
            html += f"<ul>{slate_to_html(node.get('children', []))}</ul>"
        elif node.get("type") == "li":
            html += f"<li>{slate_to_html(node.get('children', []))}</li>"
        elif node.get("type") == "link":
            url = node.get("url", "#")
            html += f'<a href="{url}">{slate_to_html(node.get("children", []))}</a>'
        elif "text" in node:
            text = node["text"]
            if node.get("bold"):
                text = f"<strong>{text}</strong>"
            if node.get("italic"):
                text = f"<em>{text}</em>"
            html += text
        else:
            html += slate_to_html(node.get("children", []))
    return html


def resolve_emails(relationship_list: list) -> list[str]:
    emails = []
    for r in relationship_list or []:
        value = r.get("value") or {}
        if isinstance(value, dict) and value.get("email"):
            emails.append(value["email"])
    return emails


def send_email(to_addresses: list[str], subject: str, html: str,
               cc_addresses: list[str] = None, bcc_addresses: list[str] = None):
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = EMAIL_FROM
    msg["To"] = ", ".join(to_addresses)
    if cc_addresses:
        msg["Cc"] = ", ".join(cc_addresses)
    msg.attach(MIMEText(html, "html"))
    all_recipients = to_addresses + (cc_addresses or []) + (bcc_addresses or [])
    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
        server.sendmail(EMAIL_FROM, all_recipients, msg.as_string())


def process(doc: dict, token: str) -> None:
    doc_id = doc.get("id")

    log = structlog.get_logger(doc_id=doc_id)
    
    

    log.info(f"Processing communication {doc_id}")

    update_status_by_communication_id(token, doc_id, PROCESSING_STATUS)
    try:
        to_emails = resolve_emails(doc.get("tos") or [])
        if not to_emails:
            raise ValueError("No valid 'to' email addresses found")
        cc_emails = resolve_emails(doc.get("ccs") or [])
        bcc_emails = resolve_emails(doc.get("bccs") or [])
        html = slate_to_html(doc.get("body") or [])

        send_email(to_emails, doc["subject"], html, cc_emails, bcc_emails)
        
        update_status_by_communication_id(token, doc_id, SENT_STATUS)

        log.info(f"Communication {doc_id} sent successfully")

    except Exception as e:
        log.error(f"Failed to process communication {doc_id}: {e}")
        update_status_by_communication_id(token, doc_id, FAILED_STATUS)
    finally:
        # todo
        log = structlog.get_logger(doc_id=None)




def auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def login() -> str:
    resp = requests.post(
        f"{MZINGA_URL}/api/users/login",
        json={f"email": MZINGA_EMAIL, "password": MZINGA_PASSWORD},
    )

    return resp.json()["token"]


def list_pending_docs(token: str) -> dict:
    res = requests.get(
        f"{MZINGA_URL}/api/communications/?where[status][equals]=pending&depth=1",
        headers=auth_headers(token)
    )
    res.raise_for_status()
    return res.json()["docs"]

def get_communication_by_id(token: str, id: str) -> dict:
    res = requests.get(
        f"{MZINGA_URL}/api/communications/{id}?depth=1",
        headers=auth_headers(token)
    )

    res.raise_for_status()
    return res.json()


def update_status_by_communication_id(token: str, id: str, new_status: str) -> None:
    res = requests.patch(
        f"{MZINGA_URL}/api/communications/{id}",
        json={"status" : f"{new_status}"},
        headers=auth_headers(token),
    )
    res.raise_for_status()



if __name__ == "__main__":
    log.info(f"Worker started. Polling every {POLL_INTERVAL}s")

    token = login()

    while True:
        try:
            docs = list_pending_docs(token)
            if docs:
                for doc in docs:
                    process(doc, token)
            else:
                time.sleep(POLL_INTERVAL)
        except requests.HTTPError as e:
            if e.response.status_code == 401:
                log.warning("Re-logging...")
                token=login()
            else:
                log.error(f"HTTP Error: {e}")
                time.sleep(POLL_INTERVAL)