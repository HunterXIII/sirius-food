"""
Pydantic-схемы для валидации входных и выходных данных.
"""
from pydantic import BaseModel, ConfigDict, EmailStr


class UserCreate(BaseModel):
    email: EmailStr
    password: str
    phone: str | None = None


class UserResponse(BaseModel):
    id: int
    email: str
    balance: float

    model_config = ConfigDict(from_attributes=True)


class MenuItemCreate(BaseModel):
    name: str
    price: float
    category_id: int | None = None


class MenuItemUpdate(BaseModel):
    name: str | None = None
    price: float | None = None
    is_available: bool | None = None
    category_id: int | None = None


class OrderCreate(BaseModel):
    # user_id нет: кто делает заказ, сервер узнаёт из токена.
    item_id: int
    quantity: int


class OrderResponse(BaseModel):
    id: int
    user_id: int
    item_id: int
    quantity: int
    status: str

    model_config = ConfigDict(from_attributes=True)


class DeliveryAssign(BaseModel):
    order_id: int
    courier_id: int


class DeliveryResponse(BaseModel):
    id: int
    order_id: int
    courier_id: int
    status: str

    model_config = ConfigDict(from_attributes=True)


class RoleUpdate(BaseModel):
    role: str
