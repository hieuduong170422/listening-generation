import urllib.request

BASE = "http://localhost:8591"

try:
    resp = urllib.request.urlopen(f"{BASE}/", timeout=5)
    html = resp.read().decode("utf-8", errors="replace")[:4000]
    print(f"Status: {resp.status}")
    has_login = "App Login" in html or "Password" in html
    has_password_input = 'type="password"' in html
    print(f"Login form shown: {has_login}")
    print(f"Password input field: {has_password_input}")

    if has_login and has_password_input:
        print("\n=== VERIFICATION PASSED ===")
        print("Login page is displayed when APP_PASSWORD is set.")
        print("Password input is masked (type=password).")
    else:
        print("\n=== VERIFICATION FAILED ===")
        print("Expected login form with password field.")

except Exception as e:
    print(f"Error: {e}")
