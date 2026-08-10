# web_app.py - Fixed version with all nickname decoding

from flask import Flask, request, jsonify, render_template
import sys
import os
import json
import urllib.parse
import hashlib
import requests
import urllib3
import base64
import time
from datetime import datetime
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad, unpad
import importlib.util

# Disable SSL warnings
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Import protobuf modules
try:
    import MajoRLogin_pb2 as mLpB
    import MajorLoginRes_pb2 as mLrPb
except ImportError:
    # Try loading from current directory
    spec1 = importlib.util.spec_from_file_location("MajoRLogin_pb2", "MajoRLogin_pb2.py")
    spec2 = importlib.util.spec_from_file_location("MajorLoginRes_pb2", "MajorLoginRes_pb2.py")
    if spec1 and spec2:
        mLpB = importlib.util.module_from_spec(spec1)
        spec1.loader.exec_module(mLpB)
        mLrPb = importlib.util.module_from_spec(spec2)
        spec2.loader.exec_module(mLrPb)
    else:
        print("ERROR: Protobuf files not found!")
        sys.exit()

app = Flask(__name__)

# ─── Constants ───
AeSkEy = b'Yg&tc%DEuh6%Zc^8'
AeSiV = b'6oyZDr22E3ychjM%'

PLATFORM_MAP = {
    3: "Facebook", 4: "Guest", 5: "VK",
    6: "Huawei", 8: "Google", 11: "X (Twitter)", 13: "AppleId",
}

def enc(d): return AES.new(AeSkEy, AES.MODE_CBC, AeSiV).encrypt(pad(d, 16))
def dec(d): return unpad(AES.new(AeSkEy, AES.MODE_CBC, AeSiV).decrypt(d), 16)

def convert_seconds(s):
    d, h = divmod(s, 86400)
    h, m = divmod(h, 3600)
    m, s = divmod(m, 60)
    return f"{d} Day {h} Hour {m} Min {s} Sec"

def format_response_text(text, title):
    try:
        parsed = json.loads(text)
        result_code = parsed.get("result")
        if result_code == 0:
            return f'<span class="success">✅ {title}: SUCCESS</span>'
        elif result_code is not None:
            error_msg = parsed.get("error", "Unknown error")
            return f'<span class="error">❌ {title}: FAILED (Code: {result_code} | {error_msg})</span>'
        else:
            return f'<span class="info">ℹ️ {title}: Completed</span>'
    except:
        if '"result": 0' in text.replace(" ", ""):
            return f'<span class="success">✅ {title}: SUCCESS</span>'
        return f'<span class="warn">⚠️ {title}: Unrecognized response</span>'

# ─── Core Functions ───

def check_bind_info(access_token):
    lines = []
    lines.append('<span class="info">🔍 Fetching account bind information from Garena...</span>\n')

    # Player info - FIXED: decode nickname
    try:
        player_url = f"https://api-otrss.garena.com/support/callback/?access_token={access_token}"
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        p_res = requests.get(player_url, headers=headers, timeout=15, allow_redirects=True)
        parsed_url = urllib.parse.urlparse(p_res.url)
        qp = urllib.parse.parse_qs(parsed_url.query)
        uid = qp.get("account_id", ["Unknown"])[0]
        # FIX: Decode nickname properly
        nickname_raw = qp.get("nickname", ["Unknown"])[0]
        nickname = urllib.parse.unquote(nickname_raw) if nickname_raw != "Unknown" else "Unknown"
        region = qp.get("region", ["Unknown"])[0]
        lines.append(f'<span class="highlight">≡ Player Information</span>')
        lines.append(f'  ● UID: {uid}')
        lines.append(f'  ● Nickname: {nickname}')
        lines.append(f'  ● Region: {region}\n')
    except Exception as e:
        lines.append(f'<span class="warn">⚠️ Failed to fetch player details: {str(e)}</span>\n')

    # Bind info
    url = "https://100067.connect.garena.com/game/account_security/bind:get_bind_info"
    payload = {'app_id': "100067", 'access_token': access_token}
    headers = {'User-Agent': "GarenaMSDK/4.0.19P9(Redmi Note 5 ;Android 9;en;US;)"}
    try:
        response = requests.get(url, params=payload, headers=headers, timeout=15)
        if response.status_code == 200:
            data = response.json()
            email = data.get("email", "")
            email_to_be = data.get("email_to_be", "")
            countdown = data.get("request_exec_countdown", 0)
            result_code = data.get("result", -1)

            lines.append(f'<span class="highlight">≡ Bind Information</span>')
            lines.append(f'  ● Current Email: {email if email else "None"}')
            lines.append(f'  ● Pending Email: {email_to_be if email_to_be else "None"}')
            if email_to_be:
                lines.append(f'  ● Countdown: {convert_seconds(countdown)}')
            if result_code == 0:
                lines.append(f'  ● Result: <span class="success">✅ SUCCESS</span>')
            else:
                lines.append(f'  ● Result: <span class="error">❌ FAILED (Code: {result_code})</span>')

            if email == "" and email_to_be != "":
                lines.append(f'\n  ● Summary: Pending email confirmation: {email_to_be} - Confirms in: {convert_seconds(countdown)}')
            elif email != "" and email_to_be == "":
                lines.append(f'\n  ● Summary: Email confirmed: {email}')
            elif email == "" and email_to_be == "":
                lines.append('\n  ● Summary: No recovery email set')
        else:
            lines.append(f'<span class="error">❌ API Error (Status {response.status_code})</span>')
    except Exception as e:
        lines.append(f'<span class="error">❌ Failed to fetch info: {str(e)}</span>')

    return '\n'.join(lines)

