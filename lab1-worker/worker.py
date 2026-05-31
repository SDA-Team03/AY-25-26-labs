import os
import time
import smtplib
import logging
from typing import List, Optional
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from dotenv import load_dotenv
from pymongo import MongoClient
from bson import ObjectId


load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)


client = MongoClient(os.environ["MONGODB_URI"])
db = client.get_default_database()


POLL_INTERVAL: int = int(os.getenv("POLL_INTERVAL_SECONDS", 5))
SMTP_HOST: str = os.getenv("SMTP_HOST", "localhost")
SMTP_PORT: int = int(os.getenv("SMTP_PORT", 1025))
EMAIL_FROM: str = os.getenv("EMAIL_FROM", "worker@mzinga.io")


def _extract_object_ids(relationship_list: List[dict]) -> List[ObjectId]:
    return [ObjectId(r["value"]) for r in relationship_list if r.get("value")]


def _build_mime_message(subject: str, email_from: str, to_addresses: List[str], cc_addresses: Optional[List[str]], html: str) -> MIMEMultipart:
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = email_from
    msg["To"] = ", ".join(to_addresses)
    if cc_addresses:
        msg["Cc"] = ", ".join(cc_addresses)
    msg.attach(MIMEText(html, "html"))
    return msg


def _all_recipients(to_addresses: List[str], cc_addresses: Optional[List[str]], bcc_addresses: Optional[List[str]]) -> List[str]:
    return to_addresses + (cc_addresses or []) + (bcc_addresses or [])


def _set_status(doc_id, status: str) -> None:
    db.communications.update_one({"_id": doc_id}, {"$set": {"status": status}})


def render_slate_html(nodes: List[dict]) -> str:
    html = ""
    for node in nodes or []:
        ntype = node.get("type")
        if ntype == "paragraph":
            html += f"<p>{render_slate_html(node.get('children', []))}</p>"
        elif ntype == "h1":
            html += f"<h1>{render_slate_html(node.get('children', []))}</h1>"
        elif ntype == "h2":
            html += f"<h2>{render_slate_html(node.get('children', []))}</h2>"
        elif ntype == "ul":
            html += f"<ul>{render_slate_html(node.get('children', []))}</ul>"
        elif ntype == "li":
            html += f"<li>{render_slate_html(node.get('children', []))}</li>"
        elif ntype == "link":
            url = node.get("url", "#")
            html += f'<a href="{url}">{render_slate_html(node.get("children", []))}</a>'
        elif "text" in node:
            text = node["text"]
            if node.get("bold"):
                text = f"<strong>{text}</strong>"
            if node.get("italic"):
                text = f"<em>{text}</em>"
            html += text
        else:
            html += render_slate_html(node.get("children", []))
    return html


def resolve_emails_from_relationships(relationship_list: List[dict]) -> List[str]:
    if not relationship_list:
        return []
    ids = _extract_object_ids(relationship_list)
    users = db.users.find({"_id": {"$in": ids}}, {"email": 1})
    return [u["email"] for u in users if u.get("email")]


def send_email(
    to_addresses: List[str],
    subject: str,
    html: str,
    cc_addresses: Optional[List[str]] = None,
    bcc_addresses: Optional[List[str]] = None,
) -> None:
    if not to_addresses:
        raise ValueError("No 'to' recipients provided to send_email")
    msg = _build_mime_message(subject, EMAIL_FROM, to_addresses, cc_addresses, html)
    all_recipients =_all_recipients(to_addresses, cc_addresses, bcc_addresses)
    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
        server.sendmail(EMAIL_FROM, all_recipients, msg.as_string())


def process_communication(doc: dict) -> None:
    doc_id = doc["_id"]
    log.info(f"Processing communication {doc_id}")
    _set_status(doc_id, "processing")
    try:
        to_emails = resolve_emails_from_relationships(doc.get("tos") or [])
        if not to_emails:
            raise ValueError("No valid 'to' email addresses found")
        cc_emails = resolve_emails_from_relationships(doc.get("ccs") or [])
        bcc_emails = resolve_emails_from_relationships(doc.get("bccs") or [])
        html = render_slate_html(doc.get("body") or [])
        send_email(to_emails, doc["subject"], html, cc_emails, bcc_emails)
        _set_status(doc_id, "sent")
        log.info(f"Communication {doc_id} sent successfully")
    except Exception:
        log.exception(f"Failed to process communication {doc_id}")
        _set_status(doc_id, "failed")


def poll() -> None:
    log.info(f"Worker started. Polling every {POLL_INTERVAL}s")
    while True:
        doc = db.communications.find_one({"status": "pending"})
        if doc:
            process_communication(doc)
        else:
            time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    poll()
