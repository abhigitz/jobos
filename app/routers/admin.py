"""Admin-only endpoints."""
import os
from io import BytesIO

from botocore.exceptions import ClientError
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from app.dependencies import get_current_user
from app.models.user import User

router = APIRouter(tags=["admin"])

R2_ENDPOINT_URL = "R2_ENDPOINT_URL"
R2_ACCESS_KEY_ID = "R2_ACCESS_KEY_ID"
R2_SECRET_ACCESS_KEY = "R2_SECRET_ACCESS_KEY"
R2_BUCKET_NAME = "R2_BUCKET_NAME"


def _get_r2_client():
    """Get R2 client. Raises if not configured."""
    import boto3
    from botocore.config import Config

    if not all(os.environ.get(k) for k in [R2_ENDPOINT_URL, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, R2_BUCKET_NAME]):
        raise HTTPException(status_code=503, detail="R2 backup not configured")
    return boto3.client(
        "s3",
        endpoint_url=os.environ.get(R2_ENDPOINT_URL),
        aws_access_key_id=os.environ.get(R2_ACCESS_KEY_ID),
        aws_secret_access_key=os.environ.get(R2_SECRET_ACCESS_KEY),
        config=Config(signature_version="s3v4"),
        region_name="auto",
    )


@router.get("/backup/list")
async def list_backups(
    current_user: User = Depends(get_current_user),
):
    """List all backup files in R2 bucket."""
    client = _get_r2_client()
    bucket = os.environ.get(R2_BUCKET_NAME)
    response = client.list_objects_v2(Bucket=bucket)
    objects = response.get("Contents", [])

    result = []
    for obj in objects:
        key = obj.get("Key", "")
        if not key.endswith(".json.gz"):
            continue
        result.append({
            "filename": key,
            "size_kb": round(obj.get("Size", 0) / 1024, 1),
            "last_modified": obj.get("LastModified", "").isoformat() if obj.get("LastModified") else "",
        })
    result.sort(key=lambda x: x["filename"], reverse=True)
    return result


@router.get("/backup/download/{filename}")
async def download_backup(
    filename: str,
    current_user: User = Depends(get_current_user),
):
    """Download a backup file from R2."""
    if ".." in filename or "/" in filename or not filename.endswith(".json.gz"):
        raise HTTPException(status_code=400, detail="Invalid filename")

    client = _get_r2_client()
    bucket = os.environ.get(R2_BUCKET_NAME)
    try:
        response = client.get_object(Bucket=bucket, Key=filename)
        body = response["Body"].read()
    except ClientError as e:
        if e.response.get("Error", {}).get("Code") == "NoSuchKey":
            raise HTTPException(status_code=404, detail="Backup not found")
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    return StreamingResponse(
        BytesIO(body),
        media_type="application/gzip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/backup/trigger")
async def trigger_backup(
    current_user: User = Depends(get_current_user),
):
    """Manually trigger database backup to R2."""
    from app.tasks.db_backup import backup_database

    await backup_database()
    return {"status": "success", "message": "Backup triggered"}
