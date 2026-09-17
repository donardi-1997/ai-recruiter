from getpass import getpass

from .credential_store import write_agent_token


def main() -> None:
    raw = getpass("Pegue el token del ASIATI Resume Agent: ").strip()
    if len(raw) < 32:
        raise SystemExit("Token invalido: use la credencial emitida por el administrador.")
    write_agent_token(raw)
    print("Credencial guardada en Windows Credential Manager.")


if __name__ == "__main__":
    main()
