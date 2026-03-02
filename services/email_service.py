import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from loguru import logger

from config import settings


def send_alert_email(
    to_email: str,
    user_name: str,
    ticker: str,
    company_name: str,
    price: float,
    direction: str,
    threshold: float,
) -> bool:
    """Send a price alert email. Returns True on success."""
    smtp_user = settings.smtp_user
    smtp_password = settings.smtp_password

    if not smtp_user or not smtp_password:
        logger.warning("[email] SMTP credentials not configured — skipping email")
        return False

    subject = f"Stock Alert: {ticker} has gone {direction} ${threshold:.2f}"

    direction_word = "risen above" if direction == "above" else "fallen below"
    body_html = f"""
    <html><body>
    <h2 style="color:#333">Stock Price Alert</h2>
    <p>Hi {user_name},</p>
    <p>
      Your monitored stock <strong>{ticker}</strong> ({company_name}) has
      <strong>{direction_word}</strong> your threshold of
      <strong>${threshold:.2f}</strong>.
    </p>
    <table style="border-collapse:collapse;margin:16px 0">
      <tr>
        <td style="padding:6px 12px;background:#f5f5f5;font-weight:bold">Ticker</td>
        <td style="padding:6px 12px">{ticker}</td>
      </tr>
      <tr>
        <td style="padding:6px 12px;background:#f5f5f5;font-weight:bold">Company</td>
        <td style="padding:6px 12px">{company_name}</td>
      </tr>
      <tr>
        <td style="padding:6px 12px;background:#f5f5f5;font-weight:bold">Current Price</td>
        <td style="padding:6px 12px">${price:.2f}</td>
      </tr>
      <tr>
        <td style="padding:6px 12px;background:#f5f5f5;font-weight:bold">Threshold</td>
        <td style="padding:6px 12px">${threshold:.2f} ({direction})</td>
      </tr>
    </table>
    <p style="color:#888;font-size:12px">
      Sent by Stock Monitor · You will not be re-alerted for this stock for 30 minutes.
    </p>
    </body></html>
    """

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = smtp_user
    msg["To"] = to_email
    msg.attach(MIMEText(body_html, "html"))

    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as server:
            server.ehlo()
            server.starttls()
            server.login(smtp_user, smtp_password)
            server.sendmail(smtp_user, to_email, msg.as_string())
        logger.info(f"[email] Alert sent to {to_email} for {ticker}")
        return True
    except Exception as exc:
        logger.error(f"[email] Failed to send to {to_email}: {exc}")
        return False
