"""
Транспортный слой модуля меню.
Техническая валидация, сборка слоёв и перевод исключений в HTTP-статусы.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.core.dependencies import require_role
from app.database import get_db
from app.exceptions import NotFoundError
from app.schemas import MenuItemCreate, MenuItemUpdate
from app.modules.menu.repository import get_menu_repository
from app.modules.menu.service import MenuService

router = APIRouter()


@router.get("/items")
def get_menu_items(db: Session = Depends(get_db)):
    # Меню не секрет: смотреть его можно без токена.
    service = MenuService(get_menu_repository(db))
    return service.get_menu()


@router.get("/categories/{category_id}")
def get_menu_category(category_id: int, db: Session = Depends(get_db)):
    # Категория с блюдами, тоже без токена.
    service = MenuService(get_menu_repository(db))
    try:
        return service.get_category(category_id)
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/items")
def create_menu_item(
    payload: MenuItemCreate,
    # Менять меню могут только повар и администратор.
    current_user=Depends(require_role("admin", "cook")),
    db: Session = Depends(get_db),
):
    # Техническая валидация цены и названия.
    if payload.price <= 0:
        raise HTTPException(
            status_code=400,
            detail="Цена должна быть положительной",
        )

    if len(payload.name) < 2:
        raise HTTPException(
            status_code=400,
            detail="Название блюда слишком короткое",
        )

    service = MenuService(get_menu_repository(db))

    try:
        item_id = service.create_item(
            name=payload.name,
            price=payload.price,
            category_id=payload.category_id,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))

    return {"status": "success", "item_id": item_id}


@router.patch("/items/{item_id}")
def update_menu_item(
    item_id: int,
    payload: MenuItemUpdate,
    current_user=Depends(require_role("admin", "cook")),
    db: Session = Depends(get_db),
):
    # Техническая валидация нового значения цены.
    if payload.price is not None and payload.price <= 0:
        raise HTTPException(
            status_code=400,
            detail="Цена должна быть положительной",
        )

    service = MenuService(get_menu_repository(db))

    try:
        item_id = service.update_item(
            item_id=item_id,
            name=payload.name,
            price=payload.price,
            is_available=payload.is_available,
            category_id=payload.category_id,
        )
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))

    return {"status": "success", "item_id": item_id}
