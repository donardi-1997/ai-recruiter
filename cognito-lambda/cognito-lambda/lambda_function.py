def lambda_handler(event, context):

    print("Cognito Pre Sign-up event:")
    print(event)

    # Confirmar usuario automáticamente
    event["response"]["autoConfirmUser"] = True

    # Confirmar email automáticamente
    event["response"]["autoVerifyEmail"] = True

    return event