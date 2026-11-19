from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_user, get_db
from app.models.user import User
from app.schemas.common import Page
from app.schemas.notification import NotificationResponse, UnreadCountResponse
from app.services.notification_service import (
    NotificationNotFoundError,
    count_unread,
    delete_notification,
    list_notifications,
    mark_all_read,
    mark_read,
)

# Cualquier rol y estado de cuenta: un restaurante PENDING debe poder ver que fue aprobado.
router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("", response_model=Page[NotificationResponse])
async def get_notifications(
    unread_only: bool = Query(default=False),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=50),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> Page[NotificationResponse]:
    items, total = await list_notifications(
        session, current_user.id, unread_only=unread_only, skip=skip, limit=limit
    )
    return Page[NotificationResponse](
        items=[NotificationResponse.model_validate(item) for item in items],
        total=total,
        skip=skip,
        limit=limit,
    )


@router.get("/unread-count", response_model=UnreadCountResponse)
async def get_unread_count(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> UnreadCountResponse:
    """Consulta barata para el polling de la campana."""
    return UnreadCountResponse(count=await count_unread(session, current_user.id))


@router.post("/read-all", status_code=status.HTTP_204_NO_CONTENT)
async def read_all_notifications(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> None:
    await mark_all_read(session, current_user.id)


@router.post("/{notification_id}/read", status_code=status.HTTP_204_NO_CONTENT)
async def read_notification(
    notification_id: int,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> None:
    try:
        await mark_read(session, current_user.id, notification_id)
    except NotificationNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error


@router.delete("/{notification_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_notification(
    notification_id: int,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> None:
    try:
        await delete_notification(session, current_user.id, notification_id)
    except NotificationNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