def bind_email(access_token, email, otp, security_code):
    lines = []
    headers = {
        "User-Agent": "GarenaMSDK/4.0.30",
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "application/json"
    }

    # Step 1: Send OTP
    lines.append('<span class="info">📤 Step 1: Sending OTP...</span>')
    send_url = "https://100067.connect.garena.com/game/account_security/bind:send_otp"
    send_data = {"email": email, "locale": "en_PK", "region": "PK", "app_id": "100067", "access_token": access_token}
    try:
        r = requests.post(send_url, headers=headers, data=send_data)
        lines.append(format_response_text(r.text, "Send OTP"))
    except Exception as e:
        lines.append(f'<span class="error">❌ Send OTP failed: {str(e)}</span>')
        return '\n'.join(lines)

    # Step 2: Verify OTP
    lines.append('\n<span class="info">🔐 Step 2: Verifying OTP...</span>')
    verify_url = "https://100067.connect.garena.com/game/account_security/bind:verify_otp"
    verify_data = {
        "app_id": "100067",
        "access_token": access_token,
        "email": email,
        "code": otp,
        "otp": otp,
        "type": "1"
    }
    try:
        r = requests.post(verify_url, headers=headers, data=verify_data)
        lines.append(format_response_text(r.text, "Verify OTP"))
        verifier_token = r.json().get("verifier_token", "")
    except Exception as e:
        lines.append(f'<span class="error">❌ Verify OTP failed: {str(e)}</span>')
        return '\n'.join(lines)

    if not verifier_token:
        lines.append('<span class="error">❌ Could not extract verifier_token.</span>')
        return '\n'.join(lines)

    # Step 3: Create bind request
    lines.append('\n<span class="info">🔗 Step 3: Creating bind request...</span>')
    bind_url = "https://100067.connect.garena.com/game/account_security/bind:create_bind_request"
    bind_data = {
        "email": email,
        "app_id": "100067",
        "access_token": access_token,
        "verifier_token": verifier_token,
        "secondary_password": security_code
    }
    try:
        r = requests.post(bind_url, headers=headers, data=bind_data)
        lines.append(format_response_text(r.text, "Final Bind Request"))
    except Exception as e:
        lines.append(f'<span class="error">❌ Bind request failed: {str(e)}</span>')

    return '\n'.join(lines)

