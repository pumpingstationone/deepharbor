import requests
import time
from dataclasses import dataclass

@dataclass
class UnifiUser():
    first_name: str
    last_name: str
    user_email: str
    employee_number: str
    onboard_time: int


#TODO: fix verify=False everywhere
# we need to pin the certs

class UnifiAccessAPI():
    def __init__(self, hostname: str, api_key: str):
        self._hostname = hostname
        self._apikey = api_key
        self._auth_header = {"Authorization": f"Bearer {api_key}"}

        self._api_url_enroll = self._hostname + "api/v1/developer/credentials/nfc_cards/sessions"
        self._api_url_users = self._hostname + "api/v1/developer/users"
        self._api_url_user_groups = self._hostname + "api/v1/developer/user_groups"

        self._code_success = "SUCCESS"
        self._code_nfc_empty = "CODE_CREDS_NFC_READ_POLL_TOKEN_EMPTY"

    def begin_enroll_session(self, reader_id: str):
        body = {"device_id": reader_id}

        r = requests.post(self._api_url_enroll, json=body, headers=self._auth_header, verify=False)
        resp = r.json()
        print(self._api_url_enroll)
        print(resp)
        code = resp.get("code")
        if (code == self._code_success):
            data = resp.get("data")
            session_id = data.get("session_id")
            return session_id
        else:
            raise RuntimeError(f"API did not return success! Instead got {code}")

    def check_enroll_session(self, session_id: str):
        r = requests.get(f"{self._api_url_enroll}/{session_id}", headers=self._auth_header, verify=False)
        resp = r.json()
        code = resp.get("code")
        if (code == self._code_success):
            data = resp.get("data")
            id = data.get("id")
            token = data.get("token")
            return id, token
        elif (code == self._code_nfc_empty):
            return None, None
        else:
            raise RuntimeError("API did not return success!")

    def create_user(self, user_obj: UnifiUser):
        body = {
            "first_name": user_obj.first_name,
            "last_name": user_obj.last_name,
            "user_email": user_obj.user_email,
            "employee_number": user_obj.employee_number,
            # "onboard_time": user_obj.onboard_time,
        }
        
        r = requests.post(self._api_url_users, json=body, headers=self._auth_header, verify=False)
        resp = r.json()
        code = resp.get("code")
        if (code == self._code_success):
            data = resp.get("data")
            id = data.get("id")
            return id
        elif (code == self._code_nfc_empty):
            return None, None
        else:
            raise RuntimeError("API did not return success!")

    def assign_group(self, user_id: str, group_id: str):
        # /api/v1/developer/user_groups/:id/users
        body = [user_id]
        r = requests.post(f"{self._api_url_user_groups}/{group_id}/users", json=body, headers=self._auth_header, verify=False)
        resp = r.json()
        code = resp.get("code")
        if (code == self._code_success):
            data = resp.get("data")
            return
        else:
            raise RuntimeError("API did not return success!")

    def unassign_group(self, user_id: str, group_id: str):
        # /api/v1/developer/user_groups/:id/users/delete
        body = [user_id]
        r = requests.post(f"{self._api_url_user_groups}/{group_id}/users/delete", json=body, headers=self._auth_header, verify=False)
        resp = r.json()
        print(resp)
        code = resp.get("code")
        if (code == self._code_success):
            data = resp.get("data")
            return
        else:
            raise RuntimeError("API did not return success!")

    def assign_credential(self, user_id: str, token: str):
        # PUT /api/v1/developer/users/:id/nfc_cards
        body = {
            "token": token
        }
        r = requests.post(f"{self._api_url_users}/{user_id}/nfc_cards", json=body, headers=self._auth_header, verify=False)
        resp = r.json()
        print(resp)
        code = resp.get("code")
        if (code == self._code_success):
            data = resp.get("data")
            return
        else:
            raise RuntimeError("API did not return success!")

    def unassign_credential(self, user_id: str, token: str):
        # PUT /api/v1/developer/users/:id/nfc_cards/delete
        body = {
            "token": token
        }
        r = requests.put(f"{self._api_url_users}/{user_id}/nfc_cards/delete", json=body, headers=self._auth_header, verify=False)
        resp = r.json()
        print(resp)
        code = resp.get("code")
        if (code == self._code_success):
            return
        else:
            raise RuntimeError("API did not return success!")
