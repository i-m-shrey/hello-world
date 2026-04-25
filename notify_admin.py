# appsrc/strategy_runner/notify_admin.py
import logging

def notify_admin(subject: str, html_body: str, text_body: str | None = None) -> bool:
    """
    Calls your existing appsrc.email_notifications function.
    Accepts common variants and signatures in that module.
    """
    try:
        import email_notifications as en
    except Exception as e:
        logging.warning("notify_admin: cannot import email_notifications: %s", e)
        return False

    candidates = (
        "send_email_to_admins",
        "send_admin_email",
        "send_email",
        "send_admin_alert_email",
        "notify_admins",
        "notify_admin",
    )

    for fname in candidates:
        fn = getattr(en, fname, None)
        if not callable(fn):
            continue
        try:
            result = fn(subject=subject, html_body=html_body, text_body=text_body)
            if isinstance(result, bool):
                return result
            return True
        except TypeError:
            try:
                result = fn(subject, html_body)
                if isinstance(result, bool):
                    return result
                return True
            except TypeError:
                if fname == "send_email":
                    try:
                        import os as _os
                        to_addr = _os.getenv("ADMIN_EMAIL", "smartetfalgo@gmail.com")
                        result = fn(to_addr, subject, html_body, True)
                        if isinstance(result, bool):
                            return result
                        return True
                    except Exception as e:
                        logging.error("notify_admin: send_email call failed: %s", e)
                        continue
                else:
                    try:
                        result = fn(subject, text_body or html_body)
                        if isinstance(result, bool):
                            return result
                        return True
                    except Exception as e:
                        logging.error("notify_admin: %s call failed: %s", fname, e)
                        continue
        except Exception as e:
            logging.error("notify_admin: %s raised: %s", fname, e)
            continue

    logging.warning("notify_admin: no known function matched in appsrc.email_notifications")
    return False
