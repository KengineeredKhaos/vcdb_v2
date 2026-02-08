"""
User routes - Entry point layer.

IMPORTANT:
- Routes own the transaction scope (commit/rollback)
- Routes get or generate request_id at entry point
- Routes coordinate service calls and manage transactions
"""
import logging
from typing import Dict, Any
from app.lib.database.session import get_db_session
from app.lib.middleware.correlation import get_or_create_request_id
from app.slices.users.services.user_service import user_service

logger = logging.getLogger(__name__)


def create_user_route(headers: Dict[str, str], name: str, email: str, 
                      veteran_id: str = None) -> Dict[str, Any]:
    """
    Create user route - demonstrates proper transaction ownership.
    
    Args:
        headers: Request headers (contains request_id)
        name: User name
        email: User email
        veteran_id: Optional veteran ID
        
    Returns:
        Response dict with user data or error
    """
    # Route gets or generates request_id at entry point
    request_id = get_or_create_request_id(headers)
    
    # Route manages the database session and transaction
    with get_db_session() as db:
        try:
            # Call service with request_id
            user = user_service.create(
                db=db,
                request_id=request_id,
                name=name,
                email=email,
                veteran_id=veteran_id
            )
            
            # Route commits the transaction
            db.commit()
            
            return {
                "status": "success",
                "request_id": request_id,
                "data": {
                    "id": user.id,
                    "name": user.name,
                    "email": user.email,
                    "veteran_id": user.veteran_id
                }
            }
            
        except Exception as e:
            # Route rolls back on error
            db.rollback()
            logger.error(f"Error creating user: {e}", extra={"request_id": request_id})
            
            return {
                "status": "error",
                "request_id": request_id,
                "error": str(e)
            }


def get_user_route(headers: Dict[str, str], user_id: int) -> Dict[str, Any]:
    """
    Get user by ID route.
    
    Args:
        headers: Request headers
        user_id: User ID to retrieve
        
    Returns:
        Response dict with user data or error
    """
    request_id = get_or_create_request_id(headers)
    
    with get_db_session() as db:
        try:
            user = user_service.get_by_id(db, request_id, user_id)
            
            # Read operations can still commit (no-op in this case)
            db.commit()
            
            if user:
                return {
                    "status": "success",
                    "request_id": request_id,
                    "data": {
                        "id": user.id,
                        "name": user.name,
                        "email": user.email,
                        "veteran_id": user.veteran_id
                    }
                }
            else:
                return {
                    "status": "not_found",
                    "request_id": request_id,
                    "error": f"User {user_id} not found"
                }
                
        except Exception as e:
            db.rollback()
            logger.error(f"Error fetching user: {e}", extra={"request_id": request_id})
            
            return {
                "status": "error",
                "request_id": request_id,
                "error": str(e)
            }
