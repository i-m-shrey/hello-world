import os
import tempfile
import shutil
import time
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.common.exceptions import WebDriverException


def build_chrome_driver(max_retries: int = 2):
    """
    Build a Chromium WebDriver suitable for Cloud Run:
    - headless=new
    - no-sandbox, disable-dev-shm-usage
    - writable temp user-data-dir under /tmp
    - uses CHROME_BIN and CHROMEDRIVER_PATH if present
    """
    os.environ.setdefault("XDG_RUNTIME_DIR", "/tmp")

    # Unique profile per start to avoid 'profile in use' and DevToolsActivePort issues
    tmp_profile = tempfile.mkdtemp(prefix="chrome-profile-", dir="/tmp")

    opts = Options()
    opts.add_argument(f"--user-data-dir={tmp_profile}")
    opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--window-size=1280,720")
    opts.add_argument("--remote-debugging-port=9222")
    opts.add_argument("--disable-dev-tools")
    opts.add_argument("--single-process")

    if os.getenv("CHROME_BIN"):
        opts.binary_location = os.getenv("CHROME_BIN")

    service = Service(executable_path=os.getenv("CHROMEDRIVER_PATH") or None)

    last_err = None
    for attempt in range(1, max_retries + 2):
        try:
            driver = webdriver.Chrome(service=service, options=opts)
            # Keep reference to cleanup path
            driver._tmp_profile = tmp_profile  # type: ignore[attr-defined]
            return driver
        except WebDriverException as e:
            last_err = e
            time.sleep(1.0 * attempt)
        except Exception as e:  # any other
            last_err = e
            break

    # Cleanup if failed to start
    shutil.rmtree(tmp_profile, ignore_errors=True)
    if last_err:
        raise last_err
    raise RuntimeError("Failed to start Chrome driver")


def safe_quit(driver):
    try:
        driver.quit()
    except Exception:
        pass
    # Remove temp profile if we set it
    tmp = getattr(driver, "_tmp_profile", None)
    if tmp:
        shutil.rmtree(tmp, ignore_errors=True)
