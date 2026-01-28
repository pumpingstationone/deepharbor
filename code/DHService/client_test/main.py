#!/usr/bin/env python3

import requests

# Replace with your actual URL
BASE_URL = "http://localhost/dh/service"


def get_access_token(username: str, password: str) -> str:
    url = f"{BASE_URL}/token"
    response = requests.post(url, data={"username": username, "password": password})
    response.raise_for_status()
    return response.json()["access_token"]


def get_current_user(access_token: str):
    url = f"{BASE_URL}/users/me/"
    headers = {"Authorization": f"Bearer {access_token}"}
    response = requests.get(url, headers=headers)
    response.raise_for_status()
    return response.json()


def get_user_items(access_token: str):
    url = f"{BASE_URL}/users/me/items/"
    headers = {"Authorization": f"Bearer {access_token}"}
    response = requests.get(url, headers=headers)
    response.raise_for_status()
    return response.json()


if __name__ == "__main__":
    username = "dev-admin-portal"
    password = "ikactyRLicKoI8VHiD9KZEwTrOIhtYjfzm1h6YUjj7M"

    # Get access token
    print("Getting access token...")
    access_token = get_access_token(username, password)
    print(f"Access Token: {access_token}")

    # Get member ID from email address
    email_address = "tachoknight@gmail.com"
    print(f"Getting member ID for email address: {email_address}...")
    url = f"{BASE_URL}/v1/member/id"
    headers = {"Authorization": f"Bearer {access_token}"}
    params = {"email_address": email_address}
    response = requests.get(url, headers=headers, params=params)
    response.raise_for_status()
    member_info = response.json()
    print(f"Member Info: {member_info}")

    # Search for a member by whatever
    url = f"{BASE_URL}/v1/member/search/"
    print(f"Searching for member 'tachoknight@gmail.com' at {url}...")
    headers = {"Authorization": f"Bearer {access_token}"}
    params = {"query": "tachoknight@gmail.com"}
    response = requests.get(url, headers=headers, params=params)
    response.raise_for_status()
    members = response.json()
    print(f"Members found: {members}")
    if not members:
        print("No members found, exiting.")
        exit(1)

    # Get the member data for the first member found
    member_id = members[0]["member_id"]
    print(f"Getting data for member ID: {member_id}...")
    url = f"{BASE_URL}/v1/member/identity/"
    params = {"member_id": member_id}
    headers = {"Authorization": f"Bearer {access_token}"}
    response = requests.get(url, headers=headers, params=params)
    response.raise_for_status()
    member_data = response.json()
    print(f"Member Data: {member_data}")

    # Get the roles for the member
    print(f"Getting roles for member ID: {member_id}...")
    url = f"{BASE_URL}/v1/member/roles/"
    params = {"member_id": member_id}
    headers = {"Authorization": f"Bearer {access_token}"}
    response = requests.get(url, headers=headers, params=params)
    response.raise_for_status()
    roles_data = response.json()
    print(f"Member Roles: {roles_data}")

    # Get all member names and email addresses
    print("Getting all member names and email addresses...")
    url = f"{BASE_URL}/v1/members/names_and_emails/"
    headers = {"Authorization": f"Bearer {access_token}"}
    response = requests.get(url, headers=headers)
    response.raise_for_status()
    names_and_emails = response.json()
    # Now go through and print each member
    for member in names_and_emails["members"]:
        print(f"Member ID: {member['member_id']}, Name: {member['first_name']} {member['last_name']}, Email: {member['primary_email_address']}")
