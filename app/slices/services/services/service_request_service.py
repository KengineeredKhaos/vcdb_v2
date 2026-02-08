"""
Service request service - Business logic layer.

Demonstrates inter-slice communication through extension contracts.

IMPORTANT:
- NO direct imports from other slices (e.g., from app.slices.users...)
- Use extension contracts for inter-slice communication
- Services only flush, never commit/rollback
- Services receive request_id, never generate it
"""
import logging
from typing import Optional
from app.lib.database.session import DatabaseSession
from app.lib.middleware.correlation import validate_request_id
from app.slices.services.models.service_request import ServiceRequest
# Correct way: Import through extension contract
from app.extensions.contract.user_contract import user_contract

logger = logging.getLogger(__name__)


class ServiceRequestService:
    """Service request business logic"""
    
    def create(self, db: DatabaseSession, request_id: str, user_id: int,
               service_type: str, description: str) -> ServiceRequest:
        """
        Create a new service request.
        
        Validates that the user is a veteran before creating the request.
        Uses extension contract to access user data (NO direct slice imports).
        
        Args:
            db: Database session
            request_id: Correlation ID
            user_id: User requesting the service
            service_type: Type of service requested
            description: Service description
            
        Returns:
            Created service request
            
        Raises:
            ValueError: If user is not a veteran
        """
        validate_request_id(request_id)
        
        logger.info(f"Creating service request for user {user_id}", 
                   extra={"request_id": request_id})
        
        # Use extension contract to verify veteran status
        # This is the ONLY correct way to access user data from another slice
        is_veteran = user_contract.verify_veteran_status(db, request_id, user_id)
        
        if not is_veteran:
            raise ValueError(f"User {user_id} is not a verified veteran")
        
        # Business logic
        service_request = ServiceRequest(
            user_id=user_id,
            service_type=service_type,
            description=description,
            status="pending"
        )
        
        db.add(service_request)
        db.flush()  # Service only flushes
        
        logger.info(f"Service request created: {service_request}", 
                   extra={"request_id": request_id})
        return service_request


# Single instance
service_request_service = ServiceRequestService()
