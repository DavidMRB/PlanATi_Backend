from __future__ import annotations

from uuid import uuid4

import boto3
from botocore.exceptions import BotoCoreError, ClientError
from fastapi import HTTPException, status

from app.core.config import settings


class R2StorageService:
    def __init__(self) -> None:
        self.endpoint_url = settings.r2_endpoint_url
        self.bucket_name = settings.r2_bucket_name
        self.access_key_id = settings.r2_access_key_id
        self.secret_access_key = settings.r2_secret_access_key
        self.public_base_url = settings.r2_public_base_url.rstrip("/")

    def is_configured(self) -> bool:
        return bool(self.access_key_id and self.secret_access_key and self.endpoint_url and self.bucket_name)

    def get_client(self):
        return boto3.client(
            "s3",
            endpoint_url=self.endpoint_url,
            aws_access_key_id=self.access_key_id,
            aws_secret_access_key=self.secret_access_key,
            region_name="auto",
        )

    def create_presigned_upload_url(self, folder: str, file_extension: str) -> dict[str, str]:
        if not self.is_configured():
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Cloudflare R2 no está configurado. Define las credenciales del bucket.",
            )

        object_key = f"{folder}/{uuid4()}{file_extension}"
        try:
            client = self.get_client()
            upload_url = client.generate_presigned_url(
                "put_object",
                Params={"Bucket": self.bucket_name, "Key": object_key, "ContentType": "image/jpeg"},
                ExpiresIn=600,
                HttpMethod="PUT",
            )
            public_url = f"{self.public_base_url}/{object_key}"
            return {"upload_url": upload_url, "public_url": public_url, "key": object_key}
        except (BotoCoreError, ClientError) as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="No se pudo generar la URL de carga para R2.",
            ) from exc


storage_service = R2StorageService()


def build_review_upload_url(file_extension: str = ".jpg") -> dict[str, str]:
    return storage_service.create_presigned_upload_url("reviews", file_extension)