def unbind_email(access_token, method, otp=None, sec_code=None):
    lines = []

    # First check current email
    try:
        url_info = "https://100067.connect.garena.com/game/account_security/bind:get_bind_info"
        info_payload = {'app_id': "100067", 'access_token': access_token}
        info_headers = {'User-Agent': "GarenaMSDK/4.0.30"}
        r_info = requests.get(url_info, params=info_payload, headers=info_headers, timeout=10)
        email = r_info.json().get("email", "")
        if not email:
            return '<span class="error">❌ No currently bound email found!</span>'
        lines.append(f'<span class="info">📧 Current email: {email}</span>')
    except Exception as e:
        return f'<span class="error">❌ Failed to get current email: {str(e)}</span>'

    headers = {
        "User-Agent": "GarenaMSDK/4.0.30",
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "application/json"
    }

    identity_token = None

    if method == '1':  # OTP
        lines.append(f'<span class="info">📤 Sending OTP to {email}...</span>')
        send_url = "https://100067.connect.garena.com/game/account_security/bind:send_otp"
        send_data = {"email": email, "locale": "en_PK", "region": "PK", "app_id": "100067", "access_token": access_token}
        try:
            r = requests.post(send_url, headers=headers, data=send_data)
            lines.append(format_response_text(r.text, "Send OTP"))
        except Exception as e:
            lines.append(f'<span class="error">❌ Send OTP failed: {str(e)}</span>')
            return '\n'.join(lines)

        if not otp:
            return '\n'.join(lines) + '\n<span class="error">❌ OTP is required</span>'

        lines.append('\n<span class="info">🔐 Verifying identity via OTP...</span>')
        verify_url = "https://100067.connect.garena.com/game/account_security/bind:verify_identity"
        verify_data = {"email": email, "app_id": "100067", "access_token": access_token, "otp": otp}
        try:
            r = requests.post(verify_url, headers=headers, data=verify_data)
            lines.append(format_response_text(r.text, "Verify Identity"))
            identity_token = r.json().get("identity_token")
        except Exception as e:
            lines.append(f'<span class="error">❌ Verify failed: {str(e)}</span>')
            return '\n'.join(lines)

    else:  # Security Code
        if not sec_code:
            return '\n'.join(lines) + '\n<span class="error">❌ Security code is required</span>'
        hashed_sec = hashlib.sha256(sec_code.encode('utf-8')).hexdigest()
        lines.append('\n<span class="info">🔐 Verifying identity via Security Code...</span>')
        verify_url = "https://100067.connect.garena.com/game/account_security/bind:verify_identity"
        verify_data = {"email": email, "app_id": "100067", "access_token": access_token, "secondary_password": hashed_sec}
        try:
            r = requests.post(verify_url, headers=headers, data=verify_data)
            lines.append(format_response_text(r.text, "Verify Identity"))
            identity_token = r.json().get("identity_token")
        except Exception as e:
            lines.append(f'<span class="error">❌ Verify failed: {str(e)}</span>')
            return '\n'.join(lines)

    if not identity_token:
        lines.append('<span class="error">❌ Identity verification failed!</span>')
        return '\n'.join(lines)

    lines.append('\n<span class="info">🔓 Creating unbind request...</span>')
    unbind_url = "https://100067.connect.garena.com/game/account_security/bind:create_unbind_request"
    unbind_data = {"app_id": "100067", "access_token": access_token, "identity_token": identity_token}
    try:
        r = requests.post(unbind_url, headers=headers, data=unbind_data)
        lines.append(format_response_text(r.text, "Unbind Request"))
    except Exception as e:
        lines.append(f'<span class="error">❌ Unbind failed: {str(e)}</span>')

    return '\n'.join(lines)

