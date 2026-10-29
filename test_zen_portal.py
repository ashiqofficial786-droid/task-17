import os
import re

import pytest
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Page
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

LOGIN_URL = "https://www.zenclass.in/login"
WAIT_TIME = 15000

VALID_USERNAME = os.getenv("ZEN_USERNAME", "")
VALID_PASSWORD = os.getenv("ZEN_PASSWORD", "")

needs_credentials = pytest.mark.skipif(
    not (VALID_USERNAME and VALID_PASSWORD),
    reason="Set ZEN_USERNAME and ZEN_PASSWORD environment variables first",
)


class BasePage:
    def __init__(self, page: Page):
        self.page = page

    def wait_until_visible(self, element, timeout=WAIT_TIME):
        try:
            element.wait_for(state="visible", timeout=timeout)
        except PlaywrightTimeoutError as error:
            raise AssertionError(f"Element not visible after {timeout} ms: {element}") from error

    def click_element(self, element):
        self.wait_until_visible(element)
        element.click()

    def type_text(self, element, text):
        self.wait_until_visible(element)
        element.fill(text)

    def is_element_visible(self, element, timeout=5000):
        try:
            element.wait_for(state="visible", timeout=timeout)
            return True
        except PlaywrightTimeoutError:
            return False


class LoginPage(BasePage):
    def __init__(self, page: Page):
        super().__init__(page)
        self.username_box = page.locator(
            "input:not([type='password']):not([type='hidden']):not([type='checkbox'])"
            ":not([type='radio']):not([type='submit']):not([type='button'])"
        ).first
        self.password_box = page.locator("input[type='password']").first
        self.submit_button = page.get_by_role(
            "button", name=re.compile(r"sign\s?in|log\s?in|login|submit", re.I)
        ).first
        self.error_message = page.locator(
            ".error, .alert, [role='alert'], .Toastify__toast--error, .text-danger"
        ).first

    def open_page(self):
        try:
            self.page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=WAIT_TIME * 2)
        except PlaywrightError as error:
            raise AssertionError(f"Could not open {LOGIN_URL}: {error}") from error
        self.wait_until_visible(self.username_box)

    def login(self, username, password):
        self.type_text(self.username_box, username)
        self.type_text(self.password_box, password)
        self.click_element(self.submit_button)

    def get_error_text(self):
        if self.is_element_visible(self.error_message, timeout=8000):
            return self.error_message.inner_text().strip()
        return ""


class DashboardPage(BasePage):
    def __init__(self, page: Page):
        super().__init__(page)
        self.popup = page.locator(".MuiModal-root").first
        self.popup_close_button = self.popup.locator(
            "button[aria-label*='close' i], button:has-text('Close'), "
            "[data-testid='CloseIcon'], button:has(svg), button:has(img)"
        ).first
        self.profile_menu = (
            page.get_by_text(re.compile(r"^\s*student\s*$", re.I)).filter(visible=True).first
        )
        self.logout_button = page.get_by_text(re.compile(r"^\s*log\s?out\s*$", re.I)).first

    def close_popup(self):
        if not self.is_element_visible(self.popup, timeout=6000):
            return
        if self.is_element_visible(self.popup_close_button, timeout=1500):
            self.popup_close_button.click()
        else:
            self.page.keyboard.press("Escape")
        try:
            self.popup.wait_for(state="hidden", timeout=WAIT_TIME)
        except PlaywrightTimeoutError as error:
            raise AssertionError("The popup could not be closed") from error

    def is_loaded(self):
        try:
            self.page.wait_for_url("**/dashboard**", timeout=WAIT_TIME * 2)
        except PlaywrightTimeoutError:
            return False
        self.close_popup()
        return True

    def logout(self):
        self.close_popup()
        self.click_element(self.profile_menu)
        self.click_element(self.logout_button)


@pytest.fixture()
def login_page(page: Page):
    page.set_default_timeout(WAIT_TIME)
    login = LoginPage(page)
    login.open_page()
    return login


@needs_credentials
def test_successful_login(page, login_page):
    login_page.login(VALID_USERNAME, VALID_PASSWORD)
    assert DashboardPage(page).is_loaded(), "Dashboard did not load after valid login"


def test_unsuccessful_login(page, login_page):
    login_page.login("invalid_user@example.com", "WrongPass@123")
    error_shown = login_page.get_error_text() != ""
    still_on_login_page = "login" in page.url
    assert error_shown or still_on_login_page, "Invalid login was accepted"


def test_username_password_input_boxes(login_page):
    assert login_page.username_box.is_visible(), "Username box is not visible"
    assert login_page.username_box.is_enabled(), "Username box is not enabled"
    assert login_page.password_box.is_visible(), "Password box is not visible"
    assert login_page.password_box.is_enabled(), "Password box is not enabled"

    login_page.type_text(login_page.username_box, "sample_user")
    login_page.type_text(login_page.password_box, "sample_pass")
    assert login_page.username_box.input_value() == "sample_user"
    assert login_page.password_box.input_value() == "sample_pass"

    assert login_page.password_box.get_attribute("type") == "password"


def test_submit_button_working(page, login_page):
    assert login_page.submit_button.is_visible(), "Submit button is not visible"
    assert login_page.submit_button.is_enabled(), "Submit button is not enabled"

    login_page.type_text(login_page.username_box, "check_user@example.com")
    login_page.type_text(login_page.password_box, "check_pass")
    try:
        with page.expect_response(lambda r: r.request.method == "POST", timeout=WAIT_TIME):
            login_page.click_element(login_page.submit_button)
    except PlaywrightTimeoutError:
        pytest.fail("Clicking Submit did not send any login request")


@needs_credentials
def test_logout_functionality(page, login_page):
    login_page.login(VALID_USERNAME, VALID_PASSWORD)
    dashboard = DashboardPage(page)
    assert dashboard.is_loaded(), "Dashboard did not load, cannot test logout"

    dashboard.logout()
    try:
        page.wait_for_url("**/login**", timeout=WAIT_TIME)
    except PlaywrightTimeoutError:
        pytest.fail("Logout did not go back to the login page")
    assert login_page.is_element_visible(login_page.username_box), "Login form not shown after logout"