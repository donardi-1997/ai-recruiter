import boto3
import os

from dotenv import load_dotenv
from botocore.exceptions import ClientError
from pydantic import BaseModel


load_dotenv()


# ============================================================
# MODELS
# ============================================================

class LoginRequest(BaseModel):
    email: str
    password: str


class SignupRequest(BaseModel):
    email: str
    password: str


class ConfirmRequest(BaseModel):
    email: str
    confirmation_code: str


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
# CREATE USER
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
# LOGIN USER
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

            "access_token":
                auth.get(
                    "AccessToken"
                ),

            "id_token":
                auth.get(
                    "IdToken"
                ),

            "refresh_token":
                auth.get(
                    "RefreshToken"
                ),

            "expires_in":
                auth.get(
                    "ExpiresIn"
                )
        }


    except ClientError as e:


        error_code = e.response["Error"].get(
            "Code",
            ""
        )


        print(
            "COGNITO LOGIN ERROR:",
            error_code,
            e.response["Error"].get("Message")
        )


        if error_code in [
            "NotAuthorizedException",
            "UserNotFoundException"
        ]:

            return {
                "error":
                    "Correo o contraseña incorrectos."
            }


        if error_code == "UserNotConfirmedException":

            return {
                "error":
                    "Tu cuenta todavía no ha sido confirmada."
            }


        return {
            "error":
                "No fue posible iniciar sesión."
        }


def refresh_user(refresh_token: str):
    try:
        response = cognito_client.initiate_auth(
            ClientId=COGNITO_CLIENT_ID,
            AuthFlow="REFRESH_TOKEN_AUTH",
            AuthParameters={"REFRESH_TOKEN": refresh_token},
        )
        auth = response.get("AuthenticationResult", {})
        return {
            "access_token": auth.get("AccessToken"),
            "id_token": auth.get("IdToken"),
            "expires_in": auth.get("ExpiresIn"),
        }
    except ClientError:
        return {"error": "La sesión expiró. Inicia sesión nuevamente."}



# ============================================================
# CONFIRM USER
# ============================================================

def confirm_user(
    email: str,
    confirmation_code: str
):

    try:

        cognito_client.confirm_sign_up(

            ClientId=COGNITO_CLIENT_ID,

            Username=email,

            ConfirmationCode=confirmation_code

        )


        return {
            "message":
                "Cuenta confirmada correctamente."
        }


    except ClientError as e:

        return {
            "error":
                e.response["Error"]["Message"]
        }