def change_bind_email(access_token, method, otp=None, sec_code=None, new_email=None, new_otp=None):
    lines = []

    # Get current email
    try:
        url_info = "https://100067.connect.garena.com/game/account_security/bind:get_bind_info"
        info_payload = {'app_id': "100067", 'access_token': access_token}
        info_headers = {'User-Agent': "GarenaMSDK/4.0.30"}
        r_info = requests.get(url_info, params=info_payload, headers=info_headers, timeout=10)
        old_email = r_info.json().get("email", "")
        if not old_email:
            return '<span class="error">❌ No currently bound email found!</span>'
        lines.append(f'<span class="info">📧 Current email: {old_email}</span>')
    except Exception as e:
        return f'<span class="error">❌ Failed to get current email: {str(e)}</span>'

    headers = {
        "User-Agent": "GarenaMSDK/4.0.30",
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "application/json"
    }

    identity_token = None

    if method == '1':  # OTP
        lines.append(f'<span class="info">📤 Sending OTP to {old_email}...</span>')
        send_url = "https://100067.connect.garena.com/game/account_security/bind:send_otp"
        send_data = {"email": old_email, "locale": "en_PK", "region": "PK", "app_id": "100067", "access_token": access_token}
        try:
            r = requests.post(send_url, headers=headers, data=send_data)
            lines.append(format_response_text(r.text, "Send OTP"))
        except Exception as e:
            lines.append(f'<span class="error">❌ Send OTP failed: {str(e)}</span>')
            return '\n'.join(lines)

        if not otp:
            return '\n'.join(lines) + '\n<span class="error">❌ OTP is required</span>'

        lines.append('\n<span class="info">🔐 Verifying old email identity...</span>')
        verify_url = "https://100067.connect.garena.com/game/account_security/bind:verify_identity"
        verify_data = {"email": old_email, "app_id": "100067", "access_token": access_token, "otp": otp}
        try:
            r = requests.post(verify_url, headers=headers, data=verify_data)
            lines.append(format_response_text(r.text, "Verify Identity"))
            identity_token = r.json().get("identity_token")
        except Exception as e:
            lines.append(f'<span class="error">❌ Verify failed: {str(e)}</span>')
            return '\n'.join(lines)

    else:  # Security Code
        if not sec_code:
            return '\n'.join(lines) + '\n<span class="error">❌ Security code is required</span>'
        hashed_sec = hashlib.sha256(sec_code.encode('utf-8')).hexdigest()
        lines.append('\n<span class="info">🔐 Verifying identity via Security Code...</span>')
        verify_url = "https://100067.connect.garena.com/game/account_security/bind:verify_identity"
        verify_data = {"email": old_email, "app_id": "100067", "access_token": access_token, "secondary_password": hashed_sec}
        try:
            r = requests.post(verify_url, headers=headers, data=verify_data)
            lines.append(format_response_text(r.text, "Verify Identity"))
            identity_token = r.json().get("identity_token")
        except Exception as e:
            lines.append(f'<span class="error">❌ Verify failed: {str(e)}</span>')
            return '\n'.join(lines)

    if not identity_token:
        lines.append('<span class="error">❌ Identity verification failed!</span>')
        return '\n'.join(lines)

    if not new_email:
        return '\n'.join(lines) + '\n<span class="error">❌ New email is required</span>'

    lines.append(f'\n<span class="info">📤 Sending OTP to {new_email}...</span>')
    send_url = "https://100067.connect.garena.com/game/account_security/bind:send_otp"
    send_data = {"email": new_email, "locale": "en_PK", "region": "PK", "app_id": "100067", "access_token": access_token}
    try:
        r = requests.post(send_url, headers=headers, data=send_data)
        lines.append(format_response_text(r.text, "Send OTP"))
    except Exception as e:
        lines.append(f'<span class="error">❌ Send OTP failed: {str(e)}</span>')
        return '\n'.join(lines)

    if not new_otp:
        return '\n'.join(lines) + '\n<span class="error">❌ New email OTP is required</span>'

    lines.append('\n<span class="info">🔐 Verifying new email OTP...</span>')
    verify_url = "https://100067.connect.garena.com/game/account_security/bind:verify_otp"
    verify_data = {"email": new_email, "app_id": "100067", "access_token": access_token, "otp": new_otp}
    try:
        r = requests.post(verify_url, headers=headers, data=verify_data)
        lines.append(format_response_text(r.text, "Verify OTP"))
        verifier_token = r.json().get("verifier_token")
    except Exception as e:
        lines.append(f'<span class="error">❌ Verify OTP failed: {str(e)}</span>')
        return '\n'.join(lines)

    if not verifier_token:
        lines.append('<span class="error">❌ Could not extract verifier_token.</span>')
        return '\n'.join(lines)

    lines.append('\n<span class="info">🔄 Creating rebind request...</span>')
    rebind_url = "https://100067.connect.garena.com/game/account_security/bind:create_rebind_request"
    rebind_data = {
        "identity_token": identity_token,
        "email": new_email,
        "app_id": "100067",
        "verifier_token": verifier_token,
        "access_token": access_token
    }
    try:
        r = requests.post(rebind_url, headers=headers, data=rebind_data)
        lines.append(format_response_text(r.text, "Rebind Request"))
    except Exception as e:
        lines.append(f'<span class="error">❌ Rebind failed: {str(e)}</span>')

    return '\n'.join(lines)

def cancel_bind_request(access_token):
    lines = []
    lines.append('<span class="info">❌ Creating cancel request...</span>')
    url = "https://100067.connect.garena.com/game/account_security/bind:cancel_request"
    headers = {
        "User-Agent": "GarenaMSDK/4.0.30",
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "application/json"
    }
    data = {"app_id": "100067", "access_token": access_token}
    try:
        r = requests.post(url, headers=headers, data=data)
        lines.append(format_response_text(r.text, "Cancel Request"))
    except Exception as e:
        lines.append(f'<span class="error">❌ Cancel failed: {str(e)}</span>')
    return '\n'.join(lines)

