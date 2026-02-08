"""
Tests to validate VCDB Ethos architecture compliance.

These tests ensure:
1. Services only flush, never commit/rollback
2. request_id is mandatory
3. Services never generate request_id
4. Inter-slice communication goes through contracts
"""
import pytest
from app.lib.database.session import DatabaseSession
from app.lib.middleware.correlation import validate_request_id, get_or_create_request_id
from app.slices.users.services.user_service import user_service
from app.slices.users.routes.user_routes import create_user_route
from app.extensions.contract.user_contract import user_contract


class TestCorrelationIDCompliance:
    """Test that correlation IDs are handled correctly"""
    
    def test_validate_request_id_with_valid_id(self):
        """Valid request_id should not raise error"""
        validate_request_id("valid-request-id")
    
    def test_validate_request_id_with_none(self):
        """None request_id should raise ValueError"""
        with pytest.raises(ValueError, match="request_id is mandatory"):
            validate_request_id(None)
    
    def test_validate_request_id_with_empty_string(self):
        """Empty request_id should raise ValueError"""
        with pytest.raises(ValueError, match="request_id is mandatory"):
            validate_request_id("")
    
    def test_validate_request_id_with_invalid_type(self):
        """Non-string request_id should raise ValueError"""
        with pytest.raises(ValueError, match="must be a string"):
            validate_request_id(123)
    
    def test_get_or_create_request_id_from_headers(self):
        """Should use request_id from headers when provided"""
        headers = {"x-request-id": "client-provided-id"}
        request_id = get_or_create_request_id(headers)
        assert request_id == "client-provided-id"
    
    def test_get_or_create_request_id_generates_when_missing(self):
        """Should generate request_id when not in headers"""
        headers = {}
        request_id = get_or_create_request_id(headers)
        assert request_id is not None
        assert len(request_id) > 0


class TestServiceFlushOnlyCompliance:
    """Test that services only flush, never commit/rollback"""
    
    def test_service_calls_flush_not_commit(self):
        """Service should call flush but not commit"""
        db = DatabaseSession()
        request_id = "test-request-id"
        
        # Create user through service
        user = user_service.create(db, request_id, "Test User", "test@example.com")
        
        # Session should NOT be committed by service
        assert not db._committed
        assert user is not None
    
    def test_route_commits_transaction(self):
        """Route should commit the transaction"""
        headers = {"x-request-id": "test-request-id"}
        
        # Call route (which should commit)
        result = create_user_route(headers, "Test User", "test@example.com")
        
        # Route should return success
        assert result["status"] == "success"
        assert result["request_id"] == "test-request-id"


class TestServiceRequestIDCompliance:
    """Test that services receive request_id and never generate it"""
    
    def test_service_requires_request_id_parameter(self):
        """Service methods should require request_id parameter"""
        import inspect
        
        # Check user_service.create signature
        sig = inspect.signature(user_service.create)
        params = list(sig.parameters.keys())
        
        assert "request_id" in params, "Service must accept request_id parameter"
    
    def test_service_validates_request_id(self):
        """Service should validate request_id is provided"""
        db = DatabaseSession()
        
        # Calling with None request_id should raise error
        with pytest.raises(ValueError, match="request_id is mandatory"):
            user_service.create(db, None, "Test", "test@example.com")


class TestExtensionContractCompliance:
    """Test that inter-slice communication uses contracts"""
    
    def test_user_contract_exists(self):
        """User contract should exist for inter-slice communication"""
        assert user_contract is not None
    
    def test_user_contract_has_get_by_id(self):
        """User contract should provide get_by_id method"""
        assert hasattr(user_contract, "get_user_by_id")
    
    def test_user_contract_has_verify_veteran_status(self):
        """User contract should provide verify_veteran_status method"""
        assert hasattr(user_contract, "verify_veteran_status")
    
    def test_contract_requires_request_id(self):
        """Contract methods should require request_id"""
        import inspect
        
        sig = inspect.signature(user_contract.get_user_by_id)
        params = list(sig.parameters.keys())
        
        assert "request_id" in params, "Contract must accept request_id parameter"


class TestDatabaseSessionCompliance:
    """Test database session behavior"""
    
    def test_session_has_flush_method(self):
        """Session should have flush method for services"""
        db = DatabaseSession()
        assert hasattr(db, "flush")
    
    def test_session_has_commit_method(self):
        """Session should have commit method for routes"""
        db = DatabaseSession()
        assert hasattr(db, "commit")
    
    def test_session_has_rollback_method(self):
        """Session should have rollback method for routes"""
        db = DatabaseSession()
        assert hasattr(db, "rollback")
    
    def test_flush_does_not_commit(self):
        """Flush should not commit the transaction"""
        db = DatabaseSession()
        db.add("test object")
        db.flush()
        
        assert not db._committed
    
    def test_commit_sets_committed_flag(self):
        """Commit should mark transaction as committed"""
        db = DatabaseSession()
        db.commit()
        
        assert db._committed
    
    def test_cannot_commit_after_rollback(self):
        """Should not be able to commit after rollback"""
        db = DatabaseSession()
        db.rollback()
        
        with pytest.raises(RuntimeError, match="Cannot commit after rollback"):
            db.commit()
