"""
User service - Business logic layer.

IMPORTANT: 
- Services only flush, never commit/rollback
- Services receive request_id as parameter, never generate it
- Services perform business logic and prepare data changes
"""
import logging
from typing import Optional
from app.lib.database.session import DatabaseSession
from app.lib.middleware.correlation import validate_request_id
from app.slices.users.models.user import User

logger = logging.getLogger(__name__)


class UserService:
    """User business logic service"""
    
    def create(self, db: DatabaseSession, request_id: str, name: str, email: str, 
               veteran_id: Optional[str] = None) -> User:
        """
        Create a new user.
        
        Args:
            db: Database session (managed by route)
            request_id: Correlation ID (provided by route, never generated here)
            name: User name
            email: User email
            veteran_id: Optional veteran ID
            
        Returns:
            Created user
        """
        # Validate correlation ID is present
        validate_request_id(request_id)
        
        # Log with correlation ID
        logger.info(f"Creating user: {email}", extra={"request_id": request_id})
        
        # Business logic
        user = User(name=name, email=email, veteran_id=veteran_id)
        
        # Add to session
        db.add(user)
        
        # Service only flushes - route owns commit/rollback
        db.flush()
        
        logger.info(f"User created: {user}", extra={"request_id": request_id})
        return user
    
    def get_by_id(self, db: DatabaseSession, request_id: str, user_id: int) -> Optional[User]:
        """
        Get user by ID.
        
        Args:
            db: Database session
            request_id: Correlation ID
            user_id: User ID to retrieve
            
        Returns:
            User if found, None otherwise
            
        Note:
            This is a stub implementation for demonstration purposes.
            In production, this would query the database.
        """
        validate_request_id(request_id)
        logger.info(f"Fetching user: {user_id}", extra={"request_id": request_id})
        
        # STUB: In real implementation, would query database like:
        # return db.query(User).filter(User.id == user_id).first()
        return None


# Single instance
user_service = UserService()