def eat_to_access_token(eat_input):
    lines = []
    eat_token = None

    if "http" in eat_input or "?" in eat_input:
        parsed = urllib.parse.urlparse(eat_input)
        qp = urllib.parse.parse_qs(parsed.query)
        if 'eat' in qp:
            eat_token = qp['eat'][0]
    else:
        eat_token = eat_input.strip()

    if not eat_token:
        return '<span class="error">❌ Could not find EAT token in input.</span>'

    lines.append('<span class="info">🔑 Contacting server & following redirects...</span>')
    api_url = f"https://api-otrss.garena.com/support/callback/?access_token={eat_token}"
    headers = {"User-Agent": "Mozilla/5.0 (Linux; Android 13; Mobile) AppleWebKit/537.36"}

    try:
        response = requests.get(api_url, headers=headers, allow_redirects=True, timeout=15)
        parsed_final = urllib.parse.urlparse(response.url)
        final_params = urllib.parse.parse_qs(parsed_final.query)

        if 'access_token' in final_params:
            access_token = final_params['access_token'][0]
            account_id = final_params.get('account_id', ['Unknown'])[0]
            # Decode nickname
            nickname_raw = final_params.get('nickname', ['Unknown'])[0]
            nickname = urllib.parse.unquote(nickname_raw) if nickname_raw != "Unknown" else "Unknown"
            region = final_params.get('region', ['Unknown'])[0]

            lines.append(f'<span class="highlight">✅ SUCCESS</span>')
            lines.append(f'  ● Nickname    : {nickname}')
            lines.append(f'  ● Account ID  : {account_id}')
            lines.append(f'  ● Region      : {region}')
            lines.append(f'  ● Access Token: <span class="highlight">{access_token}</span>')
        else:
            lines.append('<span class="error">❌ Access token not found. Token might be expired or invalid.</span>')
    except Exception as e:
        lines.append(f'<span class="error">❌ Failed to generate access token: {str(e)}</span>')

    return '\n'.join(lines)

def revoke_access_token(access_token):
    lines = []

    # Check token validity
    api_url = f"https://api-otrss.garena.com/support/callback/?access_token={access_token}"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

    nickname = "Unknown"
    account_id = "Unknown"
    region = "Unknown"
    is_valid = False

    try:
        res = requests.get(api_url, headers=headers, allow_redirects=True, timeout=15)
        parsed = urllib.parse.urlparse(res.url)
        params = urllib.parse.parse_qs(parsed.query)
        if 'access_token' in params:
            is_valid = True
            # Decode nickname
            nickname_raw = params.get('nickname', ['Unknown'])[0]
            nickname = urllib.parse.unquote(nickname_raw) if nickname_raw != "Unknown" else "Unknown"
            account_id = params.get('account_id', ['Unknown'])[0]
            region = params.get('region', ['Unknown'])[0]
    except:
        pass

    if not is_valid:
        return '<span class="error">❌ Token is already invalid, expired, or revoked!</span>'

    lines.append(f'<span class="success">✅ Token is Valid!</span>')
    lines.append(f'  ● Nickname: {nickname}')
    lines.append(f'  ● Account ID: {account_id}')
    lines.append(f'  ● Region: {region}')

    lines.append('\n<span class="info">🚫 Revoking token access...</span>')
    refresh_token = "1380dcb63ab3a077dc05bdf0b25ba4497c403a5b4eae96d7203010eafa6c83a8"
    logout_url = f"https://100067.connect.garena.com/oauth/logout?access_token={access_token}&refresh_token={refresh_token}"

    try:
        logout_res = requests.get(logout_url, headers=headers, timeout=15)
        if logout_res.status_code == 200 and "error" not in logout_res.text:
            lines.append(f'<span class="success">✅ Successfully Logged Out & Revoked</span>')
        else:
            lines.append('<span class="error">❌ Failed to revoke token!</span>')
    except Exception as e:
        lines.append(f'<span class="error">❌ Error: {str(e)}</span>')

    return '\n'.join(lines)

