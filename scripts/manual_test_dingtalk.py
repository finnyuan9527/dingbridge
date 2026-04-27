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
    from alibabacloud_dingtalk.oauth2_1_0.client import Client as OAuth2Client
    from alibabacloud_dingtalk.oauth2_1_0 import models as oauth2_models
    from alibabacloud_tea_openapi import models as open_api_models
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
    scope = "openid corpid Contact.User.Read"
        
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

    print("\n[Step 1] Exchanging Code for UserAccessToken via SDK...")
    try:
        config = open_api_models.Config(protocol='https', region_id='central')
        oauth_client = OAuth2Client(config)
        token_request = oauth2_models.GetUserTokenRequest(
            client_id=settings.dingtalk.app_key,
            client_secret=settings.dingtalk.app_secret,
            code=code,
            grant_type='authorization_code'
        )
        token_response = oauth_client.get_user_token(token_request)
        access_token = token_response.body.access_token
        print(f"AccessToken: {access_token[:10]}... (success)")
    except Exception as e:
        print(f"Failed to get token: {e}")
        return

    print("\n[Step 2] Fetching User Info via HTTP API (Bypassing SDK Models)...")
    contact_data = None
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
            contact_data = resp.json()
            print(json.dumps(contact_data, indent=2, ensure_ascii=False))
        except:
            print(resp.text)
            
    except Exception as e:
        print(f"Error fetching user info: {e}")
        contact_data = None

    union_id = (contact_data or {}).get("unionId")
    if not union_id:
        print("\n[Step 3] Skip OAPI: unionId missing")
        return

    print("\n[Step 3] Fetching AppAccessToken...")
    try:
        resp = requests.get(
            "https://oapi.dingtalk.com/gettoken",
            params={
                "appkey": settings.dingtalk.app_key,
                "appsecret": settings.dingtalk.app_secret,
            },
        )
        token_data = resp.json()
        print(json.dumps(token_data, indent=2, ensure_ascii=False))
        app_access_token = token_data.get("access_token")
    except Exception as e:
        print(f"Error fetching app access token: {e}")
        return

    if not app_access_token:
        print("\n[Step 4] Skip OAPI: app access token missing")
        return

    print("\n[Step 4] Fetching UserId by UnionId...")
    try:
        resp = requests.post(
            "https://oapi.dingtalk.com/topapi/user/getbyunionid",
            params={"access_token": app_access_token},
            json={"unionid": union_id},
        )
        userid_data = resp.json()
        print(json.dumps(userid_data, indent=2, ensure_ascii=False))
        user_id = (userid_data.get("result") or {}).get("userid")
    except Exception as e:
        print(f"Error fetching userid: {e}")
        return

    if not user_id:
        print("\n[Step 5] Skip OAPI: userid missing")
        return

    print("\n[Step 5] Fetching User Detail by UserId...")
    try:
        resp = requests.post(
            "https://oapi.dingtalk.com/topapi/v2/user/get",
            params={"access_token": app_access_token},
            json={"userid": user_id},
        )
        detail_data = resp.json()
        print(json.dumps(detail_data, indent=2, ensure_ascii=False))
    except Exception as e:
        print(f"Error fetching user detail: {e}")

if __name__ == "__main__":
    main()
