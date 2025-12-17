from pydantic import BaseModel

# This is for ouath2 clients
class Client(BaseModel):
    client_name: str
    hashed_password: str
    description: str | None = None
    disabled: bool | None = None