def build_majorlogin(tok, open_id, p_type):
    m = mLpB.MajorLogin()
    m.event_time = str(datetime.now())[:-7]
    m.game_name = "free fire"
    m.platform_id = p_type
    m.client_version = "1.120.1"
    m.system_software = "Android OS 9 / API-28"
    m.system_hardware = "Handheld"
    m.telecom_operator = "Verizon"
    m.network_type = "WIFI"
    m.screen_width = 1920
    m.screen_height = 1080
    m.screen_dpi = "280"
    m.processor_details = "ARM64 FP ASIMD AES VMH | 2865 | 4"
    m.memory = 3003
    m.gpu_renderer = "Adreno (TM) 640"
    m.gpu_version = "OpenGL ES 3.1 v1.46"
    m.unique_device_id = "Google|34a7dcdf-a7d5-4cb6-8d7e-3b0e448a0c57"
    m.client_ip = "223.191.51.89"
    m.language = "en"
    m.open_id = open_id
    m.open_id_type = str(p_type)
    m.device_type = "Handheld"
    m.access_token = tok
    m.platform_sdk_id = 1
    m.client_using_version = "7428b253defc164018c604a1ebbfebdf"
    m.login_by = 3
    m.channel_type = 3
    m.cpu_type = 2
    m.cpu_architecture = "64"
    m.client_version_code = "2019118695"
    m.login_open_id_type = p_type
    m.origin_platform_type = str(p_type)
    m.primary_platform_type = str(p_type)
    return enc(m.SerializeToString())

def read_varint(data, offset):
    res = 0; shift = 0
    while True:
        if offset >= len(data): break
        b = data[offset]; offset += 1
        res |= (b & 0x7f) << shift
        if not (b & 0x80): break
        shift += 7
    return res, offset

def parse_record(data):
    rec = {}; offset = 0
    while offset < len(data):
        tag, offset = read_varint(data, offset)
        wt, f = tag & 7, tag >> 3
        if wt == 0:
            val, offset = read_varint(data, offset)
            if f == 1: rec['ts'] = val
            elif f == 2: rec['ram'] = val
        elif wt == 2:
            length, offset = read_varint(data, offset)
            val = data[offset:offset+length]; offset += length
            if f == 3: rec['dev'] = val.decode(errors='ignore')
            elif f == 4: rec['arch'] = val.decode(errors='ignore')
        else: break
    return rec

def parse_history_protobuf(data):
    records = []; offset = 0
    while offset < len(data):
        tag, offset = read_varint(data, offset)
        wt, f = tag & 7, tag >> 3
        if wt == 0:
            val, offset = read_varint(data, offset)
        elif wt == 2:
            length, offset = read_varint(data, offset)
            val = data[offset:offset+length]; offset += length
            if f == 1: records.append(parse_record(val))
        else: break
    return records

