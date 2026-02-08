"""
Database configuration and session management.

Routes own the transaction scope, services only flush.
"""
from typing import Generator
from contextlib import contextmanager
import logging

logger = logging.getLogger(__name__)


class DatabaseSession:
    """
    Mock database session for demonstration.
    
    In production, this would be a SQLAlchemy session or similar.
    """
    
    def __init__(self):
        self._changes = []
        self._committed = False
        self._rolled_back = False
    
    def add(self, obj):
        """Add object to session"""
        self._changes.append(("add", obj))
        logger.debug(f"Added object to session: {obj}")
    
    def flush(self):
        """
        Flush changes to database without committing.
        
        This is what services should call - synchronizes with DB
        but doesn't commit the transaction.
        """
        logger.debug("Flushing session changes")
        # In real implementation, this would sync with DB
    
    def commit(self):
        """
        Commit the transaction.
        
        Only routes should call this.
        """
        if self._rolled_back:
            raise RuntimeError("Cannot commit after rollback")
        
        self.flush()
        self._committed = True
        logger.info("Transaction committed")
    
    def rollback(self):
        """
        Rollback the transaction.
        
        Only routes should call this.
        """
        self._changes.clear()
        self._rolled_back = True
        logger.info("Transaction rolled back")
    
    def close(self):
        """Close the session"""
        logger.debug("Session closed")


@contextmanager
def get_db_session() -> Generator[DatabaseSession, None, None]:
    """
    Get a database session.
    
    The route layer should use this to get a session and manage
    the transaction lifecycle (commit/rollback).
    """
    session = DatabaseSession()
    try:
        yield session
    finally:
        session.close()
