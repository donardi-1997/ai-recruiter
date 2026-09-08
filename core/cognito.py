import boto3

from botocore.exceptions import ClientError

from core.config import COGNITO_CLIENT_ID, AWS_REGION

# ============================================================
# COGNITO CLIENT
# ============================================================

cognito_client = boto3.client(
    "cognito-idp",
    region_name=AWS_REGION,
)


# ============================================================
# CREATE USER
# ============================================================


def create_user(email: str, password: str):
    try:
        response = cognito_client.sign_up(
            ClientId=COGNITO_CLIENT_ID,
            Username=email,
            Password=password,
            UserAttributes=[{"Name": "email", "Value": email}],
        )
        return {
            "message": "Usuario creado correctamente. Revisa tu correo para confirmar la cuenta.",
            "user_sub": response.get("UserSub"),
            "confirmed": response.get("UserConfirmed", False),
        }
    except ClientError as e:
        return {"error": e.response["Error"]["Message"]}


# ============================================================
# LOGIN USER
# ============================================================


def login_user(email: str, password: str):
    try:
        response = cognito_client.initiate_auth(
            ClientId=COGNITO_CLIENT_ID,
            AuthFlow="USER_PASSWORD_AUTH",
            AuthParameters={"USERNAME": email, "PASSWORD": password},
        )
        auth = response.get("AuthenticationResult", {})
        return {
            "access_token": auth.get("AccessToken"),
            "id_token": auth.get("IdToken"),
            "refresh_token": auth.get("RefreshToken"),
            "expires_in": auth.get("ExpiresIn"),
        }
    except ClientError as e:
        error_code = e.response["Error"].get("Code", "")
        print(
            "COGNITO LOGIN ERROR:",
            error_code,
            e.response["Error"].get("Message"),
        )
        if error_code in ["NotAuthorizedException", "UserNotFoundException"]:
            return {"error": "Correo o contrase\u00f1a incorrectos."}
        if error_code == "UserNotConfirmedException":
            return {"error": "Tu cuenta todav\u00eda no ha sido confirmada."}
        return {"error": "No fue posible iniciar sesi\u00f3n."}


# ============================================================
# REFRESH USER
# ============================================================


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
        return {"error": "La sesi\u00f3n expir\u00f3. Inicia sesi\u00f3n nuevamente."}


# ============================================================
# CONFIRM USER
# ============================================================


def confirm_user(email: str, confirmation_code: str):
    try:
        cognito_client.confirm_sign_up(
            ClientId=COGNITO_CLIENT_ID,
            Username=email,
            ConfirmationCode=confirmation_code,
        )
        return {"message": "Cuenta confirmada correctamente."}
    except ClientError as e:
        return {"error": e.response["Error"]["Message"]}
