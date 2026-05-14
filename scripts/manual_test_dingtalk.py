import sys
import os
from urllib.parse import urlencode
import json
import requests

# 将项目根目录添加到 sys.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 尝试加载环境变量
from dotenv import load_dotenv
load_dotenv()

try:
    from app.config import settings
except ImportError as e:
    print(f"Error importing modules: {e}")
    sys.exit(1)

def main():
    print("DingTalk Diagnostic Script (Fetch Full JSON)")
    print("-" * 50)
    
    app_key = settings.dingtalk.app_key
    if not app_key:
        print("Error: DINGTALK_APP_KEY is not set.")
        sys.exit(1)
    
    callback_url = "https://oidcdebugger.com/debug"
    scope = "openid corpid"
        
    query = urlencode(
        {
            "client_id": app_key,
            "redirect_uri": callback_url,
            "response_type": "code",
            "scope": scope,
            "state": "test_state",
            "prompt": "consent"
        }
    )
    
    auth_url = f"{settings.dingtalk.auth_base_url}?{query}"
    
    print(f"Auth URL: {auth_url}")
    print("-" * 20)
    
    code = input("\nEnter Code from oidcdebugger: ").strip()
    if not code:
        return

    print("\n[Step 1] Exchanging Code for UserAccessToken via REST API...")
    try:
        resp = requests.post(
            "https://api.dingtalk.com/v1.0/oauth2/userAccessToken",
            json={
                "clientId": settings.dingtalk.app_key,
                "clientSecret": settings.dingtalk.app_secret,
                "code": code,
                "grantType": "authorization_code",
            },
            timeout=5.0,
        )
        print(f"Status Code: {resp.status_code}")
        token_data = resp.json()
        print(json.dumps({k: ("***" if "Token" in k else v) for k, v in token_data.items()}, indent=2, ensure_ascii=False))
        resp.raise_for_status()
        access_token = token_data.get("accessToken")
        if not access_token:
            print("Failed to get token: response missing accessToken")
            return
        print(f"AccessToken: {access_token[:10]}... (success)")
    except Exception as e:
        print(f"Failed to get token: {e}")
        return

    print("\n[Step 2] Fetching User Info via REST API...")
    try:
        url = "https://api.dingtalk.com/v1.0/contact/users/me"
        headers = {
            "x-acs-dingtalk-access-token": access_token,
            "Content-Type": "application/json"
        }
        resp = requests.get(url, headers=headers)
        
        print(f"Status Code: {resp.status_code}")
        print("Response Body:")
        try:
            print(json.dumps(resp.json(), indent=2, ensure_ascii=False))
        except:
            print(resp.text)
            
    except Exception as e:
        print(f"Error fetching user info: {e}")

if __name__ == "__main__":
    main()