def get_login_history(token):
    lines = []
    jwt_token = None

    if token.startswith("ey") and "." in token:
        jwt_token = token
        lines.append('<span class="success">✅ Detected valid JWT Token.</span>')
    else:
        lines.append('<span class="info">🔍 Resolving Open ID from Access Token...</span>')
        oId = None

        try:
            r = requests.get(f"https://100067.connect.garena.com/oauth/token/inspect?token={token}", headers={"User-Agent": "Mozilla/5.0"}, timeout=5).json()
            oId = r.get("open_id")
        except: pass

        if not oId:
            try:
                uid_headers = {"access-token": token, "user-agent": "Mozilla/5.0"}
                uid_res = requests.get("https://prod-api.reward.ff.garena.com/redemption/api/auth/inspect_token/", headers=uid_headers, verify=False, timeout=5).json()
                uid = uid_res.get("uid")
                if uid:
                    openid_res = requests.post("https://topup.pk/api/auth/player_id_login", json={"app_id": 100067, "login_id": str(uid)}, verify=False, timeout=5).json()
                    oId = openid_res.get("open_id")
            except: pass

        if not oId:
            return '<span class="error">❌ Failed to extract Open ID. Token is likely invalid or expired.</span>'

        lines.append(f'<span class="success">✅ Open ID Extracted: {oId}</span>')
        lines.append('<span class="info">🔓 Bypassing MajorLogin via Protobufs...</span>')

        platforms = [8, 3, 4, 6]
        for p_type in platforms:
            pl = build_majorlogin(token, oId, p_type)
            try:
                mLhDr = {
                    "User-Agent": "Dalvik/2.1.0 (Linux; U; Android 11; SM-S908E Build/TP1A.220624.014)",
                    "Connection": "Keep-Alive", "Accept-Encoding": "gzip",
                    "Content-Type": "application/octet-stream", "Expect": "100-continue",
                    "X-GA": "v1 1", "X-Unity-Version": "2018.4.11f1", "ReleaseVersion": "OB54"
                }
                x = requests.post("https://loginbp.ggpolarbear.com/MajorLogin", headers=mLhDr, data=pl, timeout=10, verify=False)
                if x.status_code == 200:
                    res = mLrPb.MajorLoginRes()
                    try: res.ParseFromString(dec(x.content))
                    except: res.ParseFromString(x.content)
                    if res.token:
                        jwt_token = res.token
                        lines.append(f'<span class="success">✅ JWT Generated via Platform ID {p_type}!</span>')
                        break
            except: continue

        if not jwt_token:
            return '\n'.join(lines) + '\n<span class="error">❌ MajorLogin failed across all platforms.</span>'

    # Decode JWT for player info - name is already decoded in JWT
    try:
        payload_b64 = jwt_token.split('.')[1]
        payload_b64 += "=" * ((4 - len(payload_b64) % 4) % 4)
        decoded = json.loads(base64.urlsafe_b64decode(payload_b64).decode('utf-8'))
        # JWT nickname is typically already decoded, but safe to decode again
        name = urllib.parse.unquote(decoded.get("nickname", "Unknown"))
        uid = decoded.get("account_id", "Unknown")
        region = decoded.get("lock_region", "Unknown")
        p_id = decoded.get("external_type", 0)
        platform = PLATFORM_MAP.get(p_id, f"Unknown ({p_id})")

        lines.append(f'\n<span class="highlight">≡ Player Info</span>')
        lines.append(f'  ● Account Name: {name}')
        lines.append(f'  ● Account ID  : {uid}')
        lines.append(f'  ● Platform    : {platform}')
        lines.append(f'  ● Region      : {region}\n')
    except: pass

    # Fetch login history
    lines.append('<span class="info">📜 Fetching Login History Records...</span>\n')
    hH = {
        "Expect": "100-continue", "Authorization": f"Bearer {jwt_token}",
        "X-Unity-Version": "2018.4.11f1", "X-GA": "v1 1", "ReleaseVersion": "OB54",
        "Content-Type": "application/x-www-form-urlencoded",
        "User-Agent": "Dalvik/2.1.0 (Linux; U; Android 9; G011A Build/PI)",
        "Host": "client.ind.freefiremobile.com", "Connection": "close"
    }

    try:
        r = requests.post("https://client.ind.freefiremobile.com/GetLoginHistory", headers=hH, data=enc(b""), timeout=15, verify=False)
        if r.status_code != 200:
            lines.append(f'<span class="error">❌ History Request Failed: HTTP {r.status_code}</span>')
            return '\n'.join(lines)

        try: d = dec(r.content)
        except: d = r.content

        records = parse_history_protobuf(d)

        if not records:
            lines.append('<span class="warn">⚠️ No login history records found.</span>')
        else:
            lines.append(f'<span class="highlight">≡ Login History ({len(records)} records)</span>')
            for i, rec in enumerate(records, 1):
                ts_raw = rec.get('ts', 0)
                try: date_str = datetime.fromtimestamp(ts_raw).strftime('%Y-%m-%d %H:%M:%S')
                except: date_str = "Invalid Format"
                dev = rec.get('dev', 'Unknown Device')
                arch = rec.get('arch', 'Unknown Architecture')
                ram = rec.get('ram', 0)

                lines.append(f'\n  ● Record #{i}')
                lines.append(f'    ● Timestamp: {ts_raw} ({date_str})')
                lines.append(f'    ● Device   : {dev}')
                lines.append(f'    ● Arch     : {arch}')
                lines.append(f'    ● RAM      : {ram} MB')

    except Exception as e:
        lines.append(f'<span class="error">❌ Error: {str(e)}</span>')

    return '\n'.join(lines)

