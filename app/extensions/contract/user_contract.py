"""
User contract - Bridge for inter-slice communication.

Other slices must use this contract to access user data.
No direct imports from other slices allowed.
"""
from typing import Optional
from app.lib.database.session import DatabaseSession
from app.slices.users.models.user import User


class UserContract:
    """
    Contract for accessing user functionality from other slices.
    
    This is the ONLY way other slices should interact with user data.
    """
    
    @staticmethod
    def get_user_by_id(db: DatabaseSession, request_id: str, user_id: int) -> Optional[User]:
        """
        Get user by ID - accessible to other slices.
        
        Args:
            db: Database session
            request_id: Correlation ID
            user_id: User ID to retrieve
            
        Returns:
            User if found, None otherwise
        """
        # Import locally to avoid circular dependencies
        from app.slices.users.services.user_service import user_service
        return user_service.get_by_id(db, request_id, user_id)
    
    @staticmethod
    def verify_veteran_status(db: DatabaseSession, request_id: str, 
                              user_id: int) -> bool:
        """
        Verify if a user is a veteran.
        
        Args:
            db: Database session
            request_id: Correlation ID
            user_id: User ID to check
            
        Returns:
            True if user is a veteran, False otherwise
        """
        from app.slices.users.services.user_service import user_service
        user = user_service.get_by_id(db, request_id, user_id)
        return user is not None and user.veteran_id is not None


# Export contract instance
user_contract = UserContract()
