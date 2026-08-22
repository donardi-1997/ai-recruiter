import boto3
import os

from dotenv import load_dotenv
from botocore.exceptions import ClientError


load_dotenv()


# ============================================================
# COGNITO CLIENT
# ============================================================

cognito_client = boto3.client(
    "cognito-idp",
    region_name=os.getenv(
        "AWS_REGION",
        "us-east-2"
    )
)


COGNITO_CLIENT_ID = os.getenv(
    "COGNITO_CLIENT_ID"
)


print(
    "AUTH COGNITO CLIENT:",
    COGNITO_CLIENT_ID
)


# ============================================================
# CREATE USER - COGNITO SIGN UP
# ============================================================

def create_user(
    email: str,
    password: str
):

    try:

        response = cognito_client.sign_up(
            ClientId=COGNITO_CLIENT_ID,

            Username=email,

            Password=password,

            UserAttributes=[
                {
                    "Name": "email",
                    "Value": email
                }
            ]
        )


        return {
            "message":
                "Usuario creado correctamente. Revisa tu correo para confirmar la cuenta.",

            "user_sub":
                response.get(
                    "UserSub"
                ),

            "confirmed":
                response.get(
                    "UserConfirmed",
                    False
                )
        }


    except ClientError as e:

        return {
            "error":
                e.response["Error"]["Message"]
        }

# ============================================================
# LOGIN USER - COGNITO AUTHENTICATION
# ============================================================

def login_user(
    email: str,
    password: str
):

    try:

        response = cognito_client.initiate_auth(
            ClientId=COGNITO_CLIENT_ID,

            AuthFlow="USER_PASSWORD_AUTH",

            AuthParameters={
                "USERNAME": email,
                "PASSWORD": password
            }
        )


        auth = response.get(
            "AuthenticationResult",
            {}
        )


        return {
            "access_token": auth.get(
                "AccessToken"
            ),

            "id_token": auth.get(
                "IdToken"
            ),

            "refresh_token": auth.get(
                "RefreshToken"
            ),

            "expires_in": auth.get(
                "ExpiresIn"
            )
        }


    except ClientError as e:

        return {
            "error":
                e.response["Error"]["Message"]
        }