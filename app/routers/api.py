from fastapi import APIRouter

router = APIRouter()


@router.get("/hello")
async def hello_world():
    """Simple hello world API endpoint"""
    return {"message": "Hello World from API!"}