def check_bound_accounts(access_token):
    lines = []
    lines.append('<span class="info">🔗 Fetching platform bind data...</span>\n')

    url = "https://100067.connect.garena.com/bind/app/platform/info/get"
    params = {"access_token": access_token}
    headers = {
        "User-Agent": "GarenaMSDK/4.0.19P9(Redmi Note 5 ;Android 9;en;US;)",
        "Connection": "Keep-Alive",
        "Accept-Encoding": "gzip"
    }

    PLATFORM_MAP = {
        1: "Garena", 3: "Facebook", 4: "Guest", 5: "VK",
        6: "Huawei", 7: "Apple", 8: "Google", 10: "GameCenter / Line",
        11: "X (Twitter)", 13: "Apple ID", 28: "Line", 35: "TikTok"
    }

    try:
        response = requests.get(url, params=params, headers=headers, timeout=10)
        if response.status_code != 200:
            lines.append(f'<span class="error">❌ HTTP {response.status_code}</span>')
            return '\n'.join(lines)

        d = response.json()
        bounded = d.get("bounded_accounts", [])
        available = d.get("available_platforms", [])

        lines.append(f'<span class="highlight">≡ BOUND ACCOUNTS</span>')
        if not bounded:
            lines.append('  ● No third-party platforms are currently bound.')
        else:
            for p_id in bounded:
                p_name = PLATFORM_MAP.get(p_id, f"Unknown ({p_id})")
                lines.append(f'  ● {p_name}')

        lines.append(f'\n<span class="highlight">≡ AVAILABLE PLATFORMS</span>')
        if not available:
            lines.append('  ● None')
        else:
            for p_id in available:
                p_name = PLATFORM_MAP.get(p_id, f"Unknown ({p_id})")
                lines.append(f'  ● {p_name}')

    except Exception as e:
        lines.append(f'<span class="error">❌ Error: {str(e)}</span>')

    return '\n'.join(lines)

# ─── Flask Routes ───

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api', methods=['POST'])
def api():
    data = request.json
    action = data.get('action')

    try:
        if action == 'bindInfo':
            token = data.get('token', '')
            if not token:
                return jsonify({'error': 'Access token is required'})
            output = check_bind_info(token)

        elif action == 'bindEmailSend':
            token = data.get('token', '')
            email = data.get('email', '')
            if not token or not email:
                return jsonify({'error': 'Token and email are required'})
            # Just send OTP step
            headers = {"User-Agent": "GarenaMSDK/4.0.30", "Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"}
            send_url = "https://100067.connect.garena.com/game/account_security/bind:send_otp"
            send_data = {"email": email, "locale": "en_PK", "region": "PK", "app_id": "100067", "access_token": token}
            try:
                r = requests.post(send_url, headers=headers, data=send_data)
                output = format_response_text(r.text, "Send OTP")
            except Exception as e:
                output = f'<span class="error">❌ Send OTP failed: {str(e)}</span>'

        elif action == 'bindEmailFinal':
            token = data.get('token', '')
            email = data.get('email', '')
            otp = data.get('otp', '')
            sec = data.get('sec', '')
            if not token or not email or not otp or not sec:
                return jsonify({'error': 'All fields are required'})
            output = bind_email(token, email, otp, sec)

        elif action == 'unbindEmail':
            token = data.get('token', '')
            method = data.get('method', '1')
            otp = data.get('otp', '')
            sec = data.get('sec', '')
            if not token:
                return jsonify({'error': 'Access token is required'})
            output = unbind_email(token, method, otp, sec)

        elif action == 'changeBind':
            token = data.get('token', '')
            method = data.get('method', '1')
            otp = data.get('otp', '')
            sec = data.get('sec', '')
            new_email = data.get('newEmail', '')
            new_otp = data.get('newOtp', '')
            if not token or not new_email:
                return jsonify({'error': 'Token and new email are required'})
            output = change_bind_email(token, method, otp, sec, new_email, new_otp)

        elif action == 'cancelBind':
            token = data.get('token', '')
            if not token:
                return jsonify({'error': 'Access token is required'})
            output = cancel_bind_request(token)

        elif action == 'eatToToken':
            eat = data.get('eat', '')
            if not eat:
                return jsonify({'error': 'EAT input is required'})
            output = eat_to_access_token(eat)

        elif action == 'revokeToken':
            token = data.get('token', '')
            if not token:
                return jsonify({'error': 'Access token is required'})
            output = revoke_access_token(token)

        elif action == 'loginHistory':
            token = data.get('token', '')
            if not token:
                return jsonify({'error': 'Token is required'})
            output = get_login_history(token)

        elif action == 'boundAccounts':
            token = data.get('token', '')
            if not token:
                return jsonify({'error': 'Access token is required'})
            output = check_bound_accounts(token)

        else:
            return jsonify({'error': f'Unknown action: {action}'})

        return jsonify({'output': output})

    except Exception as e:
        return jsonify({'error': str(e)})

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)