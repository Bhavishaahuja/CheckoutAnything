# check_setup.py
# Tonight's "done when": prove your PayPal sandbox keys and Anthropic key both work.
# Run it with:  python check_setup.py

import os
import requests
from dotenv import load_dotenv
import anthropic

# pull keys out of the .env file sitting next to this script
load_dotenv()

paypal_client_id = os.getenv("PAYPAL_CLIENT_ID")
paypal_secret = os.getenv("PAYPAL_CLIENT_SECRET")
anthropic_key = os.getenv("ANTHROPIC_API_KEY")

# sandbox base URL, straight from PayPal's REST docs
PAYPAL_BASE = "https://api-m.sandbox.paypal.com"


def check_paypal():
    print("Checking PayPal sandbox...")

    if not paypal_client_id or not paypal_secret:
        print("  Missing PAYPAL_CLIENT_ID or PAYPAL_CLIENT_SECRET in .env")
        return False

    # client_credentials grant. requests handles the base64 of id:secret for us via auth=
    response = requests.post(
        PAYPAL_BASE + "/v1/oauth2/token",
        auth=(paypal_client_id, paypal_secret),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        data={"grant_type": "client_credentials"},
        timeout=30,
    )

    if response.status_code != 200:
        print("  Failed:", response.status_code, response.text)
        return False

    token_info = response.json()
    token = token_info["access_token"]
    print("  Got a token:", token[:12] + "...")
    print("  Expires in", token_info["expires_in"], "seconds")

    # the scope string tells us what this app is allowed to touch.
    # we care about auth/capture (core flow) and disputes (week 3)
    scope = token_info.get("scope", "")
    things_we_need = {
        "authcapture": "authorize + capture",
        "disputes": "disputes API",
    }
    for keyword in things_we_need:
        if keyword in scope:
            print("  OK  scope includes", things_we_need[keyword])
        else:
            print("  ??  scope missing", things_we_need[keyword], "(flag this to Claude)")

    return True


def check_anthropic():
    print("Checking Anthropic API...")

    if not anthropic_key:
        print("  Missing ANTHROPIC_API_KEY in .env")
        return False

    client = anthropic.Anthropic(api_key=anthropic_key)

    try:
        reply = client.messages.create(
            model="claude-sonnet-5-5",
            max_tokens=50,
            messages=[{"role": "user", "content": "Reply with exactly: Leash is alive"}],
        )
    except Exception as err:
        print("  Failed:", err)
        return False

    # grab the text out of the first content block
    reply_text = ""
    for block in reply.content:
        if block.type == "text":
            reply_text = block.text
            break

    print("  Claude says:", reply_text)
    return True


if __name__ == "__main__":
    paypal_ok = check_paypal()
    print()
    claude_ok = check_anthropic()
    print()

    if paypal_ok and claude_ok:
        print("All good. Tonight is done.")
    else:
        print("Something's off, paste the output to Claude.